"""Typed commands for the scaffold display integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WakeDisplayCommand:
    """Wake the display immediately."""

    reason: str = ""


@dataclass(frozen=True, slots=True)
class SleepDisplayCommand:
    """Put the display to sleep immediately."""

    reason: str = ""


@dataclass(frozen=True, slots=True)
class SetBrightnessCommand:
    """Set the active brightness percentage."""

    percent: int


@dataclass(frozen=True, slots=True)
class SetIdleTimeoutCommand:
    """Set the inactivity timeout used by the display integration."""

    timeout_seconds: float
