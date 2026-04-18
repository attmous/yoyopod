"""Power-domain runtime service for PiSugar polling and watchdog cadence."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp
    from yoyopod.power.models import PowerSnapshot


class PowerRuntimeService:
    """Own power refresh and watchdog work that should stay out of generic recovery."""

    _SLOW_POWER_REFRESH_WARNING_SECONDS = 0.25
    _SLOW_WATCHDOG_FEED_WARNING_SECONDS = 0.25

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app
        self._power_io_lock = threading.Lock()

    def poll_status(self, now: float | None = None, force: bool = False) -> None:
        """Refresh PiSugar power telemetry without stalling the coordinator loop."""
        if self.app.power_manager is None:
            return

        poll_now = time.monotonic() if now is None else now
        if not force and poll_now < self.app._next_power_poll_at:
            return

        interval = max(1.0, self.app.power_manager.config.poll_interval_seconds)
        self.app._next_power_poll_at = poll_now + interval

        if force:
            snapshot = self._refresh_snapshot()
            self._complete_refresh(snapshot=snapshot)
            return

        if self.app._power_refresh_in_flight:
            return

        self.app._power_refresh_in_flight = True
        worker = threading.Thread(
            target=self.run_power_refresh_attempt,
            daemon=True,
            name="power-refresh",
        )
        worker.start()

    def run_power_refresh_attempt(self) -> None:
        """Collect one PiSugar snapshot off the coordinator thread."""

        snapshot = self._refresh_snapshot()
        self.app._queue_main_thread_callback(
            lambda snapshot=snapshot: self._complete_refresh(snapshot=snapshot),
            safety=True,
        )

    def _refresh_snapshot(self) -> "PowerSnapshot":
        """Collect one PiSugar snapshot under the shared power-I/O lock."""

        assert self.app.power_manager is not None
        started_at = time.monotonic()
        with self._power_io_lock:
            snapshot = self.app.power_manager.refresh()
        duration_seconds = max(0.0, time.monotonic() - started_at)
        if duration_seconds >= self._SLOW_POWER_REFRESH_WARNING_SECONDS:
            logger.warning(
                "Power refresh worker slow: duration_ms={:.1f}",
                duration_seconds * 1000.0,
            )
        return snapshot

    def _complete_refresh(self, *, snapshot: "PowerSnapshot") -> None:
        """Publish one completed power refresh back onto the coordinator thread."""

        self.app._power_refresh_in_flight = False
        self.app.boot_service.ensure_coordinators()
        assert self.app.power_coordinator is not None
        self.app.power_coordinator.publish_snapshot(snapshot)

        if self.app._power_available is None or self.app._power_available != snapshot.available:
            reason = snapshot.error or ("ready" if snapshot.available else "unavailable")
            self.app._power_available = snapshot.available
            self.app.power_coordinator.publish_availability_change(snapshot.available, reason)

    def start_watchdog(self, now: float | None = None) -> None:
        """Enable the PiSugar software watchdog once the app loop is ready."""
        if self.app.simulate or self.app.power_manager is None:
            return

        if not self.app.power_manager.config.watchdog_enabled or self.app._watchdog_active:
            return

        feed_interval = max(
            1.0,
            float(self.app.power_manager.config.watchdog_feed_interval_seconds),
        )
        timeout_seconds = max(1, int(self.app.power_manager.config.watchdog_timeout_seconds))
        if feed_interval >= timeout_seconds:
            logger.warning(
                "Power watchdog feed interval ({}) should be less than timeout ({})",
                feed_interval,
                timeout_seconds,
            )

        with self._power_io_lock:
            enabled = self.app.power_manager.enable_watchdog()
        if not enabled:
            logger.warning("Power watchdog could not be enabled")
            return

        watchdog_now = time.monotonic() if now is None else now
        self.app._watchdog_active = True
        self.app._watchdog_feed_in_flight = False
        self.app._watchdog_feed_suppressed = False
        self.app._next_watchdog_feed_at = watchdog_now + feed_interval
        logger.info(
            "Power watchdog enabled (timeout={}s, feed={}s)",
            timeout_seconds,
            feed_interval,
        )

    def feed_watchdog_if_due(self, now: float) -> None:
        """Feed the PiSugar software watchdog without blocking the coordinator loop."""
        if not self.app._watchdog_active or self.app._watchdog_feed_suppressed:
            return

        if self.app.power_manager is None or now < self.app._next_watchdog_feed_at:
            return

        if self.app._watchdog_feed_in_flight:
            return

        self.app._watchdog_feed_in_flight = True
        worker = threading.Thread(
            target=self.run_watchdog_feed_attempt,
            daemon=True,
            name="power-watchdog-feed",
        )
        worker.start()

    def run_watchdog_feed_attempt(self) -> None:
        """Feed the watchdog off the coordinator thread and report the outcome."""

        power_manager = self.app.power_manager
        feed_interval = 1.0
        success = False
        if power_manager is not None:
            feed_interval = max(
                1.0,
                float(power_manager.config.watchdog_feed_interval_seconds),
            )
            started_at = time.monotonic()
            with self._power_io_lock:
                success = power_manager.feed_watchdog()
            duration_seconds = max(0.0, time.monotonic() - started_at)
            if duration_seconds >= self._SLOW_WATCHDOG_FEED_WARNING_SECONDS:
                logger.warning(
                    "Watchdog feed worker slow: duration_ms={:.1f}",
                    duration_seconds * 1000.0,
                )

        completed_at = time.monotonic()
        self.app._queue_main_thread_callback(
            lambda success=success, completed_at=completed_at, feed_interval=feed_interval: self._complete_watchdog_feed(
                success=success,
                completed_at=completed_at,
                feed_interval=feed_interval,
            ),
            safety=True,
        )

    def _complete_watchdog_feed(
        self,
        *,
        success: bool,
        completed_at: float,
        feed_interval: float,
    ) -> None:
        """Update watchdog cadence after one off-thread feed attempt completes."""

        self.app._watchdog_feed_in_flight = False
        if not self.app._watchdog_active:
            return

        if success:
            self.app._next_watchdog_feed_at = completed_at + feed_interval
            return

        self.app._next_watchdog_feed_at = completed_at + min(feed_interval, 5.0)

    def disable_watchdog(self) -> None:
        """Disable the PiSugar watchdog during intentional app shutdowns."""
        if not self.app._watchdog_active:
            return

        disabled = False
        if self.app.power_manager is not None:
            with self._power_io_lock:
                disabled = self.app.power_manager.disable_watchdog()
        if disabled:
            logger.info("Power watchdog disabled for intentional stop")
        else:
            logger.warning("Failed to disable power watchdog cleanly")

        self.app._watchdog_active = False
        self.app._watchdog_feed_in_flight = False
        self.app._watchdog_feed_suppressed = False
        self.app._next_watchdog_feed_at = 0.0

    def suppress_watchdog_feeding(self, reason: str) -> None:
        """Stop feeding the watchdog without disabling it."""
        if not self.app._watchdog_active or self.app._watchdog_feed_suppressed:
            return

        self.app._watchdog_feed_suppressed = True
        logger.info(f"Power watchdog feeding suppressed: {reason}")
