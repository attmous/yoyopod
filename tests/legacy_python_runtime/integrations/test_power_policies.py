"""Tests for low-battery warning and graceful shutdown policy logic."""

from __future__ import annotations

from datetime import datetime

from yoyopod.config.models import PowerConfig
from yoyopod.integrations.power.events import (
    GracefulShutdownCancelled,
    GracefulShutdownRequested,
    LowBatteryWarningRaised,
)
from yoyopod.integrations.power import BatteryState, PowerSnapshot
from yoyopod.integrations.power.policies import PowerSafetyPolicy


def _snapshot(
    *,
    available: bool = True,
    battery_percent: float | None = None,
    charging: bool | None = None,
    power_plugged: bool | None = None,
) -> PowerSnapshot:
    return PowerSnapshot(
        available=available,
        checked_at=datetime(2026, 4, 4, 12, 0, 0),
        battery=BatteryState(
            level_percent=battery_percent,
            charging=charging,
            power_plugged=power_plugged,
        ),
    )


def test_power_policy_raises_low_battery_warning_with_cooldown() -> None:
    """Warnings should be rate-limited while battery stays below the warning threshold."""

    policy = PowerSafetyPolicy(
        PowerConfig(
            low_battery_warning_percent=20.0,
            low_battery_warning_cooldown_seconds=300.0,
            critical_shutdown_percent=10.0,
        )
    )
    snapshot = _snapshot(battery_percent=15.0, charging=False, power_plugged=False)

    first_events = policy.evaluate(snapshot, now=100.0)
    second_events = policy.evaluate(snapshot, now=200.0)
    third_events = policy.evaluate(snapshot, now=401.0)

    assert len(first_events) == 1
    assert isinstance(first_events[0], LowBatteryWarningRaised)
    assert first_events[0].battery_percent == 15.0
    assert second_events == []
    assert len(third_events) == 1
    assert isinstance(third_events[0], LowBatteryWarningRaised)


def test_power_policy_requests_shutdown_once_at_critical_threshold() -> None:
    """Crossing the critical threshold should emit one shutdown request until reset."""

    policy = PowerSafetyPolicy(
        PowerConfig(
            low_battery_warning_percent=20.0,
            critical_shutdown_percent=10.0,
            shutdown_delay_seconds=15.0,
        )
    )
    snapshot = _snapshot(battery_percent=9.0, charging=False, power_plugged=False)

    first_events = policy.evaluate(snapshot, now=10.0)
    second_events = policy.evaluate(snapshot, now=20.0)

    assert len(first_events) == 1
    assert isinstance(first_events[0], GracefulShutdownRequested)
    assert first_events[0].delay_seconds == 15.0
    assert second_events == []


def test_power_policy_cancels_pending_shutdown_when_external_power_returns() -> None:
    """Restoring external power should cancel a pending critical-battery shutdown."""

    policy = PowerSafetyPolicy(PowerConfig(critical_shutdown_percent=10.0))

    critical_snapshot = _snapshot(battery_percent=8.5, charging=False, power_plugged=False)
    restored_snapshot = _snapshot(battery_percent=8.5, charging=True, power_plugged=True)

    request_events = policy.evaluate(critical_snapshot, now=50.0)
    cancel_events = policy.evaluate(restored_snapshot, now=55.0)

    assert len(request_events) == 1
    assert isinstance(request_events[0], GracefulShutdownRequested)
    assert len(cancel_events) == 1
    assert isinstance(cancel_events[0], GracefulShutdownCancelled)
    assert cancel_events[0].reason == "external_power_restored"
