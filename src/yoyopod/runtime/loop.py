"""Runtime loop scheduling and coordinator-thread queues."""

from __future__ import annotations

import time
from dataclasses import dataclass
from queue import Empty
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


@dataclass(frozen=True, slots=True)
class _LoopCadenceDecision:
    """Normalized runtime cadence decision for the next coordinator wake."""

    mode: str
    reason: str
    loop_sleep_seconds: float
    voip_iterate_interval_seconds: float


@dataclass(frozen=True, slots=True)
class _MainThreadDrainResult:
    """Snapshot one coordinator-thread queue drain so backlog pressure is visible."""

    callbacks_processed: int = 0
    events_processed: int = 0
    callbacks_deferred: int = 0
    events_deferred: int = 0
    callback_budget: int | None = None
    event_budget: int | None = None

    @property
    def total_processed(self) -> int:
        """Return the total amount of generic queue work advanced in one drain."""

        return self.callbacks_processed + self.events_processed

    @property
    def callback_budget_hit(self) -> bool:
        """Return whether queued callbacks were deferred by the per-iteration budget."""

        return self.callback_budget is not None and self.callbacks_deferred > 0

    @property
    def event_budget_hit(self) -> bool:
        """Return whether queued typed events were deferred by the per-iteration budget."""

        return self.event_budget is not None and self.events_deferred > 0


