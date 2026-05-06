"""Live PiSugar polling and watchdog cadence helpers for the power seam."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any, cast

from loguru import logger
from yoyopod_cli.pi.support.power_integration.policies import PowerSafetyPolicy

if TYPE_CHECKING:
    from yoyopod_cli.pi.support.power_integration.models import PowerSnapshot


class PowerRuntimeService:
    """Own power refresh and watchdog work that should stay out of generic recovery."""

    _SLOW_POWER_REFRESH_WARNING_SECONDS = 0.25
    _SLOW_WATCHDOG_FEED_WARNING_SECONDS = 0.25

    def __init__(self, app: Any) -> None:
        self.app = app
        self._power_io_lock = threading.Lock()
        self._watchdog_io_lock = threading.Lock()
        self._policy: PowerSafetyPolicy | None = None

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
            if self.app._power_refresh_in_flight:
                self._publish_cached_snapshot_if_ready()
                return

            self._start_power_refresh_worker()
            return

        self._start_power_refresh_worker()

    def _start_power_refresh_worker(self) -> None:
        """Schedule one background refresh when no worker is already running."""

        if self.app._power_refresh_in_flight:
            return

        self.app._power_refresh_in_flight = True
        self.app.background.power.submit(self.run_power_refresh_attempt)

    def run_power_refresh_attempt(self) -> None:
        """Collect one PiSugar snapshot off the coordinator thread."""

        snapshot = self._refresh_snapshot()
        self.app.runtime_loop.queue_main_thread_callback(
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
        return cast("PowerSnapshot", snapshot)

    def _complete_refresh(self, *, snapshot: "PowerSnapshot") -> None:
        """Publish one completed power refresh back onto the coordinator thread."""

        self.app._power_refresh_in_flight = False
        self._publish_snapshot(snapshot=snapshot)

    def _publish_cached_snapshot_if_ready(self) -> None:
        """Publish cached power state only when a prior refresh already established runtime state."""

        if self.app.power_manager is None:
            return

        runtime = self.app.app_state_runtime
        if runtime is None:
            return
        if runtime.power_snapshot is None:
            return

        self._publish_snapshot(snapshot=self.app.power_manager.get_snapshot())

    def _publish_snapshot(self, *, snapshot: "PowerSnapshot") -> None:
        """Publish one power snapshot onto the coordinator thread."""

        runtime = self.app.app_state_runtime
        if runtime is None:
            return
        if runtime.power_snapshot == snapshot and self.app._power_available == snapshot.available:
            return

        self.handle_snapshot_updated(snapshot)

        if self.app._power_available is None or self.app._power_available != snapshot.available:
            reason = snapshot.error or ("ready" if snapshot.available else "unavailable")
            self.app._power_available = snapshot.available
            self.handle_availability_change(snapshot.available, reason)

    def handle_snapshot_updated(self, snapshot: "PowerSnapshot") -> None:
        """Apply the latest power telemetry to runtime and UI state."""

        previous_signature = self._snapshot_signature(
            self.app.app_state_runtime.power_snapshot
            if self.app.app_state_runtime is not None
            else None
        )
        if self.app.app_state_runtime is not None:
            self.app.app_state_runtime.set_power_snapshot(snapshot)
        if self.app.context is not None:
            self.app.context.update_power_status(snapshot)

        current_signature = self._snapshot_signature(snapshot)
        if current_signature != previous_signature:
            if self.app.screen_manager is not None:
                self.app.screen_manager.refresh_current_screen()

        if self.app.cloud_manager is not None:
            level = snapshot.battery.level_percent
            charging = snapshot.battery.charging
            if level is not None:
                self.app.cloud_manager.publish_battery(
                    level=round(level),
                    charging=bool(charging),
                    now=time.monotonic(),
                )

        policy = self._power_safety_policy()
        if policy is None:
            return

        for event in policy.evaluate(snapshot, now=time.monotonic()):
            self.app.bus.publish(event)

    def handle_availability_change(self, available: bool, reason: str) -> None:
        """Track power backend reachability for the runtime."""

        if self.app.app_state_runtime is not None:
            self.app.app_state_runtime.set_power_available(available)
        if available:
            logger.info(f"Power backend available ({reason or 'ready'})")
            return

        logger.warning(f"Power backend unavailable ({reason or 'unknown'})")
        policy = self._power_safety_policy()
        if policy is not None:
            policy.shutdown_requested = False
            policy.next_warning_at = 0.0

    def _power_safety_policy(self) -> PowerSafetyPolicy | None:
        """Return the live power safety policy for the active manager config."""

        power_manager = self.app.power_manager
        if power_manager is None:
            self._policy = None
            return None

        power_config = getattr(power_manager, "config", None)
        if power_config is None:
            self._policy = None
            return None
        if self._policy is None or self._policy.config is not power_config:
            self._policy = PowerSafetyPolicy(power_config)
        return self._policy

    @staticmethod
    def _snapshot_signature(snapshot: "PowerSnapshot | None") -> tuple[object, ...] | None:
        """Return the stable, user-visible subset of a power snapshot."""

        if snapshot is None:
            return None

        return (
            snapshot.available,
            snapshot.error,
            snapshot.device.model,
            snapshot.device.firmware_version,
            snapshot.battery.level_percent,
            snapshot.battery.voltage_volts,
            snapshot.battery.charging,
            snapshot.battery.power_plugged,
            snapshot.battery.allow_charging,
            snapshot.battery.output_enabled,
            snapshot.battery.temperature_celsius,
            snapshot.rtc.time,
            snapshot.rtc.alarm_enabled,
            snapshot.rtc.alarm_time,
            snapshot.rtc.alarm_repeat_mask,
            snapshot.rtc.adjust_ppm,
            snapshot.shutdown.safe_shutdown_level_percent,
            snapshot.shutdown.safe_shutdown_delay_seconds,
        )

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

        with self._watchdog_io_lock:
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
        self.app.background.watchdog.submit(self.run_watchdog_feed_attempt)

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
            with self._watchdog_io_lock:
                success = power_manager.feed_watchdog()
            duration_seconds = max(0.0, time.monotonic() - started_at)
            if duration_seconds >= self._SLOW_WATCHDOG_FEED_WARNING_SECONDS:
                logger.warning(
                    "Watchdog feed worker slow: duration_ms={:.1f}",
                    duration_seconds * 1000.0,
                )

        completed_at = time.monotonic()
        self.app.runtime_loop.queue_main_thread_callback(
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
            with self._watchdog_io_lock:
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
