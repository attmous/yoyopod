"""Compatibility shim for relocated VoIP timing helpers."""

from yoyopod.core.voip_timing import (
    _VoipIterateMetrics,
    _VoipTimingWindow,
    _latest_voip_iterate_metrics,
    _maybe_log_voip_timing_summary,
    _record_voip_timing_sample,
    _sync_background_voip_timing_sample,
)

__all__ = [
    "_VoipIterateMetrics",
    "_VoipTimingWindow",
    "_latest_voip_iterate_metrics",
    "_maybe_log_voip_timing_summary",
    "_record_voip_timing_sample",
    "_sync_background_voip_timing_sample",
]
