"""Typed commands for the scaffold power integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class RefreshPowerSnapshotCommand:
    """Refresh the power snapshot immediately."""


@dataclass(frozen=True, slots=True)
class SyncTimeToRtcCommand:
    """Sync Raspberry Pi time to the PiSugar RTC."""


@dataclass(frozen=True, slots=True)
class SyncTimeFromRtcCommand:
    """Sync PiSugar RTC time back to the Raspberry Pi system clock."""


@dataclass(frozen=True, slots=True)
class SetRtcAlarmCommand:
    """Set the PiSugar wake alarm."""

    when: datetime
    repeat_mask: int = 127


@dataclass(frozen=True, slots=True)
class DisableRtcAlarmCommand:
    """Disable the PiSugar wake alarm."""
