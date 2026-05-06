"""Tests for the scaffold power integration."""

from __future__ import annotations

from datetime import datetime

from yoyopod.config.models import PowerConfig
from tests.fixtures.app import build_test_app, drain_all
from yoyopod.integrations.power import BatteryState, PowerSnapshot, setup, teardown
from yoyopod.integrations.power.commands import SetRtcAlarmCommand
from yoyopod.integrations.power.handlers import snapshot_to_state_rows
from yoyopod.integrations.power.poller import PowerPoller


class FakePowerBackend:
    """Minimal power backend double for scaffold integration tests."""

    def __init__(self, snapshot: PowerSnapshot) -> None:
        self.snapshot = snapshot
        self.sync_to_rtc_calls = 0
        self.sync_from_rtc_calls = 0
        self.set_alarm_calls: list[tuple[datetime, int]] = []
        self.disable_alarm_calls = 0

    def get_snapshot(self) -> PowerSnapshot:
        return self.snapshot

    def sync_time_to_rtc(self) -> None:
        self.sync_to_rtc_calls += 1

    def sync_time_from_rtc(self) -> None:
        self.sync_from_rtc_calls += 1

    def set_rtc_alarm(self, when: datetime, repeat_mask: int = 127) -> None:
        self.set_alarm_calls.append((when, repeat_mask))

    def disable_rtc_alarm(self) -> None:
        self.disable_alarm_calls += 1


def test_snapshot_to_state_rows_covers_visible_power_fields() -> None:
    snapshot = _sample_snapshot()

    rows = snapshot_to_state_rows(snapshot)

    assert [row[0] for row in rows] == [
        "power.available",
        "power.battery_percent",
        "power.charging",
        "power.rtc_alarm_enabled",
    ]


def test_power_poller_schedules_snapshot_handler_on_main_thread() -> None:
    app = build_test_app()
    seen: list[PowerSnapshot] = []
    backend = FakePowerBackend(_sample_snapshot())
    poller = PowerPoller(
        backend=backend,
        scheduler=app.scheduler,
        on_snapshot=seen.append,
        poll_interval_seconds=1.0,
    )

    snapshot = poller.poll_once()
    assert snapshot is backend.snapshot
    assert seen == []

    drain_all(app)
    assert seen == [backend.snapshot]


def test_power_setup_registers_services_and_updates_states() -> None:
    app = build_test_app()
    backend = FakePowerBackend(_sample_snapshot())

    integration = setup(
        app,
        config=PowerConfig(enabled=True),
        backend=backend,
        poll_interval_seconds=1.0,
    )

    refreshed = app.services.call("power", "refresh_snapshot")
    drain_all(app)

    assert refreshed == backend.snapshot
    assert integration is app.integrations["power"]
    assert app.states.get_value("power.available") is True
    assert app.states.get_value("power.battery_percent") == 87.0

    alarm_time = datetime(2026, 4, 21, 10, 0, 0)
    app.services.call("power", "set_rtc_alarm", SetRtcAlarmCommand(when=alarm_time, repeat_mask=3))
    assert backend.set_alarm_calls == [(alarm_time, 3)]

    app.services.call("power", "sync_time_to_rtc")
    app.services.call("power", "sync_time_from_rtc")
    app.services.call("power", "disable_rtc_alarm")
    assert backend.sync_to_rtc_calls == 1
    assert backend.sync_from_rtc_calls == 1
    assert backend.disable_alarm_calls == 1

    teardown(app)
    assert "power" not in app.integrations


def _sample_snapshot() -> PowerSnapshot:
    return PowerSnapshot(
        available=True,
        checked_at=datetime(2026, 4, 21, 9, 30, 0),
        battery=BatteryState(
            level_percent=87.0,
            charging=False,
            power_plugged=False,
            temperature_celsius=31.5,
            voltage_volts=4.08,
        ),
    )
