"""Runtime loop scheduling and coordinator-thread queues."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, Callable, Optional

from loguru import logger

if TYPE_CHECKING:
    from yoyopy.app import YoyoPodApp


class RuntimeLoopService:
    """Own the coordinator loop cadence and queued main-thread work."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app

    def process_pending_main_thread_actions(self, limit: Optional[int] = None) -> int:
        """Drain queued typed events scheduled by worker threads."""
        processed = 0
        while not self.app._pending_main_thread_callbacks.empty():
            callback = self.app._pending_main_thread_callbacks.get()
            try:
                callback()
            except Exception as exc:
                logger.error(f"Error handling scheduled main-thread callback: {exc}")
            processed += 1
            if limit is not None and processed >= limit:
                return processed

        remaining_limit = None if limit is None else max(0, limit - processed)
        return processed + self.app.event_bus.drain(remaining_limit)

    def queue_main_thread_callback(self, callback: Callable[[], None]) -> None:
        """Schedule a callback to run on the coordinator thread."""
        self.app._pending_main_thread_callbacks.put(callback)

    def queue_lvgl_input_action(self, action: Any, _data: Optional[Any] = None) -> None:
        """Queue semantic actions for LVGL from input polling threads."""
        if self.app._lvgl_input_bridge is None:
            return
        self.app._lvgl_input_bridge.enqueue_action(action)

    def pump_lvgl_backend(self, now: float | None = None) -> None:
        """Pump LVGL timers and queued input on the coordinator thread."""
        if self.app._lvgl_backend is None or not self.app._lvgl_backend.initialized:
            return

        monotonic_now = time.monotonic() if now is None else now
        if self.app._last_lvgl_pump_at <= 0.0:
            delta_ms = 0
        else:
            delta_ms = int(max(0.0, monotonic_now - self.app._last_lvgl_pump_at) * 1000.0)
        self.app._last_lvgl_pump_at = monotonic_now

        if self.app._lvgl_input_bridge is not None:
            self.app._lvgl_input_bridge.process_pending()
        self.app._lvgl_backend.pump(delta_ms)

    def iterate_voip_backend_if_due(self, now: float | None = None) -> None:
        """Advance the Liblinphone core on the coordinator thread at its configured cadence."""
        if self.app.voip_manager is None or not self.app.voip_manager.running:
            return

        monotonic_now = time.monotonic() if now is None else now
        if self.app._next_voip_iterate_at <= 0.0:
            self.app._next_voip_iterate_at = monotonic_now

        if monotonic_now < self.app._next_voip_iterate_at:
            return

        self.app.voip_manager.iterate()
        self.app._next_voip_iterate_at = monotonic_now + self.app._voip_iterate_interval_seconds

    def run_iteration(
        self,
        *,
        monotonic_now: float,
        current_time: float,
        last_screen_update: float,
        screen_update_interval: float,
    ) -> float:
        """Run one coordinator-loop iteration and return the next screen refresh timestamp."""
        self.iterate_voip_backend_if_due(monotonic_now)
        self.process_pending_main_thread_actions()
        self.app.recovery_service.attempt_manager_recovery(now=monotonic_now)
        self.app.recovery_service.poll_power_status(now=monotonic_now)
        self.pump_lvgl_backend(monotonic_now)
        self.app.recovery_service.feed_watchdog_if_due(monotonic_now)
        self.app.shutdown_service.process_pending_shutdown(monotonic_now)
        if self.app._shutdown_completed:
            return last_screen_update

        self.app.screen_power_service.update_screen_power(monotonic_now)
        overlay_active = self.app.screen_power_service.update_power_overlays(monotonic_now)
        if overlay_active:
            return current_time

        if not self.app._screen_awake:
            return current_time

        if current_time - last_screen_update >= screen_update_interval:
            self.app.boot_service.ensure_coordinators()
            assert self.app.playback_coordinator is not None
            assert self.app.screen_coordinator is not None
            self.app.playback_coordinator.update_now_playing_if_needed()
            self.app.screen_coordinator.update_in_call_if_needed()
            self.app.screen_coordinator.update_power_screen_if_needed()
            return current_time

        return last_screen_update

    def log_startup_status(self) -> None:
        """Emit the current runtime snapshot before entering the main loop."""
        assert self.app.coordinator_runtime is not None
        logger.info("=" * 60)
        logger.info("YoyoPod Running")
        logger.info("=" * 60)
        logger.info("")
        logger.info("Coordinator Status:")
        logger.info(f"  Current state: {self.app.coordinator_runtime.get_state_name()}")
        logger.info("")
        logger.info("VoIP Status:")
        if self.app.voip_manager:
            status = self.app.voip_manager.get_status()
            logger.info(f"  Running: {status['running']}")
            logger.info(f"  Registered: {status['registered']}")
            logger.info(f"  SIP Identity: {status.get('sip_identity', 'N/A')}")
        else:
            logger.info("  VoIP not available")
        logger.info("")
        logger.info("Music Status:")
        if self.app.music_backend and self.app.music_backend.is_connected:
            logger.info("  Connected: True")
            playback_state = self.app.music_backend.get_playback_state()
            logger.info(f"  Playback state: {playback_state}")
        else:
            logger.info("  Music backend not connected")
        logger.info("")
        logger.info("Power Status:")
        if self.app.power_manager:
            power_snapshot = self.app.power_manager.get_snapshot()
            logger.info(f"  Available: {power_snapshot.available}")
            if power_snapshot.device.model:
                logger.info(f"  Model: {power_snapshot.device.model}")
            if power_snapshot.battery.level_percent is not None:
                logger.info(f"  Battery: {power_snapshot.battery.level_percent:.1f}%")
            if power_snapshot.battery.charging is not None:
                logger.info(f"  Charging: {power_snapshot.battery.charging}")
            if power_snapshot.battery.power_plugged is not None:
                logger.info(f"  External power: {power_snapshot.battery.power_plugged}")
            logger.info(f"  Watchdog enabled: {self.app.power_manager.config.watchdog_enabled}")
        else:
            logger.info("  Power backend not configured")
        logger.info("")
        logger.info("Display Status:")
        if self.app.display is not None:
            logger.info(f"  Backend: {self.app.display.backend_kind}")
            logger.info(f"  Orientation: {self.app.display.ORIENTATION}")
        else:
            logger.info("  Display not initialized")
        logger.info("")
        logger.info("Integration Settings:")
        logger.info(f"  Auto-resume after call: {self.app.auto_resume_after_call}")
        logger.info("")
        logger.info("=" * 60)
        logger.info("System Status:")
        logger.info("  - VoIP and music managers are initialized")
        logger.info("  - Callbacks are registered")
        logger.info("  - State transitions will be logged")
        logger.info("  - Full screen integration active")
        logger.info("")
        logger.info("Press Ctrl+C to exit")
        logger.info("=" * 60)

    def run(self) -> None:
        """Run the main application loop until interrupted."""
        self.log_startup_status()

        try:
            last_screen_update = time.time()
            screen_update_interval = 1.0
            self.app.recovery_service.start_watchdog(now=time.monotonic())

            if self.app.simulate:
                logger.info("")
                logger.info("Simulation mode: Application running...")
                logger.info("  (Incoming calls and track changes will trigger callbacks)")
                logger.info("")

            while not self.app._stopping:
                time.sleep(min(0.05, self.app._voip_iterate_interval_seconds))
                monotonic_now = time.monotonic()
                current_time = time.time()
                last_screen_update = self.run_iteration(
                    monotonic_now=monotonic_now,
                    current_time=current_time,
                    last_screen_update=last_screen_update,
                    screen_update_interval=screen_update_interval,
                )
                if self.app._shutdown_completed:
                    break
        except KeyboardInterrupt:
            logger.info("\n" + "=" * 60)
            logger.info("Shutting down...")
            logger.info("=" * 60)
        finally:
            if not self.app._shutdown_completed and not self.app._stopping:
                self.app.stop()
