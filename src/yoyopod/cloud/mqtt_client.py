"""MQTT publisher for device telemetry events sent to the YoYoPod backend."""

from __future__ import annotations

import json
import threading
import time
from typing import Any

from loguru import logger


_RECONNECT_DELAY_SECONDS = 10.0
_KEEPALIVE_SECONDS = 60


class DeviceMqttClient:
    """Publish device telemetry events to the backend MQTT broker.

    The device publishes to ``yoyopod/{device_id}/evt``.
    The backend sends commands on ``yoyopod/{device_id}/cmd``; those are
    forwarded to the registered command callback.
    """

    def __init__(
        self,
        *,
        broker_host: str,
        device_id: str,
        port: int = 1883,
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = False,
        transport: str = "tcp",
        command_callback: Any | None = None,
    ) -> None:
        self._broker_host = broker_host
        self._device_id = device_id
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._transport = transport
        self._command_callback = command_callback

        self._client: Any = None
        self._connected = False
        self._stopped = False
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the MQTT client and connect in the background."""
        try:
            import paho.mqtt.client as mqtt  # type: ignore[import-untyped]
        except ImportError:
            logger.warning(
                "paho-mqtt not installed — device telemetry events will not be sent. "
                "Install with: pip install paho-mqtt"
            )
            return

        client = mqtt.Client(
            client_id=f"yoyopod-{self._device_id}",
            clean_session=True,
            transport=self._transport,
        )

        if self._username:
            client.username_pw_set(self._username, self._password)

        if self._use_tls:
            client.tls_set()

        client.reconnect_delay_set(
            min_delay=1,
            max_delay=int(_RECONNECT_DELAY_SECONDS),
        )

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        with self._lock:
            self._client = client
            self._connected = False
            self._stopped = False

        try:
            client.connect_async(self._broker_host, self._port, keepalive=_KEEPALIVE_SECONDS)
            client.loop_start()
        except Exception as exc:
            with self._lock:
                self._client = None
                self._connected = False
                self._stopped = True
            logger.warning("MQTT startup failed: {}", exc)

    def stop(self) -> None:
        """Disconnect and stop reconnect attempts."""
        with self._lock:
            self._stopped = True
            self._connected = False
            client = self._client
            self._client = None

        if client is not None:
            try:
                client.disconnect()
            except Exception:
                pass
            try:
                client.loop_stop()
            except Exception:
                pass

    def publish_battery(self, *, level: int, charging: bool) -> bool:
        """Publish a battery telemetry event."""
        return self._publish("battery", {"level": level, "charging": charging})

    def publish_heartbeat(self, *, firmware_version: str | None = None) -> bool:
        """Publish a device heartbeat event."""
        payload: dict[str, Any] = {}
        if firmware_version is not None:
            payload["firmware_version"] = firmware_version
        return self._publish("heartbeat", payload)

    def publish_connectivity(self, *, connection_type: str) -> bool:
        """Publish a connectivity change (wifi / 4g)."""
        return self._publish("connectivity", {"type": connection_type})

    def publish_playback_event(self, payload: dict[str, Any]) -> bool:
        """Publish one remote-playback event through the normal device event topic."""
        return self._publish("playback", payload)

    def publish_event(self, event_type: str, payload: dict[str, Any]) -> bool:
        """Publish one typed event envelope through the device event topic."""
        return self._publish(event_type, payload)

    def publish_ack(
        self,
        *,
        command_id: str,
        ok: bool,
        reason: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Publish one command ACK/NACK to ``yoyopod/{device_id}/ack``."""
        with self._lock:
            client = self._client
            connected = self._connected

        if client is None or not connected:
            logger.debug("MQTT not connected — skipping ack for {}", command_id)
            return False

        topic = f"yoyopod/{self._device_id}/ack"
        message_payload: dict[str, Any] = {
            "command_id": command_id,
            "status": "ack" if ok else "nack",
            "payload": payload or {},
        }
        if reason:
            message_payload["reason"] = reason

        try:
            result = client.publish(topic, json.dumps(message_payload), qos=1)
            if result.rc != 0:
                logger.warning("MQTT publish failed for ack {}: rc={}", command_id, result.rc)
                return False
            return True
        except Exception as exc:
            logger.warning("MQTT ack publish error for {}: {}", command_id, exc)
            return False

    def _publish(self, event_type: str, payload: dict[str, Any]) -> bool:
        """Publish one event envelope to ``yoyopod/{device_id}/evt``."""
        with self._lock:
            client = self._client
            connected = self._connected

        if client is None or not connected:
            logger.debug("MQTT not connected — skipping {} event", event_type)
            return False

        topic = f"yoyopod/{self._device_id}/evt"
        message = json.dumps({"type": event_type, "payload": payload, "ts": int(time.time())})
        try:
            result = client.publish(topic, message, qos=1)
            if result.rc != 0:
                logger.warning("MQTT publish failed for {}: rc={}", event_type, result.rc)
                return False
            logger.debug("MQTT published {} event", event_type)
            return True
        except Exception as exc:
            logger.warning("MQTT publish error for {}: {}", event_type, exc)
            return False

    def _on_connect(self, client: Any, userdata: Any, flags: Any, rc: int) -> None:
        if rc == 0:
            with self._lock:
                if self._client is not client or self._stopped:
                    return
                self._connected = True
            client.subscribe(f"yoyopod/{self._device_id}/cmd", qos=1)
            logger.info(
                "MQTT connected to {}:{} (device={})", self._broker_host, self._port, self._device_id
            )
        else:
            logger.warning("MQTT connect refused: rc={}", rc)

    def _on_disconnect(self, client: Any, userdata: Any, rc: int) -> None:
        with self._lock:
            if self._client is not None and self._client is not client:
                return
            self._connected = False
        if rc != 0 and not self._stopped:
            logger.warning("MQTT disconnected unexpectedly: rc={}", rc)

    def _on_message(self, client: Any, userdata: Any, msg: Any) -> None:
        """Handle an incoming command from the backend."""
        try:
            payload = json.loads(msg.payload.decode())
            logger.info(
                "MQTT command received: {}",
                payload.get("command") or payload.get("type", "unknown"),
            )
            if self._command_callback is not None:
                self._command_callback(payload)
        except Exception as exc:
            logger.warning("MQTT command parse error: {}", exc)

    @property
    def is_connected(self) -> bool:
        with self._lock:
            return self._connected
