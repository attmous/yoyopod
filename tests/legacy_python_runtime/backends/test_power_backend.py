"""Tests for the PiSugar power backend foundation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from yoyopod.backends.power import PiSugarBackend, PowerTransportError
from yoyopod.config import PowerConfig


class FakeTransport:
    """Simple command/response transport double for PiSugar tests."""

    def __init__(self, responses: dict[str, str], failures: set[str] | None = None) -> None:
        self.responses = responses
        self.failures = failures or set()
        self.commands: list[str] = []

    def send_command(self, command: str) -> str:
        self.commands.append(command)
        if command in self.failures:
            raise PowerTransportError(f"simulated failure for {command}")
        if command not in self.responses:
            raise PowerTransportError(f"unexpected command: {command}")
        return self.responses[command]


def test_pisugar_backend_parses_snapshot_from_documented_commands() -> None:
    """The backend should coerce PiSugar string responses into typed snapshot fields."""

    checked_at = datetime(2026, 4, 4, 12, 0, tzinfo=timezone.utc)
    backend = PiSugarBackend(
        PowerConfig(),
        transport=FakeTransport(
            {
                "get model": "model: PiSugar 3",
                "get firmware_version": "firmware_version: 1.0.23",
                "get battery": "battery: 87.5",
                "get battery_v": "battery_v: 4.07",
                "get battery_charging": "battery_charging: true",
                "get battery_power_plugged": "battery_power_plugged: false",
                "get battery_allow_charging": "battery_allow_charging: true",
                "get battery_output_enabled": "battery_output_enabled: true",
                "get temperature": "temperature: 31.4",
                "get rtc_time": "rtc_time: 2026-04-04T11:59:00+00:00",
                "get rtc_alarm_enabled": "rtc_alarm_enabled: false",
                "get rtc_alarm_time": "rtc_alarm_time: 2026-04-05T07:30:00+00:00",
                "get alarm_repeat": "alarm_repeat: 127",
                "get rtc_adjust_ppm": "rtc_adjust_ppm: 0.0",
                "get safe_shutdown_level": "safe_shutdown_level: 12.0",
                "get safe_shutdown_delay": "safe_shutdown_delay: 30",
            }
        ),
        now_provider=lambda: checked_at,
    )

    snapshot = backend.get_snapshot()

    assert snapshot.available is True
    assert snapshot.checked_at == checked_at
    assert snapshot.device.model == "PiSugar 3"
    assert snapshot.device.firmware_version == "1.0.23"
    assert snapshot.battery.level_percent == 87.5
    assert snapshot.battery.voltage_volts == 4.07
    assert snapshot.battery.charging is True
    assert snapshot.battery.power_plugged is False
    assert snapshot.rtc.time == datetime(2026, 4, 4, 11, 59, tzinfo=timezone.utc)
    assert snapshot.rtc.alarm_time == datetime(2026, 4, 5, 7, 30, tzinfo=timezone.utc)
    assert snapshot.shutdown.safe_shutdown_level_percent == 12.0
    assert snapshot.shutdown.safe_shutdown_delay_seconds == 30
    assert snapshot.error == ""


def test_pisugar_backend_reports_partial_failures_without_losing_availability() -> None:
    """Optional command failures should be surfaced in the snapshot error string."""

    backend = PiSugarBackend(
        PowerConfig(),
        transport=FakeTransport(
            {
                "get model": "PiSugar 3",
                "get firmware_version": "1.0.23",
                "get battery": "91",
                "get battery_v": "4.11",
                "get battery_charging": "false",
                "get battery_power_plugged": "true",
                "get battery_allow_charging": "true",
                "get battery_output_enabled": "true",
                "get rtc_time": "2026-04-04T12:00:00+00:00",
                "get rtc_alarm_enabled": "false",
                "get rtc_alarm_time": "2026-04-05T07:30:00+00:00",
                "get alarm_repeat": "127",
                "get rtc_adjust_ppm": "0.0",
                "get safe_shutdown_level": "15.0",
                "get safe_shutdown_delay": "45",
            },
            failures={"get temperature"},
        ),
    )

    snapshot = backend.get_snapshot()

    assert snapshot.available is True
    assert snapshot.battery.temperature_celsius is None
    assert "get temperature" in snapshot.error


def test_pisugar_backend_marks_snapshot_unavailable_when_transport_is_down() -> None:
    """If every command fails, the snapshot should report the backend as unavailable."""

    backend = PiSugarBackend(
        PowerConfig(),
        transport=FakeTransport({}, failures={"get model"}),
    )

    snapshot = backend.get_snapshot()

    assert snapshot.available is False
    assert "get model" in snapshot.error


def test_pisugar_backend_marks_snapshot_unavailable_when_only_identity_queries_work() -> None:
    """Model-only responses should not count as a usable power telemetry snapshot."""

    backend = PiSugarBackend(
        PowerConfig(),
        transport=FakeTransport(
            {
                "get model": "PiSugar 3",
                "get firmware_version": "I2C not connected",
                "get battery": "I2C not connected",
                "get battery_v": "I2C not connected",
                "get battery_charging": "I2C not connected",
                "get battery_power_plugged": "I2C not connected",
                "get battery_allow_charging": "I2C not connected",
                "get battery_output_enabled": "I2C not connected",
                "get temperature": "I2C not connected",
                "get rtc_time": "I2C not connected",
                "get rtc_alarm_enabled": "I2C not connected",
                "get rtc_alarm_time": "I2C not connected",
                "get alarm_repeat": "0",
                "get rtc_adjust_ppm": "0.0",
                "get safe_shutdown_level": "0.0",
                "get safe_shutdown_delay": "0",
            }
        ),
    )

    snapshot = backend.get_snapshot()

    assert backend.probe() is False
    assert snapshot.available is False
    assert snapshot.device.model == "PiSugar 3"
    assert "get battery" in snapshot.error


def test_pisugar_probe_returns_false_when_backend_is_disabled() -> None:
    """Disabled power config should short-circuit probe attempts."""

    backend = PiSugarBackend(
        PowerConfig(enabled=False),
        transport=FakeTransport({"get model": "PiSugar 3"}),
    )

    assert backend.probe() is False


def test_pisugar_backend_issues_documented_rtc_control_commands() -> None:
    """RTC sync and alarm helpers should use the official PiSugar command names."""

    transport = FakeTransport(
        {
            "rtc_pi2rtc": "done: rtc_pi2rtc",
            "rtc_rtc2pi": "done: rtc_rtc2pi",
            "rtc_alarm_set 2026-04-06T07:30:00+00:00 31": "done: rtc_alarm_set",
            "rtc_alarm_disable": "done: rtc_alarm_disable",
        }
    )
    backend = PiSugarBackend(PowerConfig(), transport=transport)

    backend.sync_time_to_rtc()
    backend.sync_time_from_rtc()
    backend.set_rtc_alarm(datetime(2026, 4, 6, 7, 30, tzinfo=timezone.utc), repeat_mask=31)
    backend.disable_rtc_alarm()

    assert transport.commands == [
        "rtc_pi2rtc",
        "rtc_rtc2pi",
        "rtc_alarm_set 2026-04-06T07:30:00+00:00 31",
        "rtc_alarm_disable",
    ]
