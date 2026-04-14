"""Small runtime state models shared by the runtime services."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class RecoveryState:
    """Track reconnect backoff for a recoverable subsystem."""

    next_attempt_at: float = 0.0
    delay_seconds: float = 1.0
    in_flight: bool = False

    def reset(self) -> None:
        """Reset backoff after a successful recovery."""
        self.next_attempt_at = 0.0
        self.delay_seconds = 1.0
        self.in_flight = False


@dataclass(slots=True)
class PowerAlert:
    """Short-lived full-screen power alert overlay."""

    title: str
    subtitle: str
    color: tuple[int, int, int]
    expires_at: float


@dataclass(slots=True)
class PendingShutdown:
    """Track a delayed low-battery shutdown countdown."""

    reason: str
    requested_at: float
    execute_at: float
    battery_percent: float | None
