"""Network backend protocol and SIM7600G-H implementation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from loguru import logger

from yoyopod.network.at_commands import AtCommandSet
from yoyopod.network.gps import GpsReader
from yoyopod.network.models import GpsCoordinate, ModemPhase, ModemState
from yoyopod.network.ppp import PppProcess
from yoyopod.network.transport import SerialTransport

if TYPE_CHECKING:
    from yoyopod.config.models import NetworkConfig


class NetworkBackend(Protocol):
    """Read-only backend contract for cellular modem integrations."""

    def probe(self) -> bool: ...
    def get_state(self) -> ModemState: ...


class Sim7600Backend:
    """SIM7600G-H modem backend over UART."""

    def __init__(self, config: "NetworkConfig") -> None:
        self._config = config
        self._transport = SerialTransport(
            port=config.serial_port,
            baud_rate=config.baud_rate,
        )
        self._at = AtCommandSet(self._transport)
        self._ppp = PppProcess(
            serial_port=config.ppp_port,
            apn=config.apn,
            baud_rate=config.baud_rate,
        )
        self._gps = GpsReader(self._transport)
        self._state = ModemState()

    def probe(self) -> bool:
        try:
            return self._at.ping()
        except Exception as exc:
            logger.error("Modem probe failed: {}", exc)
            return False

    def get_state(self) -> ModemState:
        return self._state

    def open(self) -> None:
        self._transport.open()
        self._state.phase = ModemPhase.PROBING

    def close(self) -> None:
        self.stop_ppp()
        try:
            self._at.hangup()
        except Exception:
            pass
        self._transport.close()
        self._state.phase = ModemPhase.OFF

    def init_modem(self) -> None:
        self._state.phase = ModemPhase.READY
        self._at.echo_off()

        self._state.sim_ready = self._at.check_sim()
        if not self._state.sim_ready:
            self._state.error = "SIM not ready"
            logger.error("SIM not ready")
            return

        self._state.phase = ModemPhase.REGISTERING
        self._state.signal = self._at.get_signal_quality()

        carrier, network_type = self._at.get_carrier()
        self._state.carrier = carrier
        self._state.network_type = network_type

        if not self._at.get_registration():
            self._state.error = "Not registered on network"
            logger.error("Network registration failed")
            return

        self._state.phase = ModemPhase.REGISTERED
        self._state.error = ""
        logger.info(
            "Modem ready: carrier={}, type={}, signal={}bars",
            carrier,
            network_type,
            self._state.signal.bars,
        )

        if self._config.gps_enabled:
            self._at.enable_gps()

    def start_ppp(self) -> bool:
        self._state.phase = ModemPhase.PPP_STARTING
        apn = self._config.apn.strip()
        if apn:
            self._at.configure_pdp(apn)
        else:
            logger.warning("Network APN is empty; leaving modem PDP context unchanged")

        if not self._ppp.spawn():
            self._state.phase = ModemPhase.REGISTERED
            self._state.error = "PPP failed to start"
            return False

        if not self._ppp.wait_for_link(timeout=self._config.ppp_timeout):
            self._ppp.kill()
            self._state.phase = ModemPhase.REGISTERED
            self._state.error = "PPP negotiation timed out"
            return False

        self._state.phase = ModemPhase.ONLINE
        self._state.error = ""
        return True

    def stop_ppp(self) -> None:
        if self._ppp.is_alive():
            self._state.phase = ModemPhase.PPP_STOPPING
            self._ppp.kill()
            self._state.phase = ModemPhase.REGISTERED

    def query_gps(self) -> GpsCoordinate | None:
        """Query GPS. Safe to call during active PPP since AT and PPP use separate USB ports."""
        coord = self._gps.query()
        self._state.gps = coord
        return coord
