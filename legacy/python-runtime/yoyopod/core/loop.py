"""Coordinator-thread loop scheduling and main-thread queue draining."""

from __future__ import annotations

import time
from dataclasses import dataclass
from queue import Empty, Queue
from typing import TYPE_CHECKING, Any, Callable, Optional, TypeVar

from loguru import logger
from yoyopod.core._loop_support import (
    _LoopCadenceDecision,
    _VoipIterateMetrics,
    _VoipTimingWindow,
    _apply_loop_cadence as _apply_loop_cadence_impl,
    _effective_voip_iterate_interval_seconds as _effective_voip_iterate_interval_seconds_impl,
    _latest_voip_iterate_metrics as _latest_voip_iterate_metrics_impl,
    _maybe_log_voip_timing_summary as _maybe_log_voip_timing_summary_impl,
    _measure_blocking_span as _measure_blocking_span_impl,
    _next_voip_due_at_for_cadence as _next_voip_due_at_for_cadence_impl,
    _record_blocking_span as _record_blocking_span_impl,
    _record_voip_timing_sample as _record_voip_timing_sample_impl,
    _runtime_blocking_span_warning_seconds as _runtime_blocking_span_warning_seconds_impl,
    _runtime_iteration_warning_seconds as _runtime_iteration_warning_seconds_impl,
    _runtime_loop_gap_warning_seconds as _runtime_loop_gap_warning_seconds_impl,
    _select_loop_cadence as _select_loop_cadence_impl,
    _sync_background_voip_timing_sample as _sync_background_voip_timing_sample_impl,
    _voip_iterate_warning_seconds as _voip_iterate_warning_seconds_impl,
    _voip_schedule_delay_warning_seconds as _voip_schedule_delay_warning_seconds_impl,
    _warn_if_slow as _warn_if_slow_impl,
)

from yoyopod.core.logging import get_subsystem_logger

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp


coord_logger = get_subsystem_logger("coord")
voip_logger = get_subsystem_logger("voip")
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class _MainThreadDrainResult:
    """Snapshot one coordinator-thread queue drain so backlog pressure is visible."""

    safety_callbacks_processed: int = 0
    scheduled_tasks_processed: int = 0
    events_processed: int = 0
    scheduled_tasks_deferred: int = 0
    events_deferred: int = 0
    scheduler_budget: int | None = None
    bus_budget: int | None = None

    @property
    def total_processed(self) -> int:
        """Return the total amount of queued main-thread work advanced in one drain."""

        return (
            self.safety_callbacks_processed + self.scheduled_tasks_processed + self.events_processed
        )

    @property
    def scheduler_budget_hit(self) -> bool:
        """Return whether queued scheduler tasks were deferred by the per-iteration budget."""

        return self.scheduler_budget is not None and self.scheduled_tasks_deferred > 0

    @property
    def bus_budget_hit(self) -> bool:
        """Return whether queued typed events were deferred by the per-iteration budget."""

        return self.bus_budget is not None and self.events_deferred > 0


def _queue_depth(queue_obj: object) -> int | None:
    """Return a best-effort queue depth for runtime diagnostics."""

    qsize = getattr(queue_obj, "qsize", None)
    if not callable(qsize):
        return None

    try:
        return int(qsize())
    except (NotImplementedError, TypeError, ValueError):
        return None


def _callable_name(fn: Callable[[], None]) -> str:
    """Return a stable callable name for diagnostics entries."""

    module = getattr(fn, "__module__", "") or ""
    qualname = getattr(fn, "__qualname__", getattr(fn, "__name__", repr(fn)))
    return f"{module}.{qualname}".strip(".")


