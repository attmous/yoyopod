"""Blocking span and warning-threshold helpers for runtime coordination."""

from __future__ import annotations

from collections.abc import Callable
import time
from loguru import logger
from typing import TYPE_CHECKING, TypeVar

from yoyopod.utils.logger import get_subsystem_logger

if TYPE_CHECKING:
    from yoyopod.runtime.loop import RuntimeLoopService

coord_logger = get_subsystem_logger("coord")
_T = TypeVar("_T")


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
        "span={} duration_ms={:.1f} pending_callbacks={} pending_events={} screen={} state={}",
        span_name,
        duration_seconds * 1000.0,
        runtime_loop.app._pending_main_thread_callback_count(),
        runtime_loop.app.event_bus.pending_count(),
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
) -> None:
    """Emit a targeted warning when one coordinator-loop phase runs unusually long."""

    elapsed_seconds = time.monotonic() - started_at
    if elapsed_seconds < threshold_seconds:
        return

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
