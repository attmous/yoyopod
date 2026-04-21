"""Compatibility shim for relocated coordinator blocking helpers."""

from yoyopod.core.blocking_monitor import (
    _measure_blocking_span,
    _record_blocking_span,
    _runtime_blocking_span_warning_seconds,
    _runtime_iteration_warning_seconds,
    _runtime_loop_gap_warning_seconds,
    _voip_iterate_warning_seconds,
    _voip_schedule_delay_warning_seconds,
    _warn_if_slow,
)

__all__ = [
    "_measure_blocking_span",
    "_record_blocking_span",
    "_runtime_blocking_span_warning_seconds",
    "_runtime_iteration_warning_seconds",
    "_runtime_loop_gap_warning_seconds",
    "_voip_iterate_warning_seconds",
    "_voip_schedule_delay_warning_seconds",
    "_warn_if_slow",
]
