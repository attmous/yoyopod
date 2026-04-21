"""Compatibility shim for the relocated diagnostics watchdog helpers."""

from yoyopod.core.diagnostics.watchdog import (
    ResponsivenessWatchdog,
    ResponsivenessWatchdogDecision,
    _capture_responsiveness_watchdog_evidence,
    _install_traceback_dump_handlers,
    _log_setup_failure_guidance,
    _log_signal_snapshot,
    _signal_name,
    _uninstall_traceback_dump_handlers,
    evaluate_responsiveness_status,
)

__all__ = [
    "ResponsivenessWatchdog",
    "ResponsivenessWatchdogDecision",
    "_capture_responsiveness_watchdog_evidence",
    "_install_traceback_dump_handlers",
    "_log_setup_failure_guidance",
    "_log_signal_snapshot",
    "_signal_name",
    "_uninstall_traceback_dump_handlers",
    "evaluate_responsiveness_status",
]
