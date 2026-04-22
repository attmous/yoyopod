"""Handlers for the scaffold cloud integration."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from typing import Any, Callable

from yoyopod.core.events import StateChangedEvent
from yoyopod.integrations.cloud.commands import PublishTelemetryCommand, SyncNowCommand

_TELEMETRY_ENTITIES = {
    "call.state",
    "location.fix",
    "music.state",
    "network.cellular_registered",
    "network.ppp_up",
    "network.signal_bars",
    "power.battery_percent",
    "power.charging",
}


def seed_cloud_state(app: Any, *, reason: str = "starting") -> None:
    """Seed the scaffold cloud connectivity state."""

    app.states.set(
        "cloud.mqtt_connected",
        False,
        {"reason": reason, "last_sync_at": None},
    )


def apply_mqtt_status_to_state(
    app: Any,
    *,
    connected: bool,
    reason: str = "",
    now: float | None = None,
) -> None:
    """Mirror MQTT transport connectivity into scaffold state."""

    current = app.states.get("cloud.mqtt_connected")
    last_sync_at = None if current is None else current.attrs.get("last_sync_at")
    app.states.set(
        "cloud.mqtt_connected",
        bool(connected),
        {
            "reason": reason,
            "last_sync_at": last_sync_at if now is None else now,
        },
    )


def record_sync_success(app: Any, *, now: float) -> None:
    """Update the cloud state attrs after one successful sync."""

    current = app.states.get("cloud.mqtt_connected")
    connected = False if current is None else bool(current.value)
    reason = "" if current is None else str(current.attrs.get("reason", ""))
    app.states.set(
        "cloud.mqtt_connected",
        connected,
        {
            "reason": reason,
            "last_sync_at": now,
        },
    )


def build_state_forwarder(
    app: Any,
    mqtt_client: Any,
    *,
    is_active: Callable[[], bool],
) -> Callable[[StateChangedEvent], None]:
    """Return a state-change subscriber that forwards selected entities to MQTT."""

    def on_state_changed(event: StateChangedEvent) -> None:
        if not is_active():
            return
        if event.entity not in _TELEMETRY_ENTITIES:
            return
        if not app.states.get_value("cloud.mqtt_connected", False):
            return
        payload = {
            "entity": event.entity,
            "value": _serialize_value(event.new),
            "attrs": _serialize_value(event.attrs),
            "ts": event.last_changed_at,
        }
        mqtt_client.publish(
            f"yoyopod/telemetry/{event.entity}",
            json.dumps(payload, sort_keys=True),
            qos=0,
        )

    return on_state_changed


def sync_now(app: Any, integration: Any, command: SyncNowCommand, *, now: float) -> Any:
    """Invoke the injected sync handler and mirror success into scaffold state."""

    if not isinstance(command, SyncNowCommand):
        raise TypeError("cloud.sync_now expects SyncNowCommand")
    if integration.sync_now_handler is None:
        return False
    result = integration.sync_now_handler()
    record_sync_success(app, now=now)
    return result


def publish_telemetry(integration: Any, command: PublishTelemetryCommand) -> bool:
    """Publish one explicit telemetry payload through the MQTT client."""

    if not isinstance(command, PublishTelemetryCommand):
        raise TypeError("cloud.publish_telemetry expects PublishTelemetryCommand")
    if not integration.active:
        return False
    topic_suffix = command.topic_suffix.strip().strip("/")
    if not topic_suffix:
        return False
    return bool(
        integration.mqtt_client.publish(
            f"yoyopod/telemetry/{topic_suffix}",
            json.dumps(_serialize_value(command.payload), sort_keys=True),
            qos=max(0, int(command.qos)),
        )
    )


def _serialize_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if is_dataclass(value):
        return {key: _serialize_value(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _serialize_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize_value(item) for item in value]
    if hasattr(value, "__dict__"):
        return {
            str(key): _serialize_value(item)
            for key, item in vars(value).items()
            if not key.startswith("_")
        }
    return str(value)
