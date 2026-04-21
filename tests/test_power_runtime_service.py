"""Tests for the runtime-owned power service coordination helpers."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from yoyopod.integrations.power import BatteryState, PowerSnapshot
from yoyopod.runtime.power_service import PowerRuntimeService


class _FakePowerCoordinator:
    """Capture direct power coordinator handler calls."""

    def __init__(self) -> None:
        self.snapshot_calls: list[PowerSnapshot] = []
        self.availability_calls: list[tuple[bool, str]] = []

    def handle_snapshot_updated(self, snapshot: PowerSnapshot) -> None:
        self.snapshot_calls.append(snapshot)

    def handle_availability_change(self, available: bool, reason: str) -> None:
        self.availability_calls.append((available, reason))


def test_publish_snapshot_calls_power_handlers_directly() -> None:
    """Runtime power refreshes should call coordinator handlers directly on main-thread delivery."""

    snapshot = PowerSnapshot(
        available=True,
        checked_at=datetime(2026, 4, 21, 10, 0, 0),
        battery=BatteryState(level_percent=82.0),
    )
    coordinator = _FakePowerCoordinator()
    app = SimpleNamespace(
        power_manager=SimpleNamespace(get_snapshot=lambda: snapshot),
        _power_available=None,
        coordinator_runtime=SimpleNamespace(power_snapshot=None),
        power_coordinator=coordinator,
    )

    PowerRuntimeService(app)._publish_snapshot(snapshot=snapshot)

    assert coordinator.snapshot_calls == [snapshot]
    assert coordinator.availability_calls == [(True, "ready")]


def test_publish_snapshot_skips_duplicate_runtime_state() -> None:
    """Power refresh publishing should no-op when runtime and availability already match."""

    snapshot = PowerSnapshot(
        available=False,
        checked_at=datetime(2026, 4, 21, 10, 5, 0),
        battery=BatteryState(level_percent=19.0),
        error="unavailable",
    )
    coordinator = _FakePowerCoordinator()
    app = SimpleNamespace(
        power_manager=SimpleNamespace(get_snapshot=lambda: snapshot),
        _power_available=False,
        coordinator_runtime=SimpleNamespace(power_snapshot=snapshot),
        power_coordinator=coordinator,
    )

    PowerRuntimeService(app)._publish_snapshot(snapshot=snapshot)

    assert coordinator.snapshot_calls == []
    assert coordinator.availability_calls == []


def test_publish_snapshot_noops_without_runtime_or_power_owner() -> None:
    """Power publishing should safely no-op until the runtime owners exist."""

    snapshot = PowerSnapshot(
        available=True,
        checked_at=datetime(2026, 4, 21, 10, 10, 0),
        battery=BatteryState(level_percent=60.0),
    )
    app = SimpleNamespace(
        power_manager=SimpleNamespace(get_snapshot=lambda: snapshot),
        _power_available=None,
        coordinator_runtime=None,
        power_coordinator=None,
    )

    PowerRuntimeService(app)._publish_snapshot(snapshot=snapshot)

    assert app._power_available is None


def test_publish_cached_snapshot_requires_existing_runtime_snapshot() -> None:
    """Forced refresh fallback should only publish cached power after one real snapshot exists."""

    snapshot = PowerSnapshot(
        available=True,
        checked_at=datetime(2026, 4, 21, 10, 15, 0),
        battery=BatteryState(level_percent=88.0),
    )
    coordinator = _FakePowerCoordinator()
    app = SimpleNamespace(
        power_manager=SimpleNamespace(get_snapshot=lambda: snapshot),
        _power_available=None,
        coordinator_runtime=SimpleNamespace(power_snapshot=None),
        power_coordinator=coordinator,
    )
    service = PowerRuntimeService(app)

    service._publish_cached_snapshot_if_ready()
    assert coordinator.snapshot_calls == []

    app.coordinator_runtime.power_snapshot = snapshot
    service._publish_cached_snapshot_if_ready()

    assert coordinator.snapshot_calls == [snapshot]
    assert coordinator.availability_calls == [(True, "ready")]