class RuntimeLoopService:
    """Own the coordinator loop cadence and queued main-thread work."""

    _SLOW_MAIN_THREAD_DRAIN_WARNING_SECONDS = 0.1
    _SLOW_LVGL_PUMP_WARNING_SECONDS = 0.25
    _SLOW_VOIP_ITERATE_WARNING_SECONDS = 0.25
    _VOIP_TIMING_SUMMARY_INTERVAL_SECONDS = 10.0
    _MIN_RUNTIME_LOOP_GAP_WARNING_SECONDS = 0.2
    _MIN_RUNTIME_BLOCKING_SPAN_WARNING_SECONDS = 0.2
    _MIN_RUNTIME_ITERATION_WARNING_SECONDS = 0.2
    _MIN_VOIP_SCHEDULE_DELAY_WARNING_SECONDS = 0.15
    _MIN_VOIP_ITERATE_WARNING_SECONDS = 0.15
    _RECENT_INPUT_WINDOW_SECONDS = 0.4
    _PENDING_WORK_LOOP_INTERVAL_SECONDS = 0.01
    _RELAXED_IDLE_INTERVAL_SECONDS = 0.05
    _SCREEN_SLEEP_IDLE_INTERVAL_SECONDS = 0.1
    _SCHEDULER_DRAIN_BUDGET = 4
    _BUS_DRAIN_BUDGET = 8
    _DRAIN_BUDGET_LOG_INTERVAL_SECONDS = 1.0
    _LATENCY_SENSITIVE_STATES = frozenset(
        {
            "call_incoming",
            "call_outgoing",
            "call_active",
            "call_active_music_paused",
            "paused_by_call",
            "connecting",
        }
    )

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app
        self._safety_callbacks: Queue[Callable[[], None]] = Queue()
        self._last_loop_iteration_started_at = 0.0
        self._last_runtime_loop_gap_seconds = 0.0
        self._last_runtime_iteration_duration_seconds = 0.0
        self._last_main_thread_drain_duration_seconds = 0.0
        self._main_thread_drain_recorded = False
        self._last_voip_iterate_started_at = 0.0
        self._last_voip_timing_sample_id = 0
        self._last_voip_schedule_delay_seconds = 0.0
        self._last_voip_iterate_duration_seconds = 0.0
        self._last_voip_native_events = 0
        self._last_voip_native_iterate_duration_seconds = 0.0
        self._last_voip_event_drain_duration_seconds = 0.0
        self._last_runtime_blocking_span_name: str | None = None
        self._last_runtime_blocking_span_seconds = 0.0
        self._last_runtime_blocking_span_recorded_at = 0.0
        self._last_scheduler_tasks_drained = 0
        self._last_bus_events_drained = 0
        self._last_scheduler_tasks_deferred = 0
        self._last_bus_events_deferred = 0
        self._last_scheduler_budget_hit = False
        self._last_bus_event_budget_hit = False
        self._last_scheduler_drain_budget: int | None = None
        self._last_bus_drain_budget: int | None = None
        self._last_drain_budget_log_at = 0.0
        self._voip_timing_window = _VoipTimingWindow()
        self._current_cadence_mode = "startup"
        self._current_cadence_reason = "startup"
        self._current_loop_sleep_seconds = min(
            self._RELAXED_IDLE_INTERVAL_SECONDS,
            max(0.01, float(self.app._voip_iterate_interval_seconds)),
        )
        self._current_voip_iterate_interval_seconds = max(
            0.01,
            float(self.app._voip_iterate_interval_seconds),
        )
        self._last_cadence_selected_at = 0.0
        self._last_requested_sleep_seconds = self._current_loop_sleep_seconds
        self._last_requested_sleep_recorded_at = 0.0

    def _record_blocking_span(self, span_name: str, duration_seconds: float) -> None:
        """Persist and log one named coordinator-thread blocking span."""

        _record_blocking_span_impl(self, span_name=span_name, duration_seconds=duration_seconds)

    def _measure_blocking_span(
        self,
        span_name: str,
        callback: Callable[[], _T],
    ) -> _T:
        """Run one coordinator step and surface unusually long blocking spans."""

        return _measure_blocking_span_impl(self, span_name, callback)

    def _latest_voip_iterate_metrics(self) -> _VoipIterateMetrics | None:
        """Return the latest backend-native keep-alive sub-span timings when available."""

        return _latest_voip_iterate_metrics_impl(self)

    def _voip_background_iterate_enabled(self) -> bool:
        """Return False because Rust owns VoIP runtime iteration internally."""

        return False

    @property
    def configured_voip_iterate_interval_seconds(self) -> float:
        """Return the configured VoIP iterate cadence before runtime adaptation."""

        return float(self.app._voip_iterate_interval_seconds)

    def _sync_background_voip_timing_sample(self) -> None:
        """Pull the latest background iterate sample into runtime timing snapshots."""

        _sync_background_voip_timing_sample_impl(self)

    def process_pending_main_thread_actions(self, limit: Optional[int] = None) -> int:
        """Drain queued scheduler tasks and typed events."""
        started_at = time.monotonic()
        safety_callbacks_processed = self._drain_safety_callbacks()
        scheduled_tasks_processed = self._drain_scheduler_tasks(limit)
        remaining_limit = None if limit is None else max(0, limit - scheduled_tasks_processed)
        events_processed = self.app.bus.drain(remaining_limit)
        result = self._snapshot_main_thread_drain_result(
            safety_callbacks_processed=safety_callbacks_processed,
            scheduled_tasks_processed=scheduled_tasks_processed,
            events_processed=events_processed,
        )
        self._record_main_thread_drain_result(result)
        self._warn_if_slow(
            "main-thread drain",
            started_at=started_at,
            threshold_seconds=self._SLOW_MAIN_THREAD_DRAIN_WARNING_SECONDS,
            detail=self._main_thread_drain_detail(result),
        )
        self._last_main_thread_drain_duration_seconds = max(
            0.0,
            time.monotonic() - started_at,
        )
        self._main_thread_drain_recorded = True
        return result.total_processed

    def _process_pending_main_thread_actions_for_iteration(self) -> int:
        """Advance protected callbacks first, then generic queue work under fairness budgets."""

        started_at = time.monotonic()
        safety_callbacks_processed = self._drain_safety_callbacks()
        scheduler_budget = self._scheduler_drain_budget()
        bus_budget = self._bus_drain_budget()
        scheduled_tasks_processed = self._drain_scheduler_tasks(scheduler_budget)
        result = self._snapshot_main_thread_drain_result(
            safety_callbacks_processed=safety_callbacks_processed,
            scheduled_tasks_processed=scheduled_tasks_processed,
            events_processed=self.app.bus.drain(bus_budget),
            scheduler_budget=scheduler_budget,
            bus_budget=bus_budget,
        )
        self._record_main_thread_drain_result(result)
        self._maybe_log_main_thread_drain_budget_hit(result)
        self._warn_if_slow(
            "main-thread drain",
            started_at=started_at,
            threshold_seconds=self._SLOW_MAIN_THREAD_DRAIN_WARNING_SECONDS,
            detail=self._main_thread_drain_detail(result),
        )
        self._last_main_thread_drain_duration_seconds = max(
            0.0,
            time.monotonic() - started_at,
        )
        self._main_thread_drain_recorded = True
        return result.total_processed

    def _scheduler_drain_budget(self) -> int:
        """Return the maximum scheduler task count the coordinator should drain per iteration."""

        return max(1, int(self._SCHEDULER_DRAIN_BUDGET))

    def _bus_drain_budget(self) -> int:
        """Return the maximum typed event count the coordinator should drain per iteration."""

        return max(1, int(self._BUS_DRAIN_BUDGET))

    def _pending_work_loop_sleep_seconds(self) -> float:
        """Return the coordinator sleep used while generic queue work is backlogged."""

        # Pending-work cadence intentionally stays fixed at 10 ms so backlog yields
        # between iterations instead of tracking the faster VoIP cadence.
        return self._PENDING_WORK_LOOP_INTERVAL_SECONDS

    def _drain_scheduler_tasks(
        self,
        limit: int | None = None,
    ) -> int:
        """Run queued scheduler tasks with an optional hard count limit."""

        return self.app.scheduler.drain(limit)

    def _drain_safety_callbacks(self, limit: int | None = None) -> int:
        """Run protected main-thread callbacks ahead of the generic scheduler backlog."""

        processed = 0
        while limit is None or processed < limit:
            try:
                callback = self._safety_callbacks.get_nowait()
            except Empty:
                break
            self._run_queued_callback(callback, lane_name="safety")
            processed += 1
        return processed

    def _run_queued_callback(
        self,
        callback: Callable[[], None],
        *,
        lane_name: str,
    ) -> None:
        """Run one queued callback and mirror scheduler diagnostics on failure."""

        try:
            callback()
        except Exception as exc:
            self.app.log_buffer.append(
                {
                    "kind": "error",
                    "handler": _callable_name(callback),
                    "exc": f"{exc.__class__.__name__}: {exc}",
                }
            )
            coord_logger.exception(
                "Error running queued main-thread callback on {} lane",
                lane_name,
            )

    def pending_main_thread_callback_count(self) -> int:
        """Return the combined generic and protected main-thread callback backlog."""

        generic_backlog = self.app.scheduler.pending_count()
        safety_backlog = _queue_depth(self._safety_callbacks)
        return max(0, generic_backlog) + max(0, safety_backlog or 0)

    def _snapshot_main_thread_drain_result(
        self,
        *,
        safety_callbacks_processed: int = 0,
        scheduled_tasks_processed: int,
        events_processed: int,
        scheduler_budget: int | None = None,
        bus_budget: int | None = None,
    ) -> _MainThreadDrainResult:
        """Capture drain totals and remaining backlog after one coordinator drain."""

        scheduler_backlog = self.app.scheduler.pending_count()
        # Deferred scheduler count is best-effort: queues without qsize support degrade
        # to 0 here rather than paying extra coordinator work to derive a stronger estimate.
        return _MainThreadDrainResult(
            safety_callbacks_processed=safety_callbacks_processed,
            scheduled_tasks_processed=scheduled_tasks_processed,
            events_processed=events_processed,
            scheduled_tasks_deferred=(
                max(0, scheduler_backlog) if scheduler_backlog is not None else 0
            ),
            events_deferred=max(0, self.app.bus.pending_count()),
            scheduler_budget=scheduler_budget,
            bus_budget=bus_budget,
        )

    def _record_main_thread_drain_result(self, result: _MainThreadDrainResult) -> None:
        """Persist the latest queue-drain snapshot for diagnostics and status output."""

        self._last_scheduler_tasks_drained = result.scheduled_tasks_processed
        self._last_bus_events_drained = result.events_processed
        self._last_scheduler_tasks_deferred = result.scheduled_tasks_deferred
        self._last_bus_events_deferred = result.events_deferred
        self._last_scheduler_budget_hit = result.scheduler_budget_hit
        self._last_bus_event_budget_hit = result.bus_budget_hit
        self._last_scheduler_drain_budget = result.scheduler_budget
        self._last_bus_drain_budget = result.bus_budget

    def _main_thread_drain_detail(self, result: _MainThreadDrainResult) -> str:
        """Format one queue-drain snapshot for warnings and debug logs."""

        scheduler_budget = (
            "all" if result.scheduler_budget is None else str(result.scheduler_budget)
        )
        bus_budget = "all" if result.bus_budget is None else str(result.bus_budget)
        return (
            f"safety_callbacks={result.safety_callbacks_processed} "
            f"scheduler_tasks={result.scheduled_tasks_processed}/{scheduler_budget} "
            f"events={result.events_processed}/{bus_budget} "
            f"deferred_scheduler_tasks={result.scheduled_tasks_deferred} "
            f"deferred_events={result.events_deferred}"
        )

    def _maybe_log_main_thread_drain_budget_hit(self, result: _MainThreadDrainResult) -> None:
        """Surface queue-budget pressure without logging on every hot-loop iteration."""

        if not (result.scheduler_budget_hit or result.bus_budget_hit):
            return

        now = time.monotonic()
        # One shared throttle window keeps this a coarse health signal instead of a
        # per-queue alert stream while the coordinator is already under pressure.
        if (
            self._last_drain_budget_log_at > 0.0
            and (now - self._last_drain_budget_log_at) < self._DRAIN_BUDGET_LOG_INTERVAL_SECONDS
        ):
            return

        self._last_drain_budget_log_at = now
        coord_logger.warning(
            "Main-thread drain budget hit: "
            "scheduler_tasks_drained={} scheduler_budget={} scheduler_tasks_deferred={} "
            "events_drained={} bus_budget={} events_deferred={} "
            "cadence_mode={} cadence_reason={} screen={} state={}",
            result.scheduled_tasks_processed,
            result.scheduler_budget,
            result.scheduled_tasks_deferred,
            result.events_processed,
            result.bus_budget,
            result.events_deferred,
            self._current_cadence_mode,
            self._current_cadence_reason,
            self._current_screen_name(),
            self._runtime_state_name(),
        )

    def queue_main_thread_callback(
        self,
        callback: Callable[[], None],
        *,
        safety: bool = False,
    ) -> None:
        """Schedule a callback to run on the coordinator thread."""
        if safety:
            self._safety_callbacks.put(callback)
            return
        self.app.scheduler.post(callback)

    def queue_lvgl_input_action(self, action: Any, _data: Optional[Any] = None) -> None:
        """Queue semantic actions for LVGL from input polling threads."""
        if self.app._lvgl_input_bridge is None:
            return
        self.app._lvgl_input_bridge.enqueue_action(action)

    def tick_rust_ui_host(self) -> None:
        rust_ui_host = getattr(self.app, "rust_ui_host", None)
        if rust_ui_host is None:
            return
        send_snapshot = getattr(rust_ui_host, "send_snapshot", None)
        send_tick = getattr(rust_ui_host, "send_tick", None)
        if callable(send_snapshot):
            send_snapshot()
        if callable(send_tick):
            send_tick(renderer="auto")

    def pump_lvgl_backend(self, now: float | None = None) -> None:
        """Pump LVGL timers and queued input on the coordinator thread."""
        if self.app._lvgl_backend is None or not self.app._lvgl_backend.initialized:
            return

        started_at = time.monotonic()
        monotonic_now = time.monotonic() if now is None else now
        if self.app._last_lvgl_pump_at <= 0.0:
            delta_ms = 0
        else:
            delta_ms = int(max(0.0, monotonic_now - self.app._last_lvgl_pump_at) * 1000.0)
        self.app._last_lvgl_pump_at = monotonic_now

        screen_manager = self.app.screen_manager
        flush_pending_navigation_refresh = (
            getattr(screen_manager, "flush_pending_navigation_refresh", None)
            if screen_manager is not None
            else None
        )
        if callable(flush_pending_navigation_refresh):
            flush_pending_navigation_refresh()

        if self.app._lvgl_input_bridge is not None:
            self.app._lvgl_input_bridge.process_pending()
        overlay_runtime = getattr(self.app, "cross_screen_overlays", None)
        if overlay_runtime is not None:
            overlay_runtime.render_active(monotonic_now)
        self.app._lvgl_backend.pump(delta_ms)
        self._warn_if_slow(
            "lvgl pump",
            started_at=started_at,
            threshold_seconds=self._SLOW_LVGL_PUMP_WARNING_SECONDS,
            detail_factory=lambda: f"delta_ms={delta_ms}",
        )

    def iterate_voip_backend_if_due(self, now: float | None = None) -> None:
        """Run Python-side VoIP housekeeping without owning liblinphone iteration."""
        if self.app.voip_manager is None or not self.app.voip_manager.running:
            return

        poll_housekeeping = getattr(self.app.voip_manager, "poll_housekeeping", None)
        if callable(poll_housekeeping):
            poll_housekeeping()
        self.app._next_voip_iterate_at = 0.0

    def next_sleep_interval_seconds(
        self,
        *,
        monotonic_now: float,
        current_time: float,
        last_screen_update: float,
        screen_update_interval: float,
    ) -> float:
        """Return the coordinator sleep for the next iteration."""

        cadence = self._select_loop_cadence(monotonic_now=monotonic_now)
        self._apply_loop_cadence(cadence, monotonic_now=monotonic_now)

        sleep_seconds = max(0.0, cadence.loop_sleep_seconds)
        deadlines = [sleep_seconds]

        if self.app._pending_shutdown is not None:
            deadlines.append(max(0.0, self.app._pending_shutdown.execute_at - monotonic_now))
        if self.app._next_power_poll_at > 0.0:
            deadlines.append(max(0.0, self.app._next_power_poll_at - monotonic_now))
        if (
            self.app._watchdog_active
            and not self.app._watchdog_feed_suppressed
            and self.app._next_watchdog_feed_at > 0.0
        ):
            deadlines.append(max(0.0, self.app._next_watchdog_feed_at - monotonic_now))
        if self.app._screen_awake and screen_update_interval > 0.0:
            deadlines.append(
                max(
                    0.0,
                    screen_update_interval - max(0.0, current_time - last_screen_update),
                )
            )

        requested_sleep_seconds = min(deadlines) if deadlines else sleep_seconds
        self._last_requested_sleep_seconds = requested_sleep_seconds
        self._last_requested_sleep_recorded_at = monotonic_now
        return requested_sleep_seconds

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
                self._process_pending_main_thread_actions_for_iteration,
            )
            self._measure_blocking_span(
                "worker_poll",
                self.app.worker_supervisor.poll,
            )
            self._measure_blocking_span(
                "rust_ui_host",
                self.tick_rust_ui_host,
            )
            self._measure_blocking_span(
                "manager_recovery",
                lambda: self.app.recovery_service.attempt_manager_recovery(now=monotonic_now),
            )
            self._measure_blocking_span(
                "power_poll",
                lambda: self.app.power_runtime.poll_status(now=monotonic_now),
            )
            cloud_manager = self.app.cloud_manager
            if cloud_manager is not None:
                self._measure_blocking_span(
                    "cloud_tick",
                    lambda: cloud_manager.tick(monotonic_now),
                )
            self._measure_blocking_span(
                "watchdog_feed",
                lambda: self.app.power_runtime.feed_watchdog_if_due(monotonic_now),
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
            overlay_active = False
            overlay_runtime = getattr(self.app, "cross_screen_overlays", None)
            if overlay_runtime is not None:
                overlay_active = self._measure_blocking_span(
                    "cross_screen_overlay_state",
                    lambda: overlay_runtime.evaluate(monotonic_now),
                )

            self._measure_blocking_span(
                "lvgl_pump",
                lambda: self.pump_lvgl_backend(monotonic_now),
            )

            if self.app._shutdown_completed:
                return last_screen_update

            if overlay_active:
                return current_time

            if not self.app._screen_awake:
                return current_time

            if current_time - last_screen_update >= screen_update_interval:
                screen_manager = self.app.screen_manager
                if screen_manager is None:
                    return current_time

                refreshed_visible_screen = self._measure_blocking_span(
                    "visible_screen_refresh",
                    screen_manager.refresh_current_screen_for_visible_tick,
                )
                if refreshed_visible_screen:
                    self.app.note_visible_refresh(refreshed_at=time.monotonic())
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
                    "iteration_ms={:.1f} pending_scheduler_tasks={} pending_events={} screen={} state={}",
                    self._last_runtime_iteration_duration_seconds * 1000.0,
                    self.pending_main_thread_callback_count(),
                    self.app.bus.pending_count(),
                    self._current_screen_name(),
                    self._runtime_state_name(),
                )

    def log_startup_status(self) -> None:
        """Emit the current runtime snapshot before entering the main loop."""
        assert self.app.app_state_runtime is not None
        logger.info("=" * 60)
        logger.info("YoYoPod Running")
        logger.info("=" * 60)
        logger.info("")
        logger.info("Coordinator Status:")
        logger.info(f"  Current state: {self.app.app_state_runtime.get_state_name()}")
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
            self.app.power_runtime.start_watchdog(now=time.monotonic())

            if self.app.simulate:
                logger.info("")
                logger.info("Simulation mode: Application running...")
                logger.info("  (Incoming calls and track changes will trigger callbacks)")
                logger.info("")

            while not self.app._stopping:
                monotonic_now = time.monotonic()
                current_time = time.time()
                time.sleep(
                    self.next_sleep_interval_seconds(
                        monotonic_now=monotonic_now,
                        current_time=current_time,
                        last_screen_update=last_screen_update,
                        screen_update_interval=screen_update_interval,
                    )
                )
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

    def timing_snapshot(
        self,
        *,
        now: float | None = None,
    ) -> dict[str, float | int | str | bool | None]:
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
            "runtime_main_thread_drain_seconds": (
                self._last_main_thread_drain_duration_seconds
                if self._last_loop_iteration_started_at > 0.0 or self._main_thread_drain_recorded
                else None
            ),
            "runtime_worker_count": len(self.app.worker_supervisor.snapshot()),
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
            "runtime_cadence_mode": self._current_cadence_mode,
            "runtime_cadence_reason": self._current_cadence_reason,
            "runtime_target_sleep_seconds": self._current_loop_sleep_seconds,
            "runtime_requested_sleep_seconds": self._last_requested_sleep_seconds,
            "runtime_cadence_age_seconds": (
                max(0.0, monotonic_now - self._last_cadence_selected_at)
                if self._last_cadence_selected_at > 0.0
                else None
            ),
            "runtime_requested_sleep_age_seconds": (
                max(0.0, monotonic_now - self._last_requested_sleep_recorded_at)
                if self._last_requested_sleep_recorded_at > 0.0
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
            "voip_effective_iterate_interval_seconds": (
                self._current_voip_iterate_interval_seconds
            ),
            "runtime_scheduler_tasks_drained": self._last_scheduler_tasks_drained,
            "runtime_bus_events_drained": self._last_bus_events_drained,
            "runtime_scheduler_tasks_deferred": self._last_scheduler_tasks_deferred,
            "runtime_bus_events_deferred": self._last_bus_events_deferred,
            "runtime_scheduler_drain_budget": (self._last_scheduler_drain_budget),
            "runtime_bus_drain_budget": self._last_bus_drain_budget,
            "runtime_scheduler_budget_hit": (self._last_scheduler_budget_hit),
            "runtime_bus_event_budget_hit": self._last_bus_event_budget_hit,
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

    def _select_loop_cadence(self, *, monotonic_now: float) -> _LoopCadenceDecision:
        """Choose the next runtime cadence from current state and queued work."""

        return _select_loop_cadence_impl(self, monotonic_now=monotonic_now)

    def _apply_loop_cadence(
        self,
        decision: _LoopCadenceDecision,
        *,
        monotonic_now: float,
    ) -> None:
        """Store one cadence decision and accelerate due work when responsiveness tightens."""

        _apply_loop_cadence_impl(self, decision, monotonic_now=monotonic_now)

    def _effective_voip_iterate_interval_seconds(self) -> float:
        """Return the currently selected VoIP iterate cadence."""

        return _effective_voip_iterate_interval_seconds_impl(self)

    def _next_voip_due_at_for_cadence(
        self,
        *,
        monotonic_now: float,
        iterate_interval_seconds: float,
    ) -> float:
        """Return the next VoIP iterate deadline aligned to the current cadence."""

        return _next_voip_due_at_for_cadence_impl(
            self,
            monotonic_now=monotonic_now,
            iterate_interval_seconds=iterate_interval_seconds,
        )

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
            "gap_ms={:.1f} interval_ms={:.1f} cadence_mode={} cadence_reason={} "
            "pending_scheduler_tasks={} pending_events={} screen={} state={}",
            loop_gap_seconds * 1000.0,
            self._effective_voip_iterate_interval_seconds() * 1000.0,
            self._current_cadence_mode,
            self._current_cadence_reason,
            self.pending_main_thread_callback_count(),
            self.app.bus.pending_count(),
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

        _record_voip_timing_sample_impl(
            self,
            monotonic_now=monotonic_now,
            schedule_delay_seconds=schedule_delay_seconds,
            iterate_duration_seconds=iterate_duration_seconds,
            native_iterate_duration_seconds=native_iterate_duration_seconds,
            event_drain_duration_seconds=event_drain_duration_seconds,
            drained_events=drained_events,
            delayed=delayed,
            slow=slow,
        )

    def _maybe_log_voip_timing_summary(self, *, monotonic_now: float) -> None:
        """Emit a low-frequency summary of keep-alive timing behavior."""

        _maybe_log_voip_timing_summary_impl(self, monotonic_now=monotonic_now)

    def _runtime_loop_gap_warning_seconds(self) -> float:
        """Return the loop-gap threshold that is worth surfacing on hardware."""

        return _runtime_loop_gap_warning_seconds_impl(self)

    def _runtime_iteration_warning_seconds(self) -> float:
        """Return the total iteration duration threshold for broad blocking work."""

        return _runtime_iteration_warning_seconds_impl(self)

    def _runtime_blocking_span_warning_seconds(self) -> float:
        """Return the per-step blocking threshold for coordinator runtime spans."""

        return _runtime_blocking_span_warning_seconds_impl(self)

    def _voip_schedule_delay_warning_seconds(self) -> float:
        """Return the schedule-drift threshold for VoIP iterate warnings."""

        return _voip_schedule_delay_warning_seconds_impl(self)

    def _voip_iterate_warning_seconds(self) -> float:
        """Return the per-iterate duration threshold for VoIP keep-alive warnings."""

        return _voip_iterate_warning_seconds_impl(self)

    def _current_screen_name(self) -> str:
        """Return the active route name for diagnostic log context."""

        if self.app.screen_manager is None:
            return "none"

        current_screen = self.app.screen_manager.get_current_screen()
        return str(getattr(current_screen, "route_name", None) or "none")

    def _runtime_state_name(self) -> str:
        """Return the current derived app state for diagnostic log context."""

        if self.app.app_state_runtime is not None:
            return str(self.app.app_state_runtime.get_state_name())

        screen_manager = self.app.screen_manager
        current_screen = screen_manager.get_current_screen() if screen_manager is not None else None
        current_route_name = getattr(current_screen, "route_name", None)
        from yoyopod.core.app_state import AppRuntimeState

        derived_state = AppRuntimeState.ui_state_for_screen_name(current_route_name)
        if derived_state is not None:
            return str(derived_state.value)
        return "idle"

    def _warn_if_slow(
        self,
        phase: str,
        *,
        started_at: float,
        threshold_seconds: float,
        detail: str = "",
        detail_factory: Callable[[], str] | None = None,
    ) -> None:
        """Emit a targeted warning when one coordinator-loop phase runs unusually long."""

        _warn_if_slow_impl(
            self,
            phase,
            started_at=started_at,
            threshold_seconds=threshold_seconds,
            detail=detail,
            detail_factory=detail_factory,
        )
