"""Typed power-domain events."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.integrations.power.models import PowerSnapshot


@dataclass(frozen=True, slots=True)
class PowerSnapshotUpdated:
    """Published when a new power snapshot is collected."""

    snapshot: PowerSnapshot


@dataclass(frozen=True, slots=True)
class PowerAvailabilityChanged:
    """Published when the power backend becomes available or unavailable."""

    available: bool
    reason: str = ""


@dataclass(frozen=True, slots=True)
class LowBatteryWarningRaised:
    """Published when battery reaches the warning threshold."""

    threshold_percent: float
    battery_percent: float
    snapshot: PowerSnapshot


@dataclass(frozen=True, slots=True)
class GracefulShutdownRequested:
    """Published when battery reaches the critical shutdown threshold."""

    reason: str
    delay_seconds: float
    snapshot: PowerSnapshot


@dataclass(frozen=True, slots=True)
class GracefulShutdownCancelled:
    """Published when a pending battery shutdown is cancelled."""

    reason: str


__all__ = [
    "GracefulShutdownCancelled",
    "GracefulShutdownRequested",
    "LowBatteryWarningRaised",
    "PowerAvailabilityChanged",
    "PowerSnapshotUpdated",
]
