"""State-write helpers for the scaffold power integration."""

from __future__ import annotations

from typing import Any

from yoyopod_cli.pi.support.power_integration.models import PowerSnapshot


def snapshot_to_state_rows(snapshot: PowerSnapshot) -> list[tuple[str, Any, dict[str, Any]]]:
    """Map one power snapshot onto scaffold state-store rows."""

    attrs = {
        "checked_at": snapshot.checked_at.isoformat(),
        "source": snapshot.source,
        "error": snapshot.error,
    }
    battery_attrs = {
        **attrs,
        "charging": snapshot.battery.charging,
        "power_plugged": snapshot.battery.power_plugged,
        "temperature_celsius": snapshot.battery.temperature_celsius,
        "voltage_volts": snapshot.battery.voltage_volts,
    }
    return [
        ("power.available", snapshot.available, attrs),
        ("power.battery_percent", snapshot.battery.level_percent, battery_attrs),
        ("power.charging", snapshot.battery.charging, attrs),
        ("power.rtc_alarm_enabled", snapshot.rtc.alarm_enabled, attrs),
    ]


def apply_snapshot(app: Any, snapshot: PowerSnapshot) -> PowerSnapshot:
    """Write one power snapshot into the scaffold state store."""

    for entity, value, attrs in snapshot_to_state_rows(snapshot):
        app.states.set(entity, value, attrs)
    return snapshot
