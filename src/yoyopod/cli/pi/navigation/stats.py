"""Navigation soak diagnostics models."""

from __future__ import annotations

from dataclasses import dataclass, field


class NavigationSoakFailure(RuntimeError):
    """Raised when the navigation soak cannot complete its expected path."""


@dataclass(slots=True)
class NavigationSoakStats:
    """Accumulate compact soak diagnostics for the final summary."""

    actions: int = 0
    visited_screens: set[str] = field(default_factory=set)
    explicit_idle_seconds: float = 0.0
    max_runtime_iteration_ms: float = 0.0
    max_runtime_loop_gap_ms: float = 0.0
    max_voip_schedule_delay_ms: float = 0.0
    heaviest_blocking_span_name: str | None = None
    heaviest_blocking_span_ms: float = 0.0
    last_track_name: str | None = None
    playback_verified: bool = False
    sleep_wake_status: str = "skipped"

    def observe_snapshot(self, snapshot: dict[str, float | int | None]) -> None:
        """Record high-level loop timing from one runtime snapshot."""

        runtime_iteration = snapshot.get("runtime_iteration_seconds")
        if runtime_iteration is not None:
            self.max_runtime_iteration_ms = max(
                self.max_runtime_iteration_ms,
                float(runtime_iteration) * 1000.0,
            )

        loop_gap = snapshot.get("runtime_loop_gap_seconds")
        if loop_gap is not None:
            self.max_runtime_loop_gap_ms = max(
                self.max_runtime_loop_gap_ms,
                float(loop_gap) * 1000.0,
            )

        voip_schedule_delay = snapshot.get("voip_schedule_delay_seconds")
        if voip_schedule_delay is not None:
            self.max_voip_schedule_delay_ms = max(
                self.max_voip_schedule_delay_ms,
                float(voip_schedule_delay) * 1000.0,
            )

        blocking_name = snapshot.get("runtime_blocking_span_name")
        blocking_seconds = snapshot.get("runtime_blocking_span_seconds")
        if blocking_name and blocking_seconds is not None:
            blocking_ms = float(blocking_seconds) * 1000.0
            if blocking_ms >= self.heaviest_blocking_span_ms:
                self.heaviest_blocking_span_ms = blocking_ms
                self.heaviest_blocking_span_name = str(blocking_name)
