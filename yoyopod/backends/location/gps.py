"""GPS query helpers plus scaffold backend wrapper for the SIM7600 path."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yoyopod.backends.network.at_commands import AtCommandSet
from yoyopod.backends.network.transport import SerialTransport

if TYPE_CHECKING:
    from yoyopod.integrations.network.models import GpsCoordinate


class GpsReader:
    """Query GPS position via AT commands on the SIM7600G-H."""

    def __init__(self, transport: object) -> None:
        self._at = AtCommandSet(transport)

    def enable(self) -> bool:
        """Enable the GPS engine on the modem."""

        return self._at.enable_gps()

    def disable(self) -> None:
        """Disable the GPS engine."""

        self._at.disable_gps()

    def query(self) -> "GpsCoordinate | None":
        """Query current GPS fix. Returns None if no fix available."""

        return self._at.query_gps()


class GpsBackend:
    """Own a GPS reader plus its serial transport for scaffold usage."""

    def __init__(self, config: object, *, transport: object | None = None) -> None:
        self._transport = transport or SerialTransport(
            port=str(getattr(config, "serial_port")),
            baud_rate=int(getattr(config, "baud_rate", 115200)),
        )
        self._owns_transport = transport is None
        self._reader = GpsReader(self._transport)

    def enable(self) -> bool:
        """Enable the GPS engine and return whether the modem accepted it."""

        self._ensure_open()
        return self._reader.enable()

    def disable(self) -> None:
        """Disable the GPS engine."""

        self._ensure_open()
        self._reader.disable()

    def get_fix(self) -> Any | None:
        """Return the latest GPS fix, or `None` when there is no fix."""

        self._ensure_open()
        return self._reader.query()

    def close(self) -> None:
        """Close the owned serial transport when this backend created it."""

        if self._owns_transport:
            self._transport.close()

    def _ensure_open(self) -> None:
        is_open = getattr(self._transport, "is_open", None)
        if is_open is True:
            return
        if callable(is_open) and is_open():
            return
        self._transport.open()


__all__ = ["GpsBackend", "GpsReader"]
