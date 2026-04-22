"""Canonical typed models for PiSugar-backed power management."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PowerDeviceInfo:
    """Static-ish information about the attached PiSugar device."""

    model: str | None = None
    firmware_version: str | None = None


@dataclass(frozen=True, slots=True)
class BatteryState:
    """Current battery and charger state."""

    level_percent: float | None = None
    voltage_volts: float | None = None
    charging: bool | None = None
    power_plugged: bool | None = None
    allow_charging: bool | None = None
    output_enabled: bool | None = None
    temperature_celsius: float | None = None


@dataclass(frozen=True, slots=True)
class RTCState:
    """Current RTC status exposed by PiSugar."""

    time: datetime | None = None
    alarm_enabled: bool | None = None
    alarm_time: datetime | None = None
    alarm_repeat_mask: int | None = None
    adjust_ppm: float | None = None


@dataclass(frozen=True, slots=True)
class ShutdownState:
    """Safe-shutdown configuration currently active on the PiSugar."""

    safe_shutdown_level_percent: float | None = None
    safe_shutdown_delay_seconds: int | None = None


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


@dataclass(frozen=True, slots=True)
class PowerSnapshot:
    """Best-effort point-in-time power snapshot."""

    available: bool
    checked_at: datetime
    source: str = "pisugar"
    device: PowerDeviceInfo = field(default_factory=PowerDeviceInfo)
    battery: BatteryState = field(default_factory=BatteryState)
    rtc: RTCState = field(default_factory=RTCState)
    shutdown: ShutdownState = field(default_factory=ShutdownState)
    error: str = ""


__all__ = [
    "BatteryState",
    "PendingShutdown",
    "PowerAlert",
    "PowerDeviceInfo",
    "PowerSnapshot",
    "RTCState",
    "ShutdownState",
]
