"""Tests for the user-facing power status screen."""

from __future__ import annotations

from datetime import datetime

from yoyopy.app_context import AppContext
from yoyopy.power import BatteryState, PowerDeviceInfo, PowerSnapshot, RTCState, ShutdownState
from yoyopy.ui.display import Display
from yoyopy.ui.screens.navigation.power import PowerScreen


class StubPowerManager:
    """Minimal power manager double for screen tests."""

    def __init__(self, snapshot: PowerSnapshot) -> None:
        self._snapshot = snapshot

    def get_snapshot(self) -> PowerSnapshot:
        return self._snapshot


def _snapshot() -> PowerSnapshot:
    return PowerSnapshot(
        available=True,
        checked_at=datetime(2026, 4, 5, 12, 0, 0),
        device=PowerDeviceInfo(model="PiSugar 3"),
        battery=BatteryState(
            level_percent=55.2,
            voltage_volts=3.62,
            charging=True,
            power_plugged=True,
            temperature_celsius=29.5,
        ),
        rtc=RTCState(
            time=datetime(2026, 4, 5, 13, 30, 0),
            alarm_enabled=True,
            alarm_time=datetime(2026, 4, 6, 7, 30, 0),
        ),
        shutdown=ShutdownState(
            safe_shutdown_level_percent=10.0,
            safe_shutdown_delay_seconds=15,
        ),
    )


def test_power_screen_builds_battery_and_runtime_pages() -> None:
    """The power screen should expose both telemetry and runtime/safety pages."""
    display = Display(simulate=True)
    try:
        status = {
            "app_uptime_seconds": 3661,
            "screen_on_seconds": 901,
            "screen_idle_seconds": 32,
            "screen_awake": True,
            "screen_timeout_seconds": 30.0,
            "warning_threshold_percent": 20.0,
            "critical_shutdown_percent": 10.0,
            "shutdown_delay_seconds": 15.0,
            "shutdown_pending": False,
            "watchdog_enabled": True,
            "watchdog_active": True,
            "watchdog_feed_suppressed": False,
        }
        screen = PowerScreen(
            display,
            AppContext(),
            power_manager=StubPowerManager(_snapshot()),
            status_provider=lambda: status,
        )

        pages = screen.build_pages(snapshot=screen.power_manager.get_snapshot(), status=status)

        assert pages[0].title == "Power"
        assert ("Model", "PiSugar 3") in pages[0].rows
        assert ("Battery", "55% chg") in pages[0].rows
        assert ("Alarm", "07:30") in pages[0].rows
        assert pages[1].title == "Care"
        assert ("Uptime", "1h01m") in pages[1].rows
        assert ("Watchdog", "Active") in pages[1].rows
    finally:
        display.cleanup()


def test_power_screen_formats_unavailable_snapshot() -> None:
    """Unavailable power backends should still render a readable status page."""
    display = Display(simulate=True)
    try:
        snapshot = PowerSnapshot(
            available=False,
            checked_at=datetime(2026, 4, 5, 12, 0, 0),
            error="I2C not connected",
        )
        screen = PowerScreen(
            display,
            AppContext(),
            power_manager=StubPowerManager(snapshot),
            status_provider=lambda: {},
        )

        pages = screen.build_pages(snapshot=snapshot, status={})

        assert ("Status", "Offline") in pages[0].rows
        assert ("Reason", "I2C not connected") in pages[0].rows
        assert ("Watchdog", "Off") in pages[1].rows
    finally:
        display.cleanup()
