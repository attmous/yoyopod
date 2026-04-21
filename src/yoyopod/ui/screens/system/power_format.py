"""Pure formatters for Setup screen rows and values."""

from __future__ import annotations

from datetime import datetime

if False:  # pragma: no cover - runtime import only for typing.
    from yoyopod.power.models import PowerSnapshot


def _format_battery(snapshot: "PowerSnapshot") -> str:
    """Format battery percentage with a compact suffix."""

    level = snapshot.battery.level_percent
    if level is None:
        return "Unknown"
    suffix = " chg" if snapshot.battery.charging else ""
    return f"{round(level)}%{suffix}"


def _format_charging(snapshot: "PowerSnapshot") -> str:
    """Format charging state."""

    charging = snapshot.battery.charging
    if charging is None:
        return "Unknown"
    return "Charging" if charging else "Idle"


def _format_external_power(snapshot: "PowerSnapshot") -> str:
    """Format whether USB/external power is present."""

    plugged = snapshot.battery.power_plugged
    if plugged is None:
        return "Unknown"
    return "Plugged" if plugged else "Battery"


def _format_voltage(snapshot: "PowerSnapshot") -> str:
    """Format voltage with optional temperature hint."""

    voltage = snapshot.battery.voltage_volts
    temperature = snapshot.battery.temperature_celsius
    if voltage is None and temperature is None:
        return "Unknown"
    if voltage is None:
        return f"{temperature:.1f} C"
    if temperature is None:
        return f"{voltage:.2f} V"
    return f"{voltage:.2f}V {temperature:.0f}C"


def _format_alarm(snapshot: "PowerSnapshot") -> str:
    """Format the current RTC alarm state."""

    if snapshot.rtc.alarm_enabled is not True:
        return "Off"
    if snapshot.rtc.alarm_time is None:
        return "On"
    return snapshot.rtc.alarm_time.strftime("%H:%M")


def _format_datetime(value: datetime | None) -> str:
    """Format one datetime value for compact screen use."""

    if value is None:
        return "Unknown"
    return value.strftime("%m-%d %H:%M")


def _format_duration_short(value: object) -> str:
    """Format short durations like 95 seconds -> 1m35s."""

    if value is None:
        return "0s"
    total_seconds = max(0, int(float(value)))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours > 0:
        return f"{hours}h{minutes:02d}m"
    if minutes > 0:
        return f"{minutes}m{seconds:02d}s"
    return f"{seconds}s"


def _format_percent(value: object) -> str:
    """Format a percentage-like value for screen use."""

    if value is None:
        return "--"
    return f"{int(round(float(value)))}%"


def _format_watchdog(status: dict[str, object]) -> str:
    """Format the current watchdog state."""

    if not status.get("watchdog_enabled"):
        return "Off"
    if status.get("watchdog_feed_suppressed"):
        return "Paused"
    if status.get("watchdog_active"):
        return "Active"
    return "Ready"


def _format_screen_state(status: dict[str, object]) -> str:
    """Format current display-awake plus cumulative screen-on time."""

    state = "Awake" if status.get("screen_awake") else "Sleep"
    screen_on = _format_duration_short(status.get("screen_on_seconds"))
    return f"{state} {screen_on}"


def _truncate(text: str, max_length: int) -> str:
    """Truncate strings that would overflow narrow labels."""

    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."
