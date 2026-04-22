"""Cloud integration scaffold for the Phase A spine rewrite."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from yoyopod.core.events import StateChangedEvent
from yoyopod.integrations.cloud.commands import PublishTelemetryCommand, SyncNowCommand
from yoyopod.integrations.cloud.handlers import (
    apply_mqtt_status_to_state,
    build_state_forwarder,
    publish_telemetry,
    seed_cloud_state,
    sync_now,
)

if TYPE_CHECKING:
    from yoyopod.backends.cloud import DeviceMqttClient
    from yoyopod.integrations.cloud.manager import CloudManager
    from yoyopod.integrations.cloud.models import CloudAccessToken, CloudStatusSnapshot


_EXPORTS = {
    "CloudAccessToken": ("yoyopod.integrations.cloud.models", "CloudAccessToken"),
    "CloudManager": ("yoyopod.integrations.cloud.manager", "CloudManager"),
    "CloudStatusSnapshot": ("yoyopod.integrations.cloud.models", "CloudStatusSnapshot"),
}


def __getattr__(name: str) -> Any:
    """Load public cloud exports lazily to keep submodule imports acyclic."""

    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = __import__(module_name, fromlist=[attribute])
    return getattr(module, attribute)


@dataclass(slots=True)
class CloudIntegration:
    """Runtime handles owned by the scaffold cloud integration."""

    mqtt_client: Any
    sync_now_handler: Callable[[], Any] | None = None
    active: bool = True


def setup(
    app: Any,
    *,
    mqtt_client: Any | None = None,
    sync_now_handler: Callable[[], Any] | None = None,
    now_provider: Callable[[], float] | None = None,
) -> CloudIntegration:
    """Register scaffold cloud services and state forwarding."""

    actual_now = now_provider or time.time
    integration = CloudIntegration(
        mqtt_client=mqtt_client or _build_mqtt_client(app.config),
        sync_now_handler=sync_now_handler,
    )
    app.integrations["cloud"] = integration
    seed_cloud_state(app, reason="starting")

    integration.mqtt_client.on_connect(
        lambda: _schedule_status_update(
            app,
            integration,
            connected=True,
            reason="connected",
        )
    )
    integration.mqtt_client.on_disconnect(
        lambda reason="": _schedule_status_update(
            app,
            integration,
            connected=False,
            reason=reason or "disconnected",
        )
    )
    app.bus.subscribe(
        StateChangedEvent,
        build_state_forwarder(
            app,
            integration.mqtt_client,
            is_active=lambda: integration.active,
        ),
    )
    integration.mqtt_client.start()
    if getattr(integration.mqtt_client, "is_connected", False):
        apply_mqtt_status_to_state(
            app,
            connected=True,
            reason="connected",
        )

    app.services.register(
        "cloud",
        "sync_now",
        lambda data: sync_now(app, integration, data, now=actual_now()),
    )
    app.services.register(
        "cloud",
        "publish_telemetry",
        lambda data: publish_telemetry(integration, data),
    )
    return integration


def teardown(app: Any) -> None:
    """Stop the scaffold cloud integration and drop its runtime handle."""

    integration = app.integrations.pop("cloud", None)
    if integration is None:
        return
    integration.active = False
    apply_mqtt_status_to_state(app, connected=False, reason="stopped")
    integration.mqtt_client.stop()


def _schedule_status_update(
    app: Any,
    integration: CloudIntegration,
    *,
    connected: bool,
    reason: str,
) -> None:
    if not integration.active:
        return
    app.scheduler.run_on_main(
        lambda: apply_mqtt_status_to_state(
            app,
            connected=connected,
            reason=reason,
        )
    )


def _build_mqtt_client(config: object | None) -> DeviceMqttClient:
    from yoyopod.backends.cloud import DeviceMqttClient

    cloud = getattr(config, "cloud", None)
    backend = getattr(cloud, "backend", None)
    secrets = getattr(cloud, "secrets", None)
    broker_host = str(getattr(backend, "mqtt_broker_host", "") or "").strip()
    device_id = str(getattr(secrets, "device_id", "") or "").strip()
    if not broker_host or not device_id:
        return _DisabledMqttClient()
    return DeviceMqttClient(
        broker_host=broker_host,
        device_id=device_id,
        port=int(getattr(backend, "mqtt_broker_port", 1883) or 1883),
        username=str(getattr(backend, "mqtt_username", "") or "") or None,
        password=str(getattr(backend, "mqtt_password", "") or "") or None,
        use_tls=bool(getattr(backend, "mqtt_use_tls", False)),
        transport=str(getattr(backend, "mqtt_transport", "tcp") or "tcp"),
    )


class _DisabledMqttClient:
    """No-op cloud MQTT client used when scaffold config is incomplete."""

    is_connected = False

    def on_connect(self, callback: Callable[[], None]) -> None:
        return None

    def on_disconnect(self, callback: Callable[[str], None]) -> None:
        return None

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def publish(self, topic: str, payload: str, qos: int = 0) -> bool:
        return False


__all__ = [
    "CloudAccessToken",
    "CloudIntegration",
    "CloudManager",
    "CloudStatusSnapshot",
    "PublishTelemetryCommand",
    "SyncNowCommand",
    "setup",
    "teardown",
]
