"""Compatibility shim for the relocated responsiveness watchdog."""

from yoyopod.core.diagnostics.watchdog import (
    ResponsivenessWatchdog,
    ResponsivenessWatchdogDecision,
    evaluate_responsiveness_status,
)

__all__ = [
    "ResponsivenessWatchdog",
    "ResponsivenessWatchdogDecision",
    "evaluate_responsiveness_status",
]
