"""VoIP keep-alive timing state and sampling helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yoyopod.utils.logger import get_subsystem_logger

if TYPE_CHECKING:
    from yoyopod.runtime.loop import RuntimeLoopService


voip_logger = get_subsystem_logger("voip")


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
            "pending_callbacks={} pending_events={} screen={} state={}",
            runtime_loop._last_voip_schedule_delay_seconds * 1000.0,
            runtime_loop._last_voip_iterate_duration_seconds * 1000.0,
            runtime_loop._effective_voip_iterate_interval_seconds() * 1000.0,
            runtime_loop.app._voip_iterate_interval_seconds * 1000.0,
            runtime_loop._last_voip_native_iterate_duration_seconds * 1000.0,
            runtime_loop._last_voip_event_drain_duration_seconds * 1000.0,
            runtime_loop._last_voip_native_events,
            runtime_loop._current_cadence_mode,
            runtime_loop._current_cadence_reason,
            runtime_loop.app._pending_main_thread_callback_count(),
            runtime_loop.app.event_bus.pending_count(),
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
