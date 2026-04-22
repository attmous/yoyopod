"""Cellular modem backends for scaffold and legacy runtime integrations."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from loguru import logger

from yoyopod.backends.location.gps import GpsReader
from yoyopod.backends.network.at_commands import AtCommandSet
from yoyopod.backends.network.ppp import PppProcess
from yoyopod.backends.network.transport import SerialTransport
from yoyopod.integrations.network.models import (
    GpsCoordinate,
    ModemPhase,
    ModemState,
    SignalInfo,
)

if TYPE_CHECKING:
    from yoyopod.config.models import NetworkConfig


class NetworkBackend(Protocol):
    """Read-only backend contract for cellular modem integrations."""

    def probe(self) -> bool: ...
    def get_state(self) -> ModemState: ...
    def is_online(self) -> bool: ...


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

    def is_online(self) -> bool:
        """Return True when the active PPP session still looks healthy."""

        if self._state.phase != ModemPhase.ONLINE:
            return False

        if not self._ppp.is_alive():
            self._state.phase = ModemPhase.REGISTERED
            self._state.error = "PPP process exited"
            return False

        if not Path("/sys/class/net/ppp0").exists():
            self._state.phase = ModemPhase.REGISTERED
            self._state.error = "PPP interface down"
            return False

        return True

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

    def start_ppp(self, *, wait_for_link: bool = True) -> bool:
        self._state.phase = ModemPhase.PPP_STARTING
        apn = str(self._config.apn or "").strip()
        if apn:
            self._at.configure_pdp(apn)
        else:
            logger.warning("Network APN is empty; leaving modem PDP context unchanged")

        if not self._ppp.spawn():
            self._state.phase = ModemPhase.REGISTERED
            self._state.error = "PPP failed to start"
            return False

        if not wait_for_link:
            return True

        return self.wait_for_ppp_link(timeout=self._config.ppp_timeout)

    def wait_for_ppp_link(self, timeout: float | None = None) -> bool:
        """Wait for the spawned PPP session to expose ppp0."""

        effective_timeout = self._config.ppp_timeout if timeout is None else timeout
        if not self._ppp.wait_for_link(timeout=effective_timeout):
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


@dataclass(frozen=True, slots=True)
class ModemStatus:
    """Compact registration snapshot exposed to the scaffold integration."""

    registered: bool
    carrier: str
    network_type: str
    available: bool = True
    reason: str = ""


class ModemBackend:
    """Own the modem AT transport used by scaffold network services."""

    def __init__(self, config: object, *, transport: object | None = None) -> None:
        self._transport = transport or SerialTransport(
            port=str(getattr(config, "serial_port")),
            baud_rate=int(getattr(config, "baud_rate", 115200)),
        )
        self._owns_transport = transport is None
        self._at = AtCommandSet(self._transport)

    def get_status(self) -> ModemStatus:
        """Return the latest registration snapshot."""

        try:
            self._ensure_open()
            if not self._at.ping():
                return ModemStatus(
                    registered=False,
                    carrier="",
                    network_type="",
                    available=False,
                    reason="ping_failed",
                )
            registered = bool(self._at.get_registration())
            carrier, network_type = self._at.get_carrier()
            return ModemStatus(
                registered=registered,
                carrier=carrier,
                network_type=network_type,
                available=True,
            )
        except Exception as exc:
            return ModemStatus(
                registered=False,
                carrier="",
                network_type="",
                available=False,
                reason=str(exc),
            )

    def get_signal(self) -> SignalInfo | None:
        """Return the latest signal sample, or `None` when unavailable."""

        try:
            self._ensure_open()
            return self._at.get_signal_quality()
        except Exception:
            return None

    def set_apn(self, *, apn: str, username: str = "", password: str = "") -> None:
        """Configure the modem PDP context for the given APN."""

        del username, password
        self._ensure_open()
        self._at.configure_pdp(apn)

    def close(self) -> None:
        """Close the owned serial transport when present."""

        if self._owns_transport:
            self._transport.close()

    def _ensure_open(self) -> None:
        is_open = getattr(self._transport, "is_open", None)
        if is_open is True:
            return
        if callable(is_open) and is_open():
            return
        self._transport.open()


__all__ = [
    "ModemBackend",
    "ModemStatus",
    "NetworkBackend",
    "Sim7600Backend",
]
