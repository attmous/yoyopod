"""Cellular modem wrapper for the scaffold network integration."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.backends.network.at_commands import AtCommandSet
from yoyopod.backends.network.transport import SerialTransport
from yoyopod.network.models import SignalInfo


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
