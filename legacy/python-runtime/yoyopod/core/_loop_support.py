"""Private support helpers for the canonical runtime loop service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import time
from typing import TYPE_CHECKING, TypeVar

from loguru import logger

from yoyopod.core.logging import get_subsystem_logger

if TYPE_CHECKING:
    from yoyopod.core.loop import RuntimeLoopService


coord_logger = get_subsystem_logger("coord")
voip_logger = get_subsystem_logger("voip")
_T = TypeVar("_T")


@dataclass(frozen=True, slots=True)
class _LoopCadenceDecision:
    """Normalized runtime cadence decision for the next coordinator wake."""

    mode: str
    reason: str
    loop_sleep_seconds: float
    voip_iterate_interval_seconds: float


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


def _record_blocking_span(
    runtime_loop: "RuntimeLoopService",
    span_name: str,
    duration_seconds: float,
) -> None:
    """Persist and log one named coordinator-thread blocking span."""

    runtime_loop._last_runtime_blocking_span_name = span_name
    runtime_loop._last_runtime_blocking_span_seconds = duration_seconds
    runtime_loop._last_runtime_blocking_span_recorded_at = time.monotonic()
    if (
        runtime_loop._voip_timing_window.started_at > 0.0
        and duration_seconds >= runtime_loop._voip_timing_window.max_blocking_span_seconds
    ):
        # Blocking spans only contribute to the summary once a VoIP timing window
        # exists, which starts with the first recorded iterate sample.
        runtime_loop._voip_timing_window.max_blocking_span_name = span_name
        runtime_loop._voip_timing_window.max_blocking_span_seconds = duration_seconds
    coord_logger.warning(
        "Coordinator blocking span: "
        "span={} duration_ms={:.1f} pending_scheduler_tasks={} pending_events={} screen={} state={}",
        span_name,
        duration_seconds * 1000.0,
        runtime_loop.pending_main_thread_callback_count(),
        runtime_loop.app.bus.pending_count(),
        runtime_loop._current_screen_name(),
        runtime_loop._runtime_state_name(),
    )


def _measure_blocking_span(
    runtime_loop: "RuntimeLoopService",
    span_name: str,
    callback: Callable[[], _T],
) -> _T:
    """Run one coordinator step and surface unusually long blocking spans."""

    started_at = time.monotonic()
    try:
        return callback()
    finally:
        duration_seconds = max(0.0, time.monotonic() - started_at)
        if duration_seconds >= runtime_loop._runtime_blocking_span_warning_seconds():
            runtime_loop._record_blocking_span(span_name, duration_seconds)


def _warn_if_slow(
    runtime_loop: "RuntimeLoopService",
    phase: str,
    *,
    started_at: float,
    threshold_seconds: float,
    detail: str = "",
    detail_factory: Callable[[], str] | None = None,
) -> None:
    """Emit a targeted warning when one coordinator-loop phase runs unusually long."""

    elapsed_seconds = time.monotonic() - started_at
    if elapsed_seconds < threshold_seconds:
        return

    if detail_factory is not None:
        detail = detail_factory()

    # Keep generic warnings under the default logger to preserve historical behavior.
    logger.warning(
        "Slow runtime phase: {} took {:.1f} ms ({})",
        phase,
        elapsed_seconds * 1000.0,
        detail or "no extra detail",
    )


def _runtime_loop_gap_warning_seconds(runtime_loop: "RuntimeLoopService") -> float:
    """Return the loop-gap threshold that is worth surfacing on hardware."""

    return max(
        runtime_loop._MIN_RUNTIME_LOOP_GAP_WARNING_SECONDS,
        runtime_loop._effective_voip_iterate_interval_seconds() * 6.0,
    )


def _runtime_iteration_warning_seconds(runtime_loop: "RuntimeLoopService") -> float:
    """Return the total iteration duration threshold for broad blocking work."""

    return max(
        runtime_loop._MIN_RUNTIME_ITERATION_WARNING_SECONDS,
        runtime_loop._effective_voip_iterate_interval_seconds() * 6.0,
    )


def _runtime_blocking_span_warning_seconds(runtime_loop: "RuntimeLoopService") -> float:
    """Return the per-step blocking threshold for coordinator runtime spans."""

    return max(
        runtime_loop._MIN_RUNTIME_BLOCKING_SPAN_WARNING_SECONDS,
        runtime_loop._effective_voip_iterate_interval_seconds() * 6.0,
    )


def _voip_schedule_delay_warning_seconds(runtime_loop: "RuntimeLoopService") -> float:
    """Return the schedule-drift threshold for VoIP iterate warnings."""

    return max(
        runtime_loop._MIN_VOIP_SCHEDULE_DELAY_WARNING_SECONDS,
        runtime_loop._effective_voip_iterate_interval_seconds() * 4.0,
    )


def _voip_iterate_warning_seconds(runtime_loop: "RuntimeLoopService") -> float:
    """Return the per-iterate duration threshold for VoIP keep-alive warnings."""

    return max(
        runtime_loop._MIN_VOIP_ITERATE_WARNING_SECONDS,
        runtime_loop._effective_voip_iterate_interval_seconds() * 4.0,
    )


def _select_loop_cadence(
    runtime_loop: "RuntimeLoopService",
    *,
    monotonic_now: float,
) -> _LoopCadenceDecision:
    """Choose the next runtime cadence from current state and queued work."""

    runtime_metrics = getattr(runtime_loop.app, "runtime_metrics", None)
    last_input_activity_at = (
        runtime_metrics.last_input_activity_at
        if runtime_metrics is not None
        else 0.0
    )
    configured_voip_interval_seconds = max(
        0.01,
        float(runtime_loop.app._voip_iterate_interval_seconds),
    )
    fast_loop_sleep_seconds = min(
        runtime_loop._RELAXED_IDLE_INTERVAL_SECONDS,
        configured_voip_interval_seconds,
    )
    pending_scheduler_tasks = max(0, runtime_loop.pending_main_thread_callback_count())
    pending_events = max(0, runtime_loop.app.bus.pending_count())
    if pending_scheduler_tasks > 0 or pending_events > 0:
        return _LoopCadenceDecision(
            mode="latency_sensitive",
            reason="pending_work",
            loop_sleep_seconds=runtime_loop._pending_work_loop_sleep_seconds(),
            voip_iterate_interval_seconds=configured_voip_interval_seconds,
        )

    if runtime_loop.app._pending_shutdown is not None or runtime_loop.app._power_alert is not None:
        return _LoopCadenceDecision(
            mode="latency_sensitive",
            reason="safety_transition",
            loop_sleep_seconds=fast_loop_sleep_seconds,
            voip_iterate_interval_seconds=configured_voip_interval_seconds,
        )

    if runtime_loop._runtime_state_name() in runtime_loop._LATENCY_SENSITIVE_STATES:
        return _LoopCadenceDecision(
            mode="latency_sensitive",
            reason="call_or_connecting_state",
            loop_sleep_seconds=fast_loop_sleep_seconds,
            voip_iterate_interval_seconds=configured_voip_interval_seconds,
        )

    recent_input_age_seconds = (
        max(0.0, monotonic_now - last_input_activity_at)
        if last_input_activity_at > 0.0
        else None
    )
    if (
        recent_input_age_seconds is not None
        and recent_input_age_seconds <= runtime_loop._RECENT_INPUT_WINDOW_SECONDS
    ):
        return _LoopCadenceDecision(
            mode="latency_sensitive",
            reason="recent_input",
            loop_sleep_seconds=fast_loop_sleep_seconds,
            voip_iterate_interval_seconds=configured_voip_interval_seconds,
        )

    if not runtime_loop.app._screen_awake:
        return _LoopCadenceDecision(
            mode="idle_sleeping",
            reason="screen_sleeping",
            loop_sleep_seconds=runtime_loop._SCREEN_SLEEP_IDLE_INTERVAL_SECONDS,
            voip_iterate_interval_seconds=max(
                configured_voip_interval_seconds,
                runtime_loop._SCREEN_SLEEP_IDLE_INTERVAL_SECONDS,
            ),
        )

    return _LoopCadenceDecision(
        mode="idle_awake",
        reason="screen_awake_idle",
        loop_sleep_seconds=runtime_loop._RELAXED_IDLE_INTERVAL_SECONDS,
        voip_iterate_interval_seconds=max(
            configured_voip_interval_seconds,
            runtime_loop._RELAXED_IDLE_INTERVAL_SECONDS,
        ),
    )


def _apply_loop_cadence(
    runtime_loop: "RuntimeLoopService",
    decision: _LoopCadenceDecision,
    *,
    monotonic_now: float,
) -> None:
    """Store one cadence decision and accelerate due work when responsiveness tightens."""

    previous_voip_interval_seconds = runtime_loop._current_voip_iterate_interval_seconds
    changed = (
        runtime_loop._current_cadence_mode != decision.mode
        or runtime_loop._current_cadence_reason != decision.reason
        or abs(runtime_loop._current_loop_sleep_seconds - decision.loop_sleep_seconds) > 1e-9
        or abs(previous_voip_interval_seconds - decision.voip_iterate_interval_seconds) > 1e-9
    )
    runtime_loop._current_cadence_mode = decision.mode
    runtime_loop._current_cadence_reason = decision.reason
    runtime_loop._current_loop_sleep_seconds = decision.loop_sleep_seconds
    runtime_loop._current_voip_iterate_interval_seconds = decision.voip_iterate_interval_seconds
    runtime_loop._last_cadence_selected_at = monotonic_now

    runtime_loop.app._next_voip_iterate_at = 0.0

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
        runtime_loop.app._voip_iterate_interval_seconds * 1000.0,
        runtime_loop._current_screen_name(),
        runtime_loop._runtime_state_name(),
    )


def _effective_voip_iterate_interval_seconds(runtime_loop: "RuntimeLoopService") -> float:
    """Return the currently selected VoIP iterate cadence."""

    return max(0.01, runtime_loop._current_voip_iterate_interval_seconds)


def _next_voip_due_at_for_cadence(
    runtime_loop: "RuntimeLoopService",
    *,
    monotonic_now: float,
    iterate_interval_seconds: float,
) -> float:
    """Return the next VoIP iterate deadline aligned to the current cadence."""

    effective_interval_seconds = max(0.01, iterate_interval_seconds)
    if runtime_loop._last_voip_iterate_started_at <= 0.0:
        return monotonic_now + effective_interval_seconds
    return max(
        monotonic_now,
        runtime_loop._last_voip_iterate_started_at + effective_interval_seconds,
    )


def _latest_voip_iterate_metrics(
    runtime_loop: "RuntimeLoopService",
) -> _VoipIterateMetrics | None:
    """Return the latest backend-native keep-alive sub-span timings when available."""

    if runtime_loop.app.voip_manager is None:
        return None

    get_metrics = getattr(runtime_loop.app.voip_manager, "get_iterate_metrics", None)
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


def _sync_background_voip_timing_sample(runtime_loop: "RuntimeLoopService") -> None:
    """Pull the latest background iterate sample into runtime timing snapshots."""

    if runtime_loop.app.voip_manager is None:
        return

    get_snapshot = getattr(runtime_loop.app.voip_manager, "get_iterate_timing_snapshot", None)
    if not callable(get_snapshot):
        return

    snapshot = get_snapshot()
    if snapshot is None:
        return

    last_started_at = max(0.0, float(getattr(snapshot, "last_started_at", 0.0) or 0.0))
    if last_started_at > 0.0:
        runtime_loop._last_voip_iterate_started_at = last_started_at

    sample_id = max(0, int(getattr(snapshot, "sample_id", 0) or 0))
    if sample_id <= 0 or sample_id == runtime_loop._last_voip_timing_sample_id:
        return

    runtime_loop._last_voip_timing_sample_id = sample_id
    runtime_loop._last_voip_schedule_delay_seconds = max(
        0.0,
        float(getattr(snapshot, "schedule_delay_seconds", 0.0) or 0.0),
    )
    runtime_loop._last_voip_iterate_duration_seconds = max(
        0.0,
        float(getattr(snapshot, "total_duration_seconds", 0.0) or 0.0),
    )
    runtime_loop._last_voip_native_events = max(0, int(getattr(snapshot, "drained_events", 0) or 0))
    runtime_loop._last_voip_native_iterate_duration_seconds = max(
        0.0,
        float(getattr(snapshot, "native_duration_seconds", 0.0) or 0.0),
    )
    runtime_loop._last_voip_event_drain_duration_seconds = max(
        0.0,
        float(getattr(snapshot, "event_drain_duration_seconds", 0.0) or 0.0),
    )

    delayed = (
        runtime_loop._last_voip_schedule_delay_seconds >= runtime_loop._voip_schedule_delay_warning_seconds()
    )
    slow = runtime_loop._last_voip_iterate_duration_seconds >= runtime_loop._voip_iterate_warning_seconds()
    _record_voip_timing_sample(
        runtime_loop=runtime_loop,
        monotonic_now=max(
            last_started_at,
            float(getattr(snapshot, "last_completed_at", last_started_at) or last_started_at),
        ),
        schedule_delay_seconds=runtime_loop._last_voip_schedule_delay_seconds,
        iterate_duration_seconds=runtime_loop._last_voip_iterate_duration_seconds,
        native_iterate_duration_seconds=runtime_loop._last_voip_native_iterate_duration_seconds,
        event_drain_duration_seconds=runtime_loop._last_voip_event_drain_duration_seconds,
        drained_events=runtime_loop._last_voip_native_events,
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
            "pending_scheduler_tasks={} pending_events={} screen={} state={}",
            runtime_loop._last_voip_schedule_delay_seconds * 1000.0,
            runtime_loop._last_voip_iterate_duration_seconds * 1000.0,
            runtime_loop._effective_voip_iterate_interval_seconds() * 1000.0,
            runtime_loop.app._voip_iterate_interval_seconds * 1000.0,
            runtime_loop._last_voip_native_iterate_duration_seconds * 1000.0,
            runtime_loop._last_voip_event_drain_duration_seconds * 1000.0,
            runtime_loop._last_voip_native_events,
            runtime_loop._current_cadence_mode,
            runtime_loop._current_cadence_reason,
            runtime_loop.pending_main_thread_callback_count(),
            runtime_loop.app.bus.pending_count(),
            runtime_loop._current_screen_name(),
            runtime_loop._runtime_state_name(),
        )


def _record_voip_timing_sample(
    runtime_loop: "RuntimeLoopService",
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

    if runtime_loop._voip_timing_window.started_at <= 0.0:
        runtime_loop._voip_timing_window.started_at = monotonic_now

    runtime_loop._voip_timing_window.samples += 1
    runtime_loop._voip_timing_window.total_schedule_delay_seconds += schedule_delay_seconds
    runtime_loop._voip_timing_window.max_schedule_delay_seconds = max(
        runtime_loop._voip_timing_window.max_schedule_delay_seconds,
        schedule_delay_seconds,
    )
    runtime_loop._voip_timing_window.total_iterate_duration_seconds += iterate_duration_seconds
    runtime_loop._voip_timing_window.max_iterate_duration_seconds = max(
        runtime_loop._voip_timing_window.max_iterate_duration_seconds,
        iterate_duration_seconds,
    )
    runtime_loop._voip_timing_window.max_native_iterate_duration_seconds = max(
        runtime_loop._voip_timing_window.max_native_iterate_duration_seconds,
        native_iterate_duration_seconds,
    )
    runtime_loop._voip_timing_window.max_event_drain_duration_seconds = max(
        runtime_loop._voip_timing_window.max_event_drain_duration_seconds,
        event_drain_duration_seconds,
    )
    runtime_loop._voip_timing_window.max_drained_events = max(
        runtime_loop._voip_timing_window.max_drained_events,
        drained_events,
    )
    runtime_loop._voip_timing_window.max_loop_gap_seconds = max(
        runtime_loop._voip_timing_window.max_loop_gap_seconds,
        runtime_loop._last_runtime_loop_gap_seconds,
    )
    if delayed:
        runtime_loop._voip_timing_window.delayed_samples += 1
    if slow:
        runtime_loop._voip_timing_window.slow_samples += 1


def _maybe_log_voip_timing_summary(
    runtime_loop: "RuntimeLoopService",
    *,
    monotonic_now: float,
) -> None:
    """Emit a low-frequency summary of keep-alive timing behavior."""

    window = runtime_loop._voip_timing_window
    if window.started_at <= 0.0 or window.samples <= 0:
        return

    if (
        runtime_loop._VOIP_TIMING_SUMMARY_INTERVAL_SECONDS > 0.0
        and (monotonic_now - window.started_at) < runtime_loop._VOIP_TIMING_SUMMARY_INTERVAL_SECONDS
    ):
        return

    average_schedule_delay_ms = (window.total_schedule_delay_seconds / window.samples) * 1000.0
    average_iterate_duration_ms = (window.total_iterate_duration_seconds / window.samples) * 1000.0
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
        runtime_loop._effective_voip_iterate_interval_seconds() * 1000.0,
        runtime_loop.app._voip_iterate_interval_seconds * 1000.0,
        runtime_loop._current_cadence_mode,
        runtime_loop._current_cadence_reason,
        runtime_loop._current_screen_name(),
        runtime_loop._runtime_state_name(),
    )
    runtime_loop._voip_timing_window = _VoipTimingWindow(started_at=monotonic_now)
