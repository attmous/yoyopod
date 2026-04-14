"""Recovery, watchdog, and manager-health supervision helpers."""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from loguru import logger

from yoyopy.events import RecoveryAttemptCompletedEvent

if TYPE_CHECKING:
    from yoyopy.app import YoyoPodApp
    from yoyopy.runtime.models import RecoveryState


class RecoverySupervisor:
    """Supervise recoverable backends and the PiSugar watchdog."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app

    def handle_recovery_attempt_completed_event(
        self,
        event: RecoveryAttemptCompletedEvent,
    ) -> None:
        """Finalize background recovery attempts on the coordinator thread."""
        if event.manager != "music":
            return

        self.app._music_recovery.in_flight = False
        if self.app._stopping:
            return

        if event.recovered and self.app.music_backend:
            if hasattr(self.app.music_backend, "polling") and not getattr(
                self.app.music_backend,
                "polling",
            ):
                start_polling = getattr(self.app.music_backend, "start_polling", None)
                if start_polling is not None:
                    start_polling()

        self.app._finalize_recovery_attempt(
            "Music",
            self.app._music_recovery,
            event.recovered,
            event.recovery_now,
        )

    def attempt_manager_recovery(self, now: float | None = None) -> None:
        """Try to recover VoIP and music when they become unavailable."""
        if self.app._stopping:
            return

        recovery_now = time.monotonic() if now is None else now
        self.app._attempt_voip_recovery(recovery_now)
        self.app._attempt_music_recovery(recovery_now)

    def poll_power_status(self, now: float | None = None, force: bool = False) -> None:
        """Refresh PiSugar power telemetry on the coordinator thread."""
        if self.app.power_manager is None:
            return

        poll_now = time.monotonic() if now is None else now
        if not force and poll_now < self.app._next_power_poll_at:
            return

        self.app._ensure_coordinators()
        assert self.app.power_coordinator is not None
        snapshot = self.app.power_manager.refresh()
        self.app.power_coordinator.publish_snapshot(snapshot)

        if self.app._power_available is None or self.app._power_available != snapshot.available:
            reason = snapshot.error or ("ready" if snapshot.available else "unavailable")
            self.app._power_available = snapshot.available
            self.app.power_coordinator.publish_availability_change(snapshot.available, reason)

        interval = max(1.0, self.app.power_manager.config.poll_interval_seconds)
        self.app._next_power_poll_at = poll_now + interval

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

        if not self.app.power_manager.enable_watchdog():
            logger.warning("Power watchdog could not be enabled")
            return

        watchdog_now = time.monotonic() if now is None else now
        self.app._watchdog_active = True
        self.app._watchdog_feed_suppressed = False
        self.app._next_watchdog_feed_at = watchdog_now + feed_interval
        logger.info(
            "Power watchdog enabled (timeout={}s, feed={}s)",
            timeout_seconds,
            feed_interval,
        )

    def feed_watchdog_if_due(self, now: float) -> None:
        """Feed the PiSugar software watchdog on the coordinator thread."""
        if not self.app._watchdog_active or self.app._watchdog_feed_suppressed:
            return

        if self.app.power_manager is None or now < self.app._next_watchdog_feed_at:
            return

        feed_interval = max(
            1.0,
            float(self.app.power_manager.config.watchdog_feed_interval_seconds),
        )
        if self.app.power_manager.feed_watchdog():
            self.app._next_watchdog_feed_at = now + feed_interval
            return

        self.app._next_watchdog_feed_at = now + min(feed_interval, 5.0)

    def disable_watchdog(self) -> None:
        """Disable the PiSugar watchdog during intentional app shutdowns."""
        if not self.app._watchdog_active:
            return

        if self.app.power_manager is not None and self.app.power_manager.disable_watchdog():
            logger.info("Power watchdog disabled for intentional stop")
        else:
            logger.warning("Failed to disable power watchdog cleanly")

        self.app._watchdog_active = False
        self.app._watchdog_feed_suppressed = False
        self.app._next_watchdog_feed_at = 0.0

    def suppress_watchdog_feeding(self, reason: str) -> None:
        """Stop feeding the watchdog without disabling it."""
        if not self.app._watchdog_active or self.app._watchdog_feed_suppressed:
            return

        self.app._watchdog_feed_suppressed = True
        logger.info(f"Power watchdog feeding suppressed: {reason}")

    def attempt_voip_recovery(self, recovery_now: float) -> None:
        """Restart the VoIP backend when it is not running."""
        if self.app.voip_manager is None:
            return

        if self.app.voip_manager.running:
            self.app._voip_recovery.reset()
            return

        if recovery_now < self.app._voip_recovery.next_attempt_at:
            return

        logger.info("Attempting VoIP recovery")
        self.app._finalize_recovery_attempt(
            "VoIP",
            self.app._voip_recovery,
            self.app.voip_manager.start(),
            recovery_now,
        )

    def start_music_backend(self) -> bool:
        """Start the current music backend using the available lifecycle API."""
        if self.app.music_backend is None:
            return False

        start = getattr(self.app.music_backend, "start", None)
        if start is not None:
            return bool(start())

        connect = getattr(self.app.music_backend, "connect", None)
        if connect is not None:
            return bool(connect())

        return False

    def attempt_music_recovery(self, recovery_now: float) -> None:
        """Reconnect the music backend when it becomes unavailable."""
        if self.app.music_backend is None:
            return

        if self.app.music_backend.is_connected:
            self.app._music_recovery.reset()
            return

        if self.app._music_recovery.in_flight:
            return

        if recovery_now < self.app._music_recovery.next_attempt_at:
            return

        logger.info("Attempting music backend recovery")
        self.app._music_recovery.in_flight = True
        self.app._start_music_recovery_worker(recovery_now)

    def start_music_recovery_worker(self, recovery_now: float) -> None:
        """Launch the non-blocking music recovery attempt worker."""
        worker = threading.Thread(
            target=self.app._run_music_recovery_attempt,
            args=(recovery_now,),
            daemon=True,
            name="music-recovery",
        )
        worker.start()

    def run_music_recovery_attempt(self, recovery_now: float) -> None:
        """Run a single music recovery attempt off the coordinator thread."""
        recovered = False
        if not self.app._stopping and self.app.music_backend is not None:
            recovered = self.app._start_music_backend()

        self.app.event_bus.publish(
            RecoveryAttemptCompletedEvent(
                manager="music",
                recovered=recovered,
                recovery_now=recovery_now,
            )
        )

    def finalize_recovery_attempt(
        self,
        label: str,
        state: "RecoveryState",
        recovered: bool,
        recovery_now: float,
    ) -> None:
        """Update reconnect backoff after a recovery attempt."""
        if recovered:
            logger.info(f"{label} recovery succeeded")
            state.reset()
            return

        retry_in = state.delay_seconds
        logger.warning(f"{label} recovery failed, retrying in {retry_in:.0f}s")
        state.next_attempt_at = recovery_now + retry_in
        state.delay_seconds = min(
            state.delay_seconds * 2.0,
            self.app._RECOVERY_MAX_DELAY_SECONDS,
        )
