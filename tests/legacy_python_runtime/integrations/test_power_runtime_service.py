"""Tests for the canonical power runtime service helpers."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from yoyopod.integrations.power import BatteryState, PowerRuntimeService, PowerSnapshot


def test_publish_snapshot_calls_power_handlers_directly() -> None:
    """Runtime power refreshes should apply snapshots on main-thread delivery."""

    snapshot = PowerSnapshot(
        available=True,
        checked_at=datetime(2026, 4, 21, 10, 0, 0),
        battery=BatteryState(level_percent=82.0),
    )
    runtime = SimpleNamespace(
        power_snapshot=None,
        set_power_snapshot=lambda new_snapshot: setattr(runtime, "power_snapshot", new_snapshot),
        set_power_available=lambda available: setattr(runtime, "power_available", available),
    )
    context = SimpleNamespace(update_power_status=lambda _snapshot: None)
    app = SimpleNamespace(
        power_manager=SimpleNamespace(get_snapshot=lambda: snapshot),
        _power_available=None,
        app_state_runtime=runtime,
        context=context,
        screen_manager=None,
        cloud_manager=None,
        bus=SimpleNamespace(publish=lambda _event: None),
    )

    PowerRuntimeService(app)._publish_snapshot(snapshot=snapshot)

    assert runtime.power_snapshot == snapshot
    assert app._power_available is True


def test_publish_snapshot_skips_duplicate_runtime_state() -> None:
    """Power refresh publishing should no-op when runtime and availability already match."""

    snapshot = PowerSnapshot(
        available=False,
        checked_at=datetime(2026, 4, 21, 10, 5, 0),
        battery=BatteryState(level_percent=19.0),
        error="unavailable",
    )
    runtime = SimpleNamespace(
        power_snapshot=snapshot,
        set_power_snapshot=lambda new_snapshot: setattr(runtime, "power_snapshot", new_snapshot),
        set_power_available=lambda available: setattr(runtime, "power_available", available),
    )
    app = SimpleNamespace(
        power_manager=SimpleNamespace(get_snapshot=lambda: snapshot),
        _power_available=False,
        app_state_runtime=runtime,
        context=SimpleNamespace(update_power_status=lambda _snapshot: None),
        screen_manager=None,
        cloud_manager=None,
        bus=SimpleNamespace(publish=lambda _event: None),
    )

    PowerRuntimeService(app)._publish_snapshot(snapshot=snapshot)

    assert runtime.power_snapshot == snapshot
    assert app._power_available is False


def test_publish_snapshot_noops_without_runtime_state() -> None:
    """Power publishing should safely no-op until the runtime state exists."""

    snapshot = PowerSnapshot(
        available=True,
        checked_at=datetime(2026, 4, 21, 10, 10, 0),
        battery=BatteryState(level_percent=60.0),
    )
    app = SimpleNamespace(
        power_manager=SimpleNamespace(get_snapshot=lambda: snapshot),
        _power_available=None,
        app_state_runtime=None,
        context=SimpleNamespace(update_power_status=lambda _snapshot: None),
        screen_manager=None,
        cloud_manager=None,
        bus=SimpleNamespace(publish=lambda _event: None),
    )

    PowerRuntimeService(app)._publish_snapshot(snapshot=snapshot)

    assert app._power_available is None


def test_publish_snapshot_skips_redundant_power_route_refresh_for_unchanged_signature() -> None:
    """Setup should not redraw when only hidden snapshot fields changed on the power route."""

    previous_snapshot = PowerSnapshot(
        available=False,
        checked_at=datetime(2026, 4, 21, 10, 10, 0),
        battery=BatteryState(level_percent=19.0),
        error="I2C not connected",
    )
    refreshed_snapshot = PowerSnapshot(
        available=False,
        checked_at=datetime(2026, 4, 21, 10, 10, 30),
        battery=BatteryState(level_percent=19.0),
        error="I2C not connected",
    )
    runtime = SimpleNamespace(
        power_snapshot=previous_snapshot,
        set_power_snapshot=lambda new_snapshot: setattr(runtime, "power_snapshot", new_snapshot),
        set_power_available=lambda available: setattr(runtime, "power_available", available),
    )
    refresh_calls: list[str] = []
    app = SimpleNamespace(
        power_manager=SimpleNamespace(get_snapshot=lambda: refreshed_snapshot),
        _power_available=False,
        app_state_runtime=runtime,
        context=SimpleNamespace(update_power_status=lambda _snapshot: None),
        screen_manager=SimpleNamespace(
            get_current_screen=lambda: SimpleNamespace(route_name="power"),
            refresh_current_screen=lambda: refresh_calls.append("refresh"),
        ),
        cloud_manager=None,
        bus=SimpleNamespace(publish=lambda _event: None),
    )

    PowerRuntimeService(app)._publish_snapshot(snapshot=refreshed_snapshot)

    assert runtime.power_snapshot == refreshed_snapshot
    assert refresh_calls == []


def test_publish_cached_snapshot_requires_existing_runtime_snapshot() -> None:
    """Forced refresh fallback should only publish cached power after one real snapshot exists."""

    snapshot = PowerSnapshot(
        available=True,
        checked_at=datetime(2026, 4, 21, 10, 15, 0),
        battery=BatteryState(level_percent=88.0),
    )
    runtime = SimpleNamespace(
        power_snapshot=None,
        set_power_snapshot=lambda new_snapshot: setattr(runtime, "power_snapshot", new_snapshot),
        set_power_available=lambda available: setattr(runtime, "power_available", available),
    )
    app = SimpleNamespace(
        power_manager=SimpleNamespace(get_snapshot=lambda: snapshot),
        _power_available=None,
        app_state_runtime=runtime,
        context=SimpleNamespace(update_power_status=lambda _snapshot: None),
        screen_manager=None,
        cloud_manager=None,
        bus=SimpleNamespace(publish=lambda _event: None),
    )
    service = PowerRuntimeService(app)

    service._publish_cached_snapshot_if_ready()
    assert runtime.power_snapshot is None

    app.app_state_runtime.power_snapshot = snapshot
    service._publish_cached_snapshot_if_ready()

    assert runtime.power_snapshot == snapshot
    assert app._power_available is True
