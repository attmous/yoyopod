"""Runtime loop scheduling and coordinator-thread queues."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar

from loguru import logger

from yoyopod.utils.logger import get_subsystem_logger

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


coord_logger = get_subsystem_logger("coord")
voip_logger = get_subsystem_logger("voip")
_T = TypeVar("_T")


@dataclass(slots=True)
class _VoipTimingWindow:
    """Rolling aggregate used for low-noise VoIP timing summaries."""

    started_at: float = 0.0
    samples: int = 0
    total_schedule_delay_seconds: float = 0.0
    max_schedule_delay_seconds: float = 0.0
    delayed_samples: int = 0
    total_iterate_duration_seconds: float = 0.0
    max_iterate_duration_seconds: float = 0.0
    max_native_iterate_duration_seconds: float = 0.0
    max_event_drain_duration_seconds: float = 0.0
    max_drained_events: int = 0
    slow_samples: int = 0
    max_loop_gap_seconds: float = 0.0
    max_blocking_span_name: str | None = None
    max_blocking_span_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class _VoipIterateMetrics:
    """Normalized keep-alive sub-span timings surfaced from the VoIP backend."""

    native_duration_seconds: float = 0.0
    event_drain_duration_seconds: float = 0.0


def _queue_depth(queue_obj: object) -> int | None:
    """Return a best-effort queue depth for runtime diagnostics."""

    qsize = getattr(queue_obj, "qsize", None)
    if not callable(qsize):
        return None

    try:
        return int(qsize())
    except (NotImplementedError, TypeError, ValueError):
        return None


class RuntimeLoopService:
    """Own the coordinator loop cadence and queued main-thread work."""

    _VOIP_TIMING_SUMMARY_INTERVAL_SECONDS = 10.0
    _MIN_RUNTIME_LOOP_GAP_WARNING_SECONDS = 0.2
    _MIN_RUNTIME_BLOCKING_SPAN_WARNING_SECONDS = 0.2
    _MIN_RUNTIME_ITERATION_WARNING_SECONDS = 0.2
    _MIN_VOIP_SCHEDULE_DELAY_WARNING_SECONDS = 0.15
    _MIN_VOIP_ITERATE_WARNING_SECONDS = 0.15

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app
        self._last_loop_iteration_started_at = 0.0
        self._last_runtime_loop_gap_seconds = 0.0
        self._last_runtime_iteration_duration_seconds = 0.0
        self._last_voip_iterate_started_at = 0.0
        self._last_voip_schedule_delay_seconds = 0.0
        self._last_voip_iterate_duration_seconds = 0.0
        self._last_voip_native_events = 0
        self._last_voip_native_iterate_duration_seconds = 0.0
        self._last_voip_event_drain_duration_seconds = 0.0
        self._last_runtime_blocking_span_name: str | None = None
        self._last_runtime_blocking_span_seconds = 0.0
        self._last_runtime_blocking_span_recorded_at = 0.0
        self._voip_timing_window = _VoipTimingWindow()

    def _record_blocking_span(self, span_name: str, duration_seconds: float) -> None:
        """Persist and log one named coordinator-thread blocking span."""

        self._last_runtime_blocking_span_name = span_name
        self._last_runtime_blocking_span_seconds = duration_seconds
        self._last_runtime_blocking_span_recorded_at = time.monotonic()
        if (
            self._voip_timing_window.started_at > 0.0
            and duration_seconds >= self._voip_timing_window.max_blocking_span_seconds
        ):
            self._voip_timing_window.max_blocking_span_name = span_name
            self._voip_timing_window.max_blocking_span_seconds = duration_seconds
        coord_logger.warning(
            "Coordinator blocking span: "
            "span={} duration_ms={:.1f} pending_callbacks={} pending_events={} screen={} state={}",
            span_name,
            duration_seconds * 1000.0,
            _queue_depth(self.app._pending_main_thread_callbacks),
            self.app.event_bus.pending_count(),
            self._current_screen_name(),
            self._runtime_state_name(),
        )

    def _measure_blocking_span(
        self,
        span_name: str,
        callback: Callable[[], _T],
    ) -> _T:
        """Run one coordinator step and surface unusually long blocking spans."""

        started_at = time.monotonic()
        try:
            return callback()
        finally:
            duration_seconds = max(0.0, time.monotonic() - started_at)
            if duration_seconds >= self._runtime_blocking_span_warning_seconds():
                self._record_blocking_span(span_name, duration_seconds)

    def _latest_voip_iterate_metrics(self) -> _VoipIterateMetrics | None:
        """Return the latest backend-native keep-alive sub-span timings when available."""

        if self.app.voip_manager is None:
            return None

        get_metrics = getattr(self.app.voip_manager, "get_iterate_metrics", None)
        if not callable(get_metrics):
            return None

        metrics = get_metrics()
        if metrics is None:
            return None

        return _VoipIterateMetrics(
            native_duration_seconds=max(
                0.0,
                float(getattr(metrics, "native_duration_seconds", 0.0) or 0.0),
            ),
            event_drain_duration_seconds=max(
                0.0,
                float(getattr(metrics, "event_drain_duration_seconds", 0.0) or 0.0),
            ),
        )

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

        scheduled_for = self.app._next_voip_iterate_at
        if monotonic_now < scheduled_for:
            return

        schedule_delay_seconds = max(0.0, monotonic_now - scheduled_for)
        since_last_iterate_seconds = (
            max(0.0, monotonic_now - self._last_voip_iterate_started_at)
            if self._last_voip_iterate_started_at > 0.0
            else 0.0
        )
        self._last_voip_iterate_started_at = monotonic_now
        self._last_voip_schedule_delay_seconds = schedule_delay_seconds

        started_at = time.monotonic()
        native_events = self.app.voip_manager.iterate()
        iterate_duration_seconds = time.monotonic() - started_at
        iterate_metrics = self._latest_voip_iterate_metrics()
        self._last_voip_iterate_duration_seconds = iterate_duration_seconds
        self._last_voip_native_events = native_events
        self._last_voip_native_iterate_duration_seconds = (
            iterate_metrics.native_duration_seconds if iterate_metrics is not None else 0.0
        )
        self._last_voip_event_drain_duration_seconds = (
            iterate_metrics.event_drain_duration_seconds if iterate_metrics is not None else 0.0
        )
        self.app._next_voip_iterate_at = monotonic_now + self.app._voip_iterate_interval_seconds

        delayed = schedule_delay_seconds >= self._voip_schedule_delay_warning_seconds()
        slow = iterate_duration_seconds >= self._voip_iterate_warning_seconds()
        self._record_voip_timing_sample(
            monotonic_now=monotonic_now,
            schedule_delay_seconds=schedule_delay_seconds,
            iterate_duration_seconds=iterate_duration_seconds,
            native_iterate_duration_seconds=self._last_voip_native_iterate_duration_seconds,
            event_drain_duration_seconds=self._last_voip_event_drain_duration_seconds,
            drained_events=native_events,
            delayed=delayed,
            slow=slow,
        )

        if delayed or slow:
            voip_logger.warning(
                "VoIP iterate timing drift: "
                "schedule_delay_ms={:.1f} iterate_ms={:.1f} since_last_ms={:.1f} "
                "interval_ms={:.1f} native_iterate_ms={:.1f} event_drain_ms={:.1f} "
                "native_events={} pending_callbacks={} pending_events={} screen={} state={}",
                schedule_delay_seconds * 1000.0,
                iterate_duration_seconds * 1000.0,
                since_last_iterate_seconds * 1000.0,
                self.app._voip_iterate_interval_seconds * 1000.0,
                self._last_voip_native_iterate_duration_seconds * 1000.0,
                self._last_voip_event_drain_duration_seconds * 1000.0,
                native_events,
                _queue_depth(self.app._pending_main_thread_callbacks),
                self.app.event_bus.pending_count(),
                self._current_screen_name(),
                self._runtime_state_name(),
            )

    def run_iteration(
        self,
        *,
        monotonic_now: float,
        current_time: float,
        last_screen_update: float,
        screen_update_interval: float,
    ) -> float:
        """Run one coordinator-loop iteration and return the next screen refresh timestamp."""
        iteration_started_at = time.monotonic()
        self._observe_loop_gap(monotonic_now=monotonic_now)
        self.app._last_loop_heartbeat_at = monotonic_now
        try:
            self._measure_blocking_span(
                "voip_keepalive",
                lambda: self.iterate_voip_backend_if_due(monotonic_now),
            )
            self._measure_blocking_span(
                "main_thread_actions",
                self.process_pending_main_thread_actions,
            )
            self._measure_blocking_span(
                "manager_recovery",
                lambda: self.app.recovery_service.attempt_manager_recovery(now=monotonic_now),
            )
            self._measure_blocking_span(
                "power_poll",
                lambda: self.app.recovery_service.poll_power_status(now=monotonic_now),
            )
            self._measure_blocking_span(
                "lvgl_pump",
                lambda: self.pump_lvgl_backend(monotonic_now),
            )
            self._measure_blocking_span(
                "watchdog_feed",
                lambda: self.app.recovery_service.feed_watchdog_if_due(monotonic_now),
            )
            self._measure_blocking_span(
                "pending_shutdown",
                lambda: self.app.shutdown_service.process_pending_shutdown(monotonic_now),
            )
            if self.app._shutdown_completed:
                return last_screen_update

            self._measure_blocking_span(
                "screen_power",
                lambda: self.app.screen_power_service.update_screen_power(monotonic_now),
            )
            overlay_active = self._measure_blocking_span(
                "power_overlay",
                lambda: self.app.screen_power_service.update_power_overlays(monotonic_now),
            )
            if overlay_active:
                return current_time

            if not self.app._screen_awake:
                return current_time

            if current_time - last_screen_update >= screen_update_interval:
                self.app.boot_service.ensure_coordinators()
                assert self.app.playback_coordinator is not None
                assert self.app.screen_coordinator is not None
                self._measure_blocking_span(
                    "visible_screen_refresh",
                    lambda: (
                        self.app.playback_coordinator.update_now_playing_if_needed(),
                        self.app.screen_coordinator.update_in_call_if_needed(),
                        self.app.screen_coordinator.update_power_screen_if_needed(),
                    ),
                )
                return current_time

            return last_screen_update
        finally:
            iteration_finished_at = time.monotonic()
            self._last_runtime_iteration_duration_seconds = (
                iteration_finished_at - iteration_started_at
            )
            self._maybe_log_voip_timing_summary(monotonic_now=iteration_finished_at)
            if (
                self._last_runtime_iteration_duration_seconds
                >= self._runtime_iteration_warning_seconds()
            ):
                coord_logger.warning(
                    "Runtime iteration slow: "
                    "iteration_ms={:.1f} pending_callbacks={} pending_events={} screen={} state={}",
                    self._last_runtime_iteration_duration_seconds * 1000.0,
                    _queue_depth(self.app._pending_main_thread_callbacks),
                    self.app.event_bus.pending_count(),
                    self._current_screen_name(),
                    self._runtime_state_name(),
                )

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

    def timing_snapshot(self, *, now: float | None = None) -> dict[str, float | int | None]:
        """Expose the latest loop timing markers for snapshots and diagnostics."""

        monotonic_now = time.monotonic() if now is None else now
        return {
            "runtime_loop_gap_seconds": (
                self._last_runtime_loop_gap_seconds
                if self._last_loop_iteration_started_at > 0.0
                else None
            ),
            "runtime_iteration_seconds": (
                self._last_runtime_iteration_duration_seconds
                if self._last_loop_iteration_started_at > 0.0
                else None
            ),
            "voip_schedule_delay_seconds": (
                self._last_voip_schedule_delay_seconds
                if self._last_voip_iterate_started_at > 0.0
                else None
            ),
            "voip_iterate_duration_seconds": (
                self._last_voip_iterate_duration_seconds
                if self._last_voip_iterate_started_at > 0.0
                else None
            ),
            "voip_native_iterate_duration_seconds": (
                self._last_voip_native_iterate_duration_seconds
                if self._last_voip_iterate_started_at > 0.0
                else None
            ),
            "voip_event_drain_duration_seconds": (
                self._last_voip_event_drain_duration_seconds
                if self._last_voip_iterate_started_at > 0.0
                else None
            ),
            "voip_iterate_native_events": (
                self._last_voip_native_events if self._last_voip_iterate_started_at > 0.0 else None
            ),
            "voip_iterate_age_seconds": (
                max(0.0, monotonic_now - self._last_voip_iterate_started_at)
                if self._last_voip_iterate_started_at > 0.0
                else None
            ),
            "voip_iterate_interval_seconds": self.app._voip_iterate_interval_seconds,
            "runtime_blocking_span_name": self._last_runtime_blocking_span_name,
            "runtime_blocking_span_seconds": (
                self._last_runtime_blocking_span_seconds
                if self._last_runtime_blocking_span_name is not None
                else None
            ),
            "runtime_blocking_span_age_seconds": (
                max(0.0, monotonic_now - self._last_runtime_blocking_span_recorded_at)
                if self._last_runtime_blocking_span_recorded_at > 0.0
                else None
            ),
            "voip_timing_window_samples": self._voip_timing_window.samples,
        }

    def _observe_loop_gap(self, *, monotonic_now: float) -> None:
        """Track coordinator-loop gaps so starvation shows up in logs and snapshots."""

        if self._last_loop_iteration_started_at <= 0.0:
            self._last_loop_iteration_started_at = monotonic_now
            self._last_runtime_loop_gap_seconds = 0.0
            return

        loop_gap_seconds = max(0.0, monotonic_now - self._last_loop_iteration_started_at)
        self._last_loop_iteration_started_at = monotonic_now
        self._last_runtime_loop_gap_seconds = loop_gap_seconds
        self._voip_timing_window.max_loop_gap_seconds = max(
            self._voip_timing_window.max_loop_gap_seconds,
            loop_gap_seconds,
        )

        if loop_gap_seconds < self._runtime_loop_gap_warning_seconds():
            return

        coord_logger.warning(
            "Runtime loop blocked: "
            "gap_ms={:.1f} interval_ms={:.1f} pending_callbacks={} pending_events={} screen={} state={}",
            loop_gap_seconds * 1000.0,
            self.app._voip_iterate_interval_seconds * 1000.0,
            _queue_depth(self.app._pending_main_thread_callbacks),
            self.app.event_bus.pending_count(),
            self._current_screen_name(),
            self._runtime_state_name(),
        )

    def _record_voip_timing_sample(
        self,
        *,
        monotonic_now: float,
        schedule_delay_seconds: float,
        iterate_duration_seconds: float,
        native_iterate_duration_seconds: float,
        event_drain_duration_seconds: float,
        drained_events: int,
        delayed: bool,
        slow: bool,
    ) -> None:
        """Accumulate one VoIP iterate sample for the next summary window."""

        if self._voip_timing_window.started_at <= 0.0:
            self._voip_timing_window.started_at = monotonic_now

        self._voip_timing_window.samples += 1
        self._voip_timing_window.total_schedule_delay_seconds += schedule_delay_seconds
        self._voip_timing_window.max_schedule_delay_seconds = max(
            self._voip_timing_window.max_schedule_delay_seconds,
            schedule_delay_seconds,
        )
        self._voip_timing_window.total_iterate_duration_seconds += iterate_duration_seconds
        self._voip_timing_window.max_iterate_duration_seconds = max(
            self._voip_timing_window.max_iterate_duration_seconds,
            iterate_duration_seconds,
        )
        self._voip_timing_window.max_native_iterate_duration_seconds = max(
            self._voip_timing_window.max_native_iterate_duration_seconds,
            native_iterate_duration_seconds,
        )
        self._voip_timing_window.max_event_drain_duration_seconds = max(
            self._voip_timing_window.max_event_drain_duration_seconds,
            event_drain_duration_seconds,
        )
        self._voip_timing_window.max_drained_events = max(
            self._voip_timing_window.max_drained_events,
            drained_events,
        )
        self._voip_timing_window.max_loop_gap_seconds = max(
            self._voip_timing_window.max_loop_gap_seconds,
            self._last_runtime_loop_gap_seconds,
        )
        if delayed:
            self._voip_timing_window.delayed_samples += 1
        if slow:
            self._voip_timing_window.slow_samples += 1

    def _maybe_log_voip_timing_summary(self, *, monotonic_now: float) -> None:
        """Emit a low-frequency summary of keep-alive timing behavior."""

        window = self._voip_timing_window
        if window.started_at <= 0.0 or window.samples <= 0:
            return

        if (
            self._VOIP_TIMING_SUMMARY_INTERVAL_SECONDS > 0.0
            and (monotonic_now - window.started_at) < self._VOIP_TIMING_SUMMARY_INTERVAL_SECONDS
        ):
            return

        average_schedule_delay_ms = (window.total_schedule_delay_seconds / window.samples) * 1000.0
        average_iterate_duration_ms = (
            window.total_iterate_duration_seconds / window.samples
        ) * 1000.0
        voip_logger.info(
            "VoIP timing window: "
            "samples={} avg_schedule_delay_ms={:.1f} max_schedule_delay_ms={:.1f} "
            "avg_iterate_ms={:.1f} max_iterate_ms={:.1f} max_loop_gap_ms={:.1f} "
            "delayed_samples={} slow_samples={} max_native_iterate_ms={:.1f} "
            "max_event_drain_ms={:.1f} max_native_events={} "
            "max_blocking_span={} max_blocking_span_ms={:.1f} "
            "interval_ms={:.1f} screen={} state={}",
            window.samples,
            average_schedule_delay_ms,
            window.max_schedule_delay_seconds * 1000.0,
            average_iterate_duration_ms,
            window.max_iterate_duration_seconds * 1000.0,
            window.max_loop_gap_seconds * 1000.0,
            window.delayed_samples,
            window.slow_samples,
            window.max_native_iterate_duration_seconds * 1000.0,
            window.max_event_drain_duration_seconds * 1000.0,
            window.max_drained_events,
            window.max_blocking_span_name or "none",
            window.max_blocking_span_seconds * 1000.0,
            self.app._voip_iterate_interval_seconds * 1000.0,
            self._current_screen_name(),
            self._runtime_state_name(),
        )
        self._voip_timing_window = _VoipTimingWindow(started_at=monotonic_now)

    def _runtime_loop_gap_warning_seconds(self) -> float:
        """Return the loop-gap threshold that is worth surfacing on hardware."""

        return max(
            self._MIN_RUNTIME_LOOP_GAP_WARNING_SECONDS,
            self.app._voip_iterate_interval_seconds * 6.0,
        )

    def _runtime_iteration_warning_seconds(self) -> float:
        """Return the total iteration duration threshold for broad blocking work."""

        return max(
            self._MIN_RUNTIME_ITERATION_WARNING_SECONDS,
            self.app._voip_iterate_interval_seconds * 6.0,
        )

    def _runtime_blocking_span_warning_seconds(self) -> float:
        """Return the per-step blocking threshold for coordinator runtime spans."""

        return max(
            self._MIN_RUNTIME_BLOCKING_SPAN_WARNING_SECONDS,
            self.app._voip_iterate_interval_seconds * 6.0,
        )

    def _voip_schedule_delay_warning_seconds(self) -> float:
        """Return the schedule-drift threshold for VoIP iterate warnings."""

        return max(
            self._MIN_VOIP_SCHEDULE_DELAY_WARNING_SECONDS,
            self.app._voip_iterate_interval_seconds * 4.0,
        )

    def _voip_iterate_warning_seconds(self) -> float:
        """Return the per-iterate duration threshold for VoIP keep-alive warnings."""

        return max(
            self._MIN_VOIP_ITERATE_WARNING_SECONDS,
            self.app._voip_iterate_interval_seconds * 4.0,
        )

    def _current_screen_name(self) -> str:
        """Return the active route name for diagnostic log context."""

        if self.app.screen_manager is None:
            return "none"

        current_screen = self.app.screen_manager.get_current_screen()
        return str(getattr(current_screen, "route_name", None) or "none")

    def _runtime_state_name(self) -> str:
        """Return the current derived app state for diagnostic log context."""

        if self.app.coordinator_runtime is not None:
            return str(self.app.coordinator_runtime.get_state_name())

        return str(getattr(self.app._ui_state, "value", self.app._ui_state))
