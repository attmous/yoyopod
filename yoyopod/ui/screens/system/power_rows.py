"""Setup screen row and page builders."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yoyopod.core.hardware import format_device_label

from yoyopod.ui.screens.system.power_format import (
    _format_alarm,
    _format_battery,
    _format_charging,
    _format_datetime,
    _format_duration_short,
    _format_external_power,
    _format_percent,
    _format_screen_state,
    _format_watchdog,
    _format_voltage,
    _truncate,
)

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.integrations.power.models import PowerSnapshot


@dataclass(frozen=True, slots=True)
class PowerPage:
    """One setup page made of compact rows."""

    title: str
    rows: list[tuple[str, str]]
    interactive: bool = False


def _build_battery_rows(*, snapshot: "PowerSnapshot | None") -> list[tuple[str, str]]:
    """Build the power-focused page."""

    if snapshot is None:
        return [
            ("Source", "Unavailable"),
            ("Battery", "Unknown"),
            ("Charging", "Unknown"),
            ("RTC", "Unknown"),
            ("Alarm", "Unknown"),
        ]

    if not snapshot.available:
        error = snapshot.error or "Unavailable"
        return [
            ("Source", snapshot.source),
            ("Model", snapshot.device.model or "Unknown"),
            ("Status", "Offline"),
            ("Reason", _truncate(error, 18)),
            ("RTC", _format_datetime(snapshot.rtc.time)),
            ("Alarm", _format_alarm(snapshot)),
        ]

    return [
        ("Model", snapshot.device.model or "Unknown"),
        ("Battery", _format_battery(snapshot)),
        ("Charging", _format_charging(snapshot)),
        ("External", _format_external_power(snapshot)),
        ("Voltage", _format_voltage(snapshot)),
        ("RTC", _format_datetime(snapshot.rtc.time)),
        ("Alarm", _format_alarm(snapshot)),
    ]


def _build_runtime_rows(
    *,
    snapshot: "PowerSnapshot | None",
    status: dict[str, object],
) -> list[tuple[str, str]]:
    """Build the care/runtime page."""

    warning_percent = _format_percent(status.get("warning_threshold_percent"))
    critical_percent = _format_percent(status.get("critical_shutdown_percent"))
    delay_seconds = _format_duration_short(status.get("shutdown_delay_seconds"))
    shutdown_value = "Ready"
    if status.get("shutdown_pending"):
        shutdown_value = f"In {_format_duration_short(status.get('shutdown_in_seconds'))}"
    warn_crit_value = f"{warning_percent}/{critical_percent}"
    if snapshot is not None and snapshot.shutdown.safe_shutdown_level_percent is not None:
        safe_shutdown_percent = _format_percent(snapshot.shutdown.safe_shutdown_level_percent)
        warn_crit_value = f"{warning_percent}/{safe_shutdown_percent}"

    return [
        ("Uptime", _format_duration_short(status.get("app_uptime_seconds"))),
        ("Screen", _format_screen_state(status)),
        ("Idle", _format_duration_short(status.get("screen_idle_seconds"))),
        ("Timeout", _format_duration_short(status.get("screen_timeout_seconds"))),
        ("Warn/Crit", warn_crit_value),
        (
            "Shutdown",
            shutdown_value if delay_seconds == "0s" else f"{shutdown_value} ({delay_seconds})",
        ),
        ("Watchdog", _format_watchdog(status)),
    ]


def _build_voice_rows(
    *,
    context: "AppContext | None" = None,
    summary_mode: bool = False,
) -> list[tuple[str, str]]:
    """Build the voice-related settings page."""

    if context is None:
        rows = [
            ("Voice Cmds", "Unknown"),
            ("AI Requests", "Unknown"),
            ("Screen Read", "Unknown"),
            ("Speaker", "Auto"),
            ("Mic Device", "Auto"),
            ("Mic", "Unknown"),
            ("Volume", "--"),
        ]
        if summary_mode:
            return [
                ("Voice Cmds", "Unknown"),
                ("AI Requests", "Unknown"),
                ("Screen Read", "Unknown"),
                ("Mic", "Unknown"),
                ("Volume", "--"),
            ]
        return rows

    voice = context.voice
    volume_level = context.output_volume_level(voice.output_volume)
    rows = [
        ("Voice Cmds", "On" if voice.commands_enabled else "Off"),
        ("AI Requests", "On" if voice.ai_requests_enabled else "Off"),
        ("Screen Read", "On" if voice.screen_read_enabled else "Off"),
        ("Speaker", format_device_label(voice.speaker_device_id)),
        ("Mic Device", format_device_label(voice.capture_device_id)),
        ("Mic", "Muted" if voice.mic_muted else "Live"),
        ("Volume", f"{volume_level}/10"),
    ]

    if summary_mode:
        return [
            ("Voice Cmds", rows[0][1]),
            ("AI Requests", rows[1][1]),
            ("Screen Read", rows[2][1]),
            ("Mic", rows[5][1]),
            ("Volume", rows[6][1]),
        ]
    return rows


def _row_capacity_for_page(page: PowerPage, *, is_portrait: bool) -> int:
    """Return how many rows the current display/layout can safely show."""

    if is_portrait and not page.interactive:
        return 5
    return 4
