"""Tests for the scaffold cloud integration."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field

from tests.fixtures.app import build_test_app, drain_all
from yoyopod.integrations.cloud import (
    PublishTelemetryCommand,
    SyncNowCommand,
    setup,
    teardown,
)


@dataclass(slots=True)
class FakeMqttClient:
    """Small MQTT double with explicit connect and disconnect hooks."""

    started: bool = False
    stopped: bool = False
    is_connected: bool = False
    published: list[tuple[str, str, int]] = field(default_factory=list)
    _connect_callbacks: list[Callable[[], None]] = field(default_factory=list)
    _disconnect_callbacks: list[Callable[[str], None]] = field(default_factory=list)

    def on_connect(self, callback: Callable[[], None]) -> None:
        self._connect_callbacks.append(callback)

    def on_disconnect(self, callback: Callable[[str], None]) -> None:
        self._disconnect_callbacks.append(callback)

    def start(self) -> None:
        self.started = True

    def stop(self) -> None:
        self.stopped = True
        self.is_connected = False

    def publish(self, topic: str, payload: str, qos: int = 0) -> bool:
        self.published.append((topic, payload, qos))
        return self.is_connected

    def trigger_connect(self) -> None:
        self.is_connected = True
        for callback in list(self._connect_callbacks):
            callback()

    def trigger_disconnect(self, reason: str = "network") -> None:
        self.is_connected = False
        for callback in list(self._disconnect_callbacks):
            callback(reason)


def test_cloud_setup_seeds_state_and_tracks_mqtt_connectivity() -> None:
    app = build_test_app()
    mqtt = FakeMqttClient()

    integration = setup(app, mqtt_client=mqtt)

    assert integration is app.integrations["cloud"]
    assert mqtt.started is True
    assert app.states.get_value("cloud.mqtt_connected") is False
    assert app.states.get("cloud.mqtt_connected").attrs == {
        "reason": "starting",
        "last_sync_at": None,
    }

    worker = threading.Thread(target=mqtt.trigger_connect)
    worker.start()
    worker.join()

    assert app.states.get_value("cloud.mqtt_connected") is False

    drain_all(app)

    assert app.states.get_value("cloud.mqtt_connected") is True
    assert app.states.get("cloud.mqtt_connected").attrs["reason"] == "connected"


def test_cloud_forwards_selected_state_changes_and_explicit_publish() -> None:
    app = build_test_app()
    mqtt = FakeMqttClient(is_connected=True)
    setup(app, mqtt_client=mqtt)
    drain_all(app)

    app.states.set("power.battery_percent", 82, {"source": "pisugar"})
    app.states.set("display.awake", True)
    drain_all(app)

    assert len(mqtt.published) == 1
    topic, payload, qos = mqtt.published[0]
    assert topic == "yoyopod/telemetry/power.battery_percent"
    assert qos == 0
    decoded = json.loads(payload)
    assert decoded["entity"] == "power.battery_percent"
    assert decoded["value"] == 82
    assert decoded["attrs"] == {"source": "pisugar"}

    assert (
        app.services.call(
            "cloud",
            "publish_telemetry",
            PublishTelemetryCommand(
                topic_suffix="diagnostics/custom",
                payload={"ok": True},
                qos=1,
            ),
        )
        is True
    )

    explicit_topic, explicit_payload, explicit_qos = mqtt.published[-1]
    assert explicit_topic == "yoyopod/telemetry/diagnostics/custom"
    assert json.loads(explicit_payload) == {"ok": True}
    assert explicit_qos == 1


def test_cloud_sync_now_updates_last_sync_attr() -> None:
    app = build_test_app()
    mqtt = FakeMqttClient()
    sync_calls: list[str] = []
    setup(
        app,
        mqtt_client=mqtt,
        sync_now_handler=lambda: sync_calls.append("synced") or {"applied": True},
        now_provider=lambda: 1234.5,
    )

    result = app.services.call("cloud", "sync_now", SyncNowCommand())

    assert result == {"applied": True}
    assert sync_calls == ["synced"]
    assert app.states.get("cloud.mqtt_connected").attrs["last_sync_at"] == 1234.5


def test_cloud_services_reject_wrong_payload_types() -> None:
    app = build_test_app()
    setup(app, mqtt_client=FakeMqttClient())

    try:
        app.services.call("cloud", "sync_now", {"force": True})
    except TypeError as exc:
        assert str(exc) == "cloud.sync_now expects SyncNowCommand"
    else:
        raise AssertionError("cloud.sync_now accepted an untyped payload")

    try:
        app.services.call("cloud", "publish_telemetry", {"topic_suffix": "x"})
    except TypeError as exc:
        assert str(exc) == "cloud.publish_telemetry expects PublishTelemetryCommand"
    else:
        raise AssertionError("cloud.publish_telemetry accepted an untyped payload")

    teardown(app)
    assert "cloud" not in app.integrations
