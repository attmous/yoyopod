"""Lightweight responsiveness watchdog helpers for the frozen scaffold spine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(slots=True)
class ResponsivenessWatchdog:
    """Evaluate whether recent tick timings are within a healthy threshold."""

    max_p99_drain_ms: float = 250.0

    def snapshot(self, tick_stats: Mapping[str, float | int]) -> dict[str, float | bool]:
        """Return one simple health snapshot for diagnostics surfaces."""

        drain_ms_p99 = float(tick_stats.get("drain_ms_p99", 0.0))
        return {
            "healthy": drain_ms_p99 <= self.max_p99_drain_ms,
            "drain_ms_p99": drain_ms_p99,
            "max_p99_drain_ms": self.max_p99_drain_ms,
        }
