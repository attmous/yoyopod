"""Canonical app-facing power manager facade."""

from __future__ import annotations

from dataclasses import replace
import shlex
import subprocess
from datetime import datetime
from typing import TYPE_CHECKING, Callable

from loguru import logger

from yoyopod.backends.power import (
    PiSugarBackend,
    PiSugarWatchdog,
    PowerBackend,
    WatchdogCommandError,
)
from yoyopod_cli.config.models import PowerConfig
from yoyopod.integrations.power.models import PowerSnapshot, RTCState

if TYPE_CHECKING:
    from yoyopod_cli.config import ConfigManager


ShutdownHook = Callable[[], None]
ShutdownRunner = Callable[[list[str]], int]


class PowerManager:
    """Coordinate power backend access and retain the latest snapshot."""

    def __init__(
        self,
        config: PowerConfig,
        backend: PowerBackend | None = None,
        shutdown_runner: ShutdownRunner | None = None,
        watchdog: PiSugarWatchdog | None = None,
    ) -> None:
        self.config = config
        self.backend = backend or PiSugarBackend(config)
        self._shutdown_runner = shutdown_runner or self._default_shutdown_runner
        self.watchdog = watchdog or (
            PiSugarWatchdog(config) if config.watchdog_enabled else None
        )
        self._shutdown_hooks: list[tuple[str, ShutdownHook]] = []
        self.last_snapshot = PowerSnapshot(
            available=False,
            checked_at=datetime.now(),
            error="power snapshot not collected yet",
        )

    @classmethod
    def from_config_manager(cls, config_manager: "ConfigManager") -> "PowerManager":
        """Build a power manager from the typed power-domain configuration."""

        return cls(replace(config_manager.get_power_settings()))

    def probe(self) -> bool:
        """Return True when the configured backend is reachable."""
        if not self.config.enabled:
            return False
        return self.backend.probe()

    def refresh(self) -> PowerSnapshot:
        """Collect and store a new snapshot from the backend."""
        if self._should_fast_fail_refresh():
            previous_error = self.last_snapshot.error.strip()
            self.last_snapshot = PowerSnapshot(
                available=False,
                checked_at=datetime.now(),
                source=self.last_snapshot.source,
                error=(
                    previous_error
                    if previous_error and previous_error != "power snapshot not collected yet"
                    else "power backend unavailable"
                ),
            )
            return self.last_snapshot

        try:
            self.last_snapshot = self.backend.get_snapshot()
        except Exception as exc:
            logger.error(f"Power snapshot refresh failed: {exc}")
            self.last_snapshot = PowerSnapshot(
                available=False,
                checked_at=datetime.now(),
                error=str(exc),
            )
        return self.last_snapshot

    def _should_fast_fail_refresh(self) -> bool:
        """Avoid repeated full PiSugar sweeps when the backend is already known offline."""
        if not self.config.enabled or self.last_snapshot.available:
            return False

        try:
            return not self.probe()
        except Exception as exc:
            logger.debug(f"Power probe failed during refresh gate: {exc}")
            return True

    def get_snapshot(self, refresh: bool = False) -> PowerSnapshot:
        """Return the cached snapshot, optionally refreshing first."""
        if refresh:
            return self.refresh()
        return self.last_snapshot

    def get_battery_percentage(self, refresh: bool = False) -> float | None:
        """Return the current battery percentage when available."""
        snapshot = self.get_snapshot(refresh=refresh)
        return snapshot.battery.level_percent

    def get_rtc_state(self, refresh: bool = False) -> RTCState:
        """Return the latest RTC state, optionally refreshing first."""
        snapshot = self.get_snapshot(refresh=refresh)
        return snapshot.rtc

    def sync_time_to_rtc(self) -> RTCState:
        """Sync Raspberry Pi system time to the PiSugar RTC and return fresh RTC state."""
        self.backend.sync_time_to_rtc()
        return self.get_rtc_state(refresh=True)

    def sync_time_from_rtc(self) -> RTCState:
        """Sync PiSugar RTC time to the Raspberry Pi system clock and return fresh RTC state."""
        self.backend.sync_time_from_rtc()
        return self.get_rtc_state(refresh=True)

    def set_rtc_alarm(self, when: datetime, repeat_mask: int = 127) -> RTCState:
        """Set the PiSugar RTC wake alarm and return fresh RTC state."""
        self.backend.set_rtc_alarm(when, repeat_mask)
        return self.get_rtc_state(refresh=True)

    def disable_rtc_alarm(self) -> RTCState:
        """Disable the PiSugar RTC wake alarm and return fresh RTC state."""
        self.backend.disable_rtc_alarm()
        return self.get_rtc_state(refresh=True)

    def enable_watchdog(self) -> bool:
        """Enable and immediately feed the PiSugar software watchdog."""
        if self.watchdog is None:
            logger.info("Power watchdog not configured")
            return False

        try:
            self.watchdog.enable()
        except WatchdogCommandError as exc:
            logger.error(f"Failed to enable power watchdog: {exc}")
            return False
        return True

    def feed_watchdog(self) -> bool:
        """Feed the PiSugar software watchdog once."""
        if self.watchdog is None:
            return False

        try:
            self.watchdog.feed()
        except WatchdogCommandError as exc:
            logger.error(f"Failed to feed power watchdog: {exc}")
            return False
        return True

    def disable_watchdog(self) -> bool:
        """Disable the PiSugar software watchdog."""
        if self.watchdog is None:
            return False

        try:
            self.watchdog.disable()
        except WatchdogCommandError as exc:
            logger.error(f"Failed to disable power watchdog: {exc}")
            return False
        return True

    def register_shutdown_hook(self, name: str, hook: ShutdownHook) -> None:
        """Register one callable to run before a graceful poweroff."""
        self._shutdown_hooks.append((name, hook))

    def run_shutdown_hooks(self) -> list[str]:
        """Run graceful-shutdown hooks and return any failing hook names."""
        failed_hooks: list[str] = []
        for name, hook in self._shutdown_hooks:
            try:
                hook()
            except Exception as exc:
                logger.error(f"Shutdown hook failed ({name}): {exc}")
                failed_hooks.append(name)
        return failed_hooks

    def request_system_shutdown(self) -> bool:
        """Execute the configured system shutdown command."""
        command = shlex.split(self.config.shutdown_command)
        if not command:
            logger.warning("No power shutdown command configured")
            return False

        return_code = self._shutdown_runner(command)
        if return_code != 0:
            logger.error(
                "System shutdown command failed (code {}): {}",
                return_code,
                self.config.shutdown_command,
            )
            return False
        return True

    @staticmethod
    def _default_shutdown_runner(command: list[str]) -> int:
        """Execute the real shutdown command via subprocess."""
        completed = subprocess.run(command, check=False)
        return completed.returncode


__all__ = ["PowerManager", "ShutdownHook", "ShutdownRunner"]