@dataclass(frozen=True, slots=True)
class _CallbackDrainResult:
    """Track ordinary and safety callback drain counts for one coordinator step."""

    regular_callbacks_processed: int = 0
    safety_callbacks_processed: int = 0

    @property
    def total_processed(self) -> int:
        """Return the total number of callbacks advanced in one drain."""

        return self.regular_callbacks_processed + self.safety_callbacks_processed


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
    _MAIN_THREAD_CALLBACK_DRAIN_BUDGET = 4
    _EVENT_BUS_DRAIN_BUDGET = 8
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
        self._last_loop_iteration_started_at = 0.0
        self._last_runtime_loop_gap_seconds = 0.0
        self._last_runtime_iteration_duration_seconds = 0.0
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
        self._last_main_thread_callbacks_drained = 0
        self._last_event_bus_events_drained = 0
        self._last_main_thread_callbacks_deferred = 0
        self._last_event_bus_events_deferred = 0
        self._last_main_thread_callback_budget_hit = False
        self._last_event_bus_event_budget_hit = False
        self._last_main_thread_callback_drain_budget: int | None = None
        self._last_event_bus_drain_budget: int | None = None
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
            self.app._pending_main_thread_callback_count(),
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

    def _voip_background_iterate_enabled(self) -> bool:
        """Return whether the active VoIP manager owns a dedicated iterate worker."""

        return bool(
            self.app.voip_manager is not None
            and getattr(self.app.voip_manager, "background_iterate_enabled", False)
        )

    def _sync_background_voip_timing_sample(self) -> None:
        """Pull the latest background iterate sample into runtime timing snapshots."""

        if self.app.voip_manager is None:
            return

        get_snapshot = getattr(self.app.voip_manager, "get_iterate_timing_snapshot", None)
        if not callable(get_snapshot):
            return

        snapshot = get_snapshot()
        if snapshot is None:
            return

        last_started_at = max(0.0, float(getattr(snapshot, "last_started_at", 0.0) or 0.0))
        if last_started_at > 0.0:
            self._last_voip_iterate_started_at = last_started_at

        sample_id = max(0, int(getattr(snapshot, "sample_id", 0) or 0))
        if sample_id <= 0 or sample_id == self._last_voip_timing_sample_id:
            return

        self._last_voip_timing_sample_id = sample_id
        self._last_voip_schedule_delay_seconds = max(
            0.0,
            float(getattr(snapshot, "schedule_delay_seconds", 0.0) or 0.0),
        )
        self._last_voip_iterate_duration_seconds = max(
            0.0,
            float(getattr(snapshot, "total_duration_seconds", 0.0) or 0.0),
        )
        self._last_voip_native_events = max(0, int(getattr(snapshot, "drained_events", 0) or 0))
        self._last_voip_native_iterate_duration_seconds = max(
            0.0,
            float(getattr(snapshot, "native_duration_seconds", 0.0) or 0.0),
        )
        self._last_voip_event_drain_duration_seconds = max(
            0.0,
            float(getattr(snapshot, "event_drain_duration_seconds", 0.0) or 0.0),
        )

        delayed = (
            self._last_voip_schedule_delay_seconds >= self._voip_schedule_delay_warning_seconds()
        )
        slow = self._last_voip_iterate_duration_seconds >= self._voip_iterate_warning_seconds()
        self._record_voip_timing_sample(
            monotonic_now=max(
                last_started_at,
                float(getattr(snapshot, "last_completed_at", last_started_at) or last_started_at),
            ),
            schedule_delay_seconds=self._last_voip_schedule_delay_seconds,
            iterate_duration_seconds=self._last_voip_iterate_duration_seconds,
            native_iterate_duration_seconds=self._last_voip_native_iterate_duration_seconds,
            event_drain_duration_seconds=self._last_voip_event_drain_duration_seconds,
            drained_events=self._last_voip_native_events,
            delayed=delayed,
            slow=slow,
        )

        if delayed or slow:
            voip_logger.warning(
                "VoIP iterate timing drift: "
                "schedule_delay_ms={:.1f} iterate_ms={:.1f} "
                "interval_ms={:.1f} configured_interval_ms={:.1f} "
                "native_iterate_ms={:.1f} event_drain_ms={:.1f} "
                "native_events={} cadence_mode={} cadence_reason={} "
                "pending_callbacks={} pending_events={} screen={} state={}",
                self._last_voip_schedule_delay_seconds * 1000.0,
                self._last_voip_iterate_duration_seconds * 1000.0,
                self._effective_voip_iterate_interval_seconds() * 1000.0,
                self.app._voip_iterate_interval_seconds * 1000.0,
                self._last_voip_native_iterate_duration_seconds * 1000.0,
                self._last_voip_event_drain_duration_seconds * 1000.0,
                self._last_voip_native_events,
                self._current_cadence_mode,
                self._current_cadence_reason,
                self.app._pending_main_thread_callback_count(),
                self.app.event_bus.pending_count(),
                self._current_screen_name(),
                self._runtime_state_name(),
            )

    def process_pending_main_thread_actions(self, limit: Optional[int] = None) -> int:
        """Drain queued typed events scheduled by worker threads."""
        started_at = time.monotonic()
        callback_result = self._drain_pending_main_thread_callbacks(limit)
        remaining_limit = (
            None
            if limit is None
            else max(0, limit - callback_result.regular_callbacks_processed)
        )
        events_processed = self.app.event_bus.drain(remaining_limit)
        result = self._snapshot_main_thread_drain_result(
            callbacks_processed=callback_result.total_processed,
            events_processed=events_processed,
        )
        self._record_main_thread_drain_result(result)
        self._warn_if_slow(
            "main-thread drain",
            started_at=started_at,
            threshold_seconds=self._SLOW_MAIN_THREAD_DRAIN_WARNING_SECONDS,
            detail=self._main_thread_drain_detail(result),
        )
        return result.total_processed

    def _process_pending_main_thread_actions_for_iteration(self) -> int:
        """Advance generic queue work with hard per-iteration fairness budgets."""

        started_at = time.monotonic()
        callback_budget = self._main_thread_callback_drain_budget()
        event_budget = self._event_bus_drain_budget()
        callback_result = self._drain_pending_main_thread_callbacks(callback_budget)
        result = self._snapshot_main_thread_drain_result(
            callbacks_processed=callback_result.total_processed,
            events_processed=self.app.event_bus.drain(event_budget),
            callback_budget=callback_budget,
            event_budget=event_budget,
        )
        self._record_main_thread_drain_result(result)
        self._maybe_log_main_thread_drain_budget_hit(result)
        self._warn_if_slow(
            "main-thread drain",
            started_at=started_at,
            threshold_seconds=self._SLOW_MAIN_THREAD_DRAIN_WARNING_SECONDS,
            detail=self._main_thread_drain_detail(result),
        )
        return result.total_processed

    def _main_thread_callback_drain_budget(self) -> int:
        """Return the maximum callback count the coordinator should drain per iteration."""

        return max(1, int(self._MAIN_THREAD_CALLBACK_DRAIN_BUDGET))

    def _event_bus_drain_budget(self) -> int:
        """Return the maximum typed event count the coordinator should drain per iteration."""

        return max(1, int(self._EVENT_BUS_DRAIN_BUDGET))

    def _pending_work_loop_sleep_seconds(self) -> float:
        """Return the coordinator sleep used while generic queue work is backlogged."""

        # Pending-work cadence intentionally stays fixed at 10 ms so backlog yields
        # between iterations instead of tracking the faster VoIP cadence.
        return self._PENDING_WORK_LOOP_INTERVAL_SECONDS

    def _drain_pending_main_thread_callbacks(
        self,
        limit: int | None = None,
    ) -> _CallbackDrainResult:
        """Run safety callbacks ahead of ordinary queue work."""

        safety_callbacks_processed = self._drain_callback_queue(
            self.app._pending_safety_main_thread_callbacks
        )
        regular_callbacks_processed = self._drain_callback_queue(
            self.app._pending_main_thread_callbacks,
            limit=limit,
        )
        return _CallbackDrainResult(
            regular_callbacks_processed=regular_callbacks_processed,
            safety_callbacks_processed=safety_callbacks_processed,
        )

    def _drain_callback_queue(
        self,
        queue_obj: Any,
        *,
        limit: int | None = None,
    ) -> int:
        """Run queued coordinator-thread callbacks with an optional hard count limit."""

        processed = 0
        while limit is None or processed < limit:
            try:
                callback = queue_obj.get_nowait()
            except Empty:
                break

            try:
                callback()
            except Exception as exc:
                logger.error(f"Error handling scheduled main-thread callback: {exc}")
            processed += 1

        return processed

    def _snapshot_main_thread_drain_result(
        self,
        *,
        callbacks_processed: int,
        events_processed: int,
        callback_budget: int | None = None,
        event_budget: int | None = None,
    ) -> _MainThreadDrainResult:
        """Capture drain totals and remaining backlog after one coordinator drain."""

        callback_backlog = self.app._pending_main_thread_callback_count()
        # Deferred callback count is best-effort: queues without qsize support degrade
        # to 0 here rather than paying extra coordinator work to derive a stronger estimate.
        return _MainThreadDrainResult(
            callbacks_processed=callbacks_processed,
            events_processed=events_processed,
            callbacks_deferred=max(0, callback_backlog) if callback_backlog is not None else 0,
            events_deferred=max(0, self.app.event_bus.pending_count()),
            callback_budget=callback_budget,
            event_budget=event_budget,
        )

    def _record_main_thread_drain_result(self, result: _MainThreadDrainResult) -> None:
        """Persist the latest queue-drain snapshot for diagnostics and status output."""

        self._last_main_thread_callbacks_drained = result.callbacks_processed
        self._last_event_bus_events_drained = result.events_processed
        self._last_main_thread_callbacks_deferred = result.callbacks_deferred
        self._last_event_bus_events_deferred = result.events_deferred
        self._last_main_thread_callback_budget_hit = result.callback_budget_hit
        self._last_event_bus_event_budget_hit = result.event_budget_hit
        self._last_main_thread_callback_drain_budget = result.callback_budget
        self._last_event_bus_drain_budget = result.event_budget

    def _main_thread_drain_detail(self, result: _MainThreadDrainResult) -> str:
        """Format one queue-drain snapshot for warnings and debug logs."""

        callback_budget = (
            "all" if result.callback_budget is None else str(result.callback_budget)
        )
        event_budget = "all" if result.event_budget is None else str(result.event_budget)
        return (
            f"callbacks={result.callbacks_processed}/{callback_budget} "
            f"events={result.events_processed}/{event_budget} "
            f"deferred_callbacks={result.callbacks_deferred} "
            f"deferred_events={result.events_deferred}"
        )

    def _maybe_log_main_thread_drain_budget_hit(self, result: _MainThreadDrainResult) -> None:
        """Surface queue-budget pressure without logging on every hot-loop iteration."""

        if not (result.callback_budget_hit or result.event_budget_hit):
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
            "callbacks_drained={} callback_budget={} callbacks_deferred={} "
            "events_drained={} event_budget={} events_deferred={} "
            "cadence_mode={} cadence_reason={} screen={} state={}",
            result.callbacks_processed,
            result.callback_budget,
            result.callbacks_deferred,
            result.events_processed,
            result.event_budget,
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
            # Safety completions must bypass the ordinary per-iteration fairness cap.
            self.app._pending_safety_main_thread_callbacks.put(callback)
            return
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

        started_at = time.monotonic()
        monotonic_now = time.monotonic() if now is None else now
        if self.app._last_lvgl_pump_at <= 0.0:
            delta_ms = 0
        else:
            delta_ms = int(max(0.0, monotonic_now - self.app._last_lvgl_pump_at) * 1000.0)
        self.app._last_lvgl_pump_at = monotonic_now

        if self.app._lvgl_input_bridge is not None:
            self.app._lvgl_input_bridge.process_pending()
        self.app._lvgl_backend.pump(delta_ms)
        self._warn_if_slow(
            "lvgl pump",
            started_at=started_at,
            threshold_seconds=self._SLOW_LVGL_PUMP_WARNING_SECONDS,
            detail=f"delta_ms={delta_ms}",
        )

    def iterate_voip_backend_if_due(self, now: float | None = None) -> None:
        """Advance or observe VoIP keep-alive work without stalling the coordinator thread."""
        if self.app.voip_manager is None or not self.app.voip_manager.running:
            return

        if self._voip_background_iterate_enabled():
            ensure_running = getattr(self.app.voip_manager, "ensure_background_iterate_running", None)
            if callable(ensure_running):
                ensure_running()
            poll_housekeeping = getattr(self.app.voip_manager, "poll_housekeeping", None)
            if callable(poll_housekeeping):
                poll_housekeeping()
            self._sync_background_voip_timing_sample()
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
        self.app._next_voip_iterate_at = self._next_voip_due_at_for_cadence(
            monotonic_now=monotonic_now,
            iterate_interval_seconds=self._effective_voip_iterate_interval_seconds(),
        )

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
                "interval_ms={:.1f} configured_interval_ms={:.1f} "
                "native_iterate_ms={:.1f} event_drain_ms={:.1f} "
                "native_events={} cadence_mode={} cadence_reason={} "
                "pending_callbacks={} pending_events={} screen={} state={}",
                schedule_delay_seconds * 1000.0,
                iterate_duration_seconds * 1000.0,
                since_last_iterate_seconds * 1000.0,
                self._effective_voip_iterate_interval_seconds() * 1000.0,
                self.app._voip_iterate_interval_seconds * 1000.0,
                self._last_voip_native_iterate_duration_seconds * 1000.0,
                self._last_voip_event_drain_duration_seconds * 1000.0,
                native_events,
                self._current_cadence_mode,
                self._current_cadence_reason,
                self.app._pending_main_thread_callback_count(),
                self.app.event_bus.pending_count(),
                self._current_screen_name(),
                self._runtime_state_name(),
            )
        self._warn_if_slow(
            "voip iterate",
            started_at=started_at,
            threshold_seconds=self._SLOW_VOIP_ITERATE_WARNING_SECONDS,
            detail=(f"screen={self._current_screen_name()} " f"state={self._runtime_state_name()}"),
        )

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
        if (
            self.app.voip_manager is not None
            and self.app.voip_manager.running
            and not self._voip_background_iterate_enabled()
        ):
            if self.app._next_voip_iterate_at <= 0.0:
                deadlines.append(self._effective_voip_iterate_interval_seconds())
            else:
                deadlines.append(max(0.0, self.app._next_voip_iterate_at - monotonic_now))

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
                "manager_recovery",
                lambda: self.app.recovery_service.attempt_manager_recovery(now=monotonic_now),
            )
            self._measure_blocking_span(
                "power_poll",
                lambda: self.app.power_runtime.poll_status(now=monotonic_now),
            )
            if self.app.cloud_manager is not None:
                self._measure_blocking_span(
                    "cloud_tick",
                    lambda: self.app.cloud_manager.tick(monotonic_now),
                )
            self._measure_blocking_span(
                "lvgl_pump",
                lambda: self.pump_lvgl_backend(monotonic_now),
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
                    self.app._pending_main_thread_callback_count(),
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
            "runtime_main_thread_callbacks_drained": self._last_main_thread_callbacks_drained,
            "runtime_event_bus_events_drained": self._last_event_bus_events_drained,
            "runtime_main_thread_callbacks_deferred": self._last_main_thread_callbacks_deferred,
            "runtime_event_bus_events_deferred": self._last_event_bus_events_deferred,
            "runtime_main_thread_callback_drain_budget": (
                self._last_main_thread_callback_drain_budget
            ),
            "runtime_event_bus_drain_budget": self._last_event_bus_drain_budget,
            "runtime_main_thread_callback_budget_hit": (
                self._last_main_thread_callback_budget_hit
            ),
            "runtime_event_bus_event_budget_hit": self._last_event_bus_event_budget_hit,
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

        configured_voip_interval_seconds = max(
            0.01,
            float(self.app._voip_iterate_interval_seconds),
        )
        fast_loop_sleep_seconds = min(
            self._RELAXED_IDLE_INTERVAL_SECONDS,
            configured_voip_interval_seconds,
        )
        pending_callbacks = max(0, self.app._pending_main_thread_callback_count() or 0)
        pending_events = max(0, self.app.event_bus.pending_count())
        if pending_callbacks > 0 or pending_events > 0:
            return _LoopCadenceDecision(
                mode="latency_sensitive",
                reason="pending_work",
                loop_sleep_seconds=self._pending_work_loop_sleep_seconds(),
                voip_iterate_interval_seconds=configured_voip_interval_seconds,
            )

        if self.app._pending_shutdown is not None or self.app._power_alert is not None:
            return _LoopCadenceDecision(
                mode="latency_sensitive",
                reason="safety_transition",
                loop_sleep_seconds=fast_loop_sleep_seconds,
                voip_iterate_interval_seconds=configured_voip_interval_seconds,
            )

        if self._runtime_state_name() in self._LATENCY_SENSITIVE_STATES:
            return _LoopCadenceDecision(
                mode="latency_sensitive",
                reason="call_or_connecting_state",
                loop_sleep_seconds=fast_loop_sleep_seconds,
                voip_iterate_interval_seconds=configured_voip_interval_seconds,
            )

        recent_input_age_seconds = (
            max(0.0, monotonic_now - self.app._last_input_activity_at)
            if self.app._last_input_activity_at > 0.0
            else None
        )
        if (
            recent_input_age_seconds is not None
            and recent_input_age_seconds <= self._RECENT_INPUT_WINDOW_SECONDS
        ):
            return _LoopCadenceDecision(
                mode="latency_sensitive",
                reason="recent_input",
                loop_sleep_seconds=fast_loop_sleep_seconds,
                voip_iterate_interval_seconds=configured_voip_interval_seconds,
            )

        if not self.app._screen_awake:
            return _LoopCadenceDecision(
                mode="idle_sleeping",
                reason="screen_sleeping",
                loop_sleep_seconds=self._SCREEN_SLEEP_IDLE_INTERVAL_SECONDS,
                voip_iterate_interval_seconds=max(
                    configured_voip_interval_seconds,
                    self._SCREEN_SLEEP_IDLE_INTERVAL_SECONDS,
                ),
            )

        return _LoopCadenceDecision(
            mode="idle_awake",
            reason="screen_awake_idle",
            loop_sleep_seconds=self._RELAXED_IDLE_INTERVAL_SECONDS,
            voip_iterate_interval_seconds=max(
                configured_voip_interval_seconds,
                self._RELAXED_IDLE_INTERVAL_SECONDS,
            ),
        )

    def _apply_loop_cadence(
        self,
        decision: _LoopCadenceDecision,
        *,
        monotonic_now: float,
    ) -> None:
        """Store one cadence decision and accelerate due work when responsiveness tightens."""

        previous_voip_interval_seconds = self._current_voip_iterate_interval_seconds
        changed = (
            self._current_cadence_mode != decision.mode
            or self._current_cadence_reason != decision.reason
            or abs(self._current_loop_sleep_seconds - decision.loop_sleep_seconds) > 1e-9
            or abs(previous_voip_interval_seconds - decision.voip_iterate_interval_seconds) > 1e-9
        )
        self._current_cadence_mode = decision.mode
        self._current_cadence_reason = decision.reason
        self._current_loop_sleep_seconds = decision.loop_sleep_seconds
        self._current_voip_iterate_interval_seconds = decision.voip_iterate_interval_seconds
        self._last_cadence_selected_at = monotonic_now

        if (
            self.app.voip_manager is not None
            and self.app.voip_manager.running
        ):
            if self._voip_background_iterate_enabled():
                ensure_running = getattr(
                    self.app.voip_manager,
                    "ensure_background_iterate_running",
                    None,
                )
                if callable(ensure_running):
                    ensure_running()
                set_interval = getattr(
                    self.app.voip_manager,
                    "set_iterate_interval_seconds",
                    None,
                )
                if callable(set_interval):
                    set_interval(decision.voip_iterate_interval_seconds)
                self.app._next_voip_iterate_at = 0.0
            else:
                self.app._next_voip_iterate_at = self._next_voip_due_at_for_cadence(
                    monotonic_now=monotonic_now,
                    iterate_interval_seconds=decision.voip_iterate_interval_seconds,
                )

        if not changed:
            return

        coord_logger.info(
            "Runtime cadence: "
            "mode={} reason={} sleep_ms={:.1f} voip_interval_ms={:.1f} "
            "configured_voip_interval_ms={:.1f} screen={} state={}",
            decision.mode,
            decision.reason,
            decision.loop_sleep_seconds * 1000.0,
            decision.voip_iterate_interval_seconds * 1000.0,
            self.app._voip_iterate_interval_seconds * 1000.0,
            self._current_screen_name(),
            self._runtime_state_name(),
        )

    def _effective_voip_iterate_interval_seconds(self) -> float:
        """Return the currently selected VoIP iterate cadence."""

        return max(0.01, self._current_voip_iterate_interval_seconds)

    def _next_voip_due_at_for_cadence(
        self,
        *,
        monotonic_now: float,
        iterate_interval_seconds: float,
    ) -> float:
        """Return the next VoIP iterate deadline aligned to the current cadence."""

        effective_interval_seconds = max(0.01, iterate_interval_seconds)
        if self._last_voip_iterate_started_at <= 0.0:
            return monotonic_now + effective_interval_seconds
        return max(
            monotonic_now,
            self._last_voip_iterate_started_at + effective_interval_seconds,
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
            "pending_callbacks={} pending_events={} screen={} state={}",
            loop_gap_seconds * 1000.0,
            self._effective_voip_iterate_interval_seconds() * 1000.0,
            self._current_cadence_mode,
            self._current_cadence_reason,
            self.app._pending_main_thread_callback_count(),
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
            "interval_ms={:.1f} configured_interval_ms={:.1f} "
            "cadence_mode={} cadence_reason={} screen={} state={}",
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
            self._effective_voip_iterate_interval_seconds() * 1000.0,
            self.app._voip_iterate_interval_seconds * 1000.0,
            self._current_cadence_mode,
            self._current_cadence_reason,
            self._current_screen_name(),
            self._runtime_state_name(),
        )
        self._voip_timing_window = _VoipTimingWindow(started_at=monotonic_now)

    def _runtime_loop_gap_warning_seconds(self) -> float:
        """Return the loop-gap threshold that is worth surfacing on hardware."""

        return max(
            self._MIN_RUNTIME_LOOP_GAP_WARNING_SECONDS,
            self._effective_voip_iterate_interval_seconds() * 6.0,
        )

    def _runtime_iteration_warning_seconds(self) -> float:
        """Return the total iteration duration threshold for broad blocking work."""

        return max(
            self._MIN_RUNTIME_ITERATION_WARNING_SECONDS,
            self._effective_voip_iterate_interval_seconds() * 6.0,
        )

    def _runtime_blocking_span_warning_seconds(self) -> float:
        """Return the per-step blocking threshold for coordinator runtime spans."""

        return max(
            self._MIN_RUNTIME_BLOCKING_SPAN_WARNING_SECONDS,
            self._effective_voip_iterate_interval_seconds() * 6.0,
        )

    def _voip_schedule_delay_warning_seconds(self) -> float:
        """Return the schedule-drift threshold for VoIP iterate warnings."""

        return max(
            self._MIN_VOIP_SCHEDULE_DELAY_WARNING_SECONDS,
            self._effective_voip_iterate_interval_seconds() * 4.0,
        )

    def _voip_iterate_warning_seconds(self) -> float:
        """Return the per-iterate duration threshold for VoIP keep-alive warnings."""

        return max(
            self._MIN_VOIP_ITERATE_WARNING_SECONDS,
            self._effective_voip_iterate_interval_seconds() * 4.0,
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

    def _warn_if_slow(
        self,
        phase: str,
        *,
        started_at: float,
        threshold_seconds: float,
        detail: str = "",
    ) -> None:
        """Emit a targeted warning when one coordinator-loop phase runs unusually long."""

        elapsed_seconds = time.monotonic() - started_at
        if elapsed_seconds < threshold_seconds:
            return

        logger.warning(
            "Slow runtime phase: {} took {:.1f} ms ({})",
            phase,
            elapsed_seconds * 1000.0,
            detail or "no extra detail",
        )
