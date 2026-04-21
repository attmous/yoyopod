"""PPP backend wrapper for the scaffold network integration."""

from __future__ import annotations

from yoyopod.network.ppp import PppProcess


class PPPBackend:
    """Wrap the legacy `PppProcess` behind scaffold-friendly methods."""

    def __init__(self, config: object, *, process: PppProcess | None = None) -> None:
        self._config = config
        self._process = process or PppProcess(
            serial_port=str(getattr(config, "ppp_port")),
            apn=str(getattr(config, "apn", "")),
            baud_rate=int(getattr(config, "baud_rate", 115200)),
        )

    def bring_up(self) -> bool:
        """Spawn PPP and wait for the link."""

        if not self._process.spawn():
            return False
        return self._process.wait_for_link(timeout=float(getattr(self._config, "ppp_timeout", 30)))

    def tear_down(self) -> None:
        """Terminate the PPP process."""

        self._process.kill()

    def is_up(self) -> bool:
        """Return whether the PPP subprocess still looks alive."""

        return self._process.is_alive()
