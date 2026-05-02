use std::collections::BTreeMap;

use anyhow::{Context, Result};
use serde_json::{json, Value};

use crate::config::CloudHostConfig;
use crate::mqtt::{CloudMqttBackend, MqttRuntimeEvent};
use crate::snapshot::{current_epoch_seconds, current_millis, persist_status, CloudStatusSnapshot};

pub struct CloudHost<B: CloudMqttBackend> {
    config_dir: String,
    config: CloudHostConfig,
    mqtt: B,
    snapshot: CloudStatusSnapshot,
    last_telemetry_payloads: BTreeMap<String, Value>,
    last_connectivity_type: Option<String>,
    next_battery_report_at_ms: u64,
}

impl<B: CloudMqttBackend> CloudHost<B> {
    pub fn new(config_dir: impl Into<String>, config: CloudHostConfig, mqtt: B) -> Self {
        let snapshot = CloudStatusSnapshot::from_config(&config);
        Self {
            config_dir: config_dir.into(),
            config,
            mqtt,
            snapshot,
            last_telemetry_payloads: BTreeMap::new(),
            last_connectivity_type: None,
            next_battery_report_at_ms: 0,
        }
    }

    pub fn config_dir(&self) -> &str {
        &self.config_dir
    }

    pub fn snapshot(&self) -> &CloudStatusSnapshot {
        &self.snapshot
    }

    pub fn mark_config_load_failed(&mut self, error: impl Into<String>) {
        self.snapshot.mark_config_load_failed(error);
        self.persist_status();
    }

    pub fn start(&mut self) -> Result<()> {
        if self.snapshot.provisioning_state == "invalid_provisioning" {
            self.persist_status();
            return Ok(());
        }
        if !self.config.provisioned() {
            self.snapshot.provisioning_state = "unprovisioned".to_string();
            self.snapshot.cloud_state = "offline".to_string();
            self.persist_status();
            return Ok(());
        }
        self.snapshot.provisioning_state = "provisioned".to_string();
        if !self.config.mqtt_configured() {
            self.snapshot.cloud_state = "offline".to_string();
            self.snapshot.last_error_summary = "MQTT broker host not configured".to_string();
            self.persist_status();
            return Ok(());
        }

        self.snapshot.mark_connecting();
        self.mqtt.start(&self.config).inspect_err(|error| {
            self.snapshot.mark_degraded(error.to_string());
            self.persist_status();
        })?;
        self.persist_status();
        Ok(())
    }

    pub fn stop(&mut self) {
        self.mqtt.stop();
        self.snapshot.mark_disconnected("stopped");
        self.persist_status();
    }

    pub fn drain_runtime_events(&mut self) -> Vec<CloudRuntimeEvent> {
        let mut events = Vec::new();
        for event in self.mqtt.drain_events() {
            match event {
                MqttRuntimeEvent::Connected => {
                    self.snapshot.mark_connected();
                    self.persist_status();
                    events.push(CloudRuntimeEvent::Snapshot(self.snapshot.clone()));
                }
                MqttRuntimeEvent::Disconnected(reason) => {
                    self.snapshot.mark_disconnected(reason);
                    self.persist_status();
                    events.push(CloudRuntimeEvent::Snapshot(self.snapshot.clone()));
                }
                MqttRuntimeEvent::Command(command) => {
                    self.snapshot
                        .mark_command(command_type(&command).unwrap_or_default());
                    self.persist_status();
                    events.push(CloudRuntimeEvent::Command(command));
                    events.push(CloudRuntimeEvent::Snapshot(self.snapshot.clone()));
                }
                MqttRuntimeEvent::Error(message) => {
                    self.snapshot.mark_degraded(message.clone());
                    self.persist_status();
                    events.push(CloudRuntimeEvent::Error(message));
                    events.push(CloudRuntimeEvent::Snapshot(self.snapshot.clone()));
                }
            }
        }
        if self.mqtt.is_connected() && !self.snapshot.mqtt_connected {
            self.snapshot.mark_connected();
            self.persist_status();
            events.push(CloudRuntimeEvent::Snapshot(self.snapshot.clone()));
        }
        events
    }

    pub fn health_payload(&self) -> Value {
        json!({ "snapshot": self.snapshot })
    }

    pub fn publish_heartbeat(&mut self, firmware_version: Option<&str>) -> Result<bool> {
        let mut payload = json!({});
        if let Some(firmware_version) = firmware_version.filter(|value| !value.trim().is_empty()) {
            payload["firmware_version"] = json!(firmware_version);
        }
        self.publish_device_event("heartbeat", payload)
    }

    pub fn publish_battery(&mut self, level: i64, charging: bool) -> Result<bool> {
        let now = current_millis();
        if now < self.next_battery_report_at_ms {
            return Ok(false);
        }
        let level = level.clamp(0, 100);
        let published = self.publish_device_event(
            "battery",
            json!({
                "level": level,
                "charging": charging,
            }),
        )?;
        if published {
            self.next_battery_report_at_ms =
                now + self.config.battery_report_interval_seconds.max(1) * 1000;
        }
        Ok(published)
    }

    pub fn publish_connectivity(&mut self, connection_type: &str) -> Result<bool> {
        let connection_type = connection_type.trim();
        if connection_type.is_empty() {
            return Ok(false);
        }
        if self
            .last_connectivity_type
            .as_deref()
            .is_some_and(|last| last == connection_type)
        {
            return Ok(false);
        }
        let published = self.publish_device_event(
            "connectivity",
            json!({
                "type": connection_type,
            }),
        )?;
        if published {
            self.last_connectivity_type = Some(connection_type.to_string());
        }
        Ok(published)
    }

    pub fn publish_playback_event(&mut self, payload: Value) -> Result<bool> {
        self.publish_device_event("playback", payload)
    }

    pub fn publish_device_event(&mut self, event_type: &str, payload: Value) -> Result<bool> {
        if !self.snapshot.mqtt_connected && !self.mqtt.is_connected() {
            return Ok(false);
        }
        let topic = self.config.device_event_topic();
        let message = json!({
            "type": event_type,
            "payload": payload,
            "ts": current_epoch_seconds(),
        });
        self.mqtt
            .publish(&topic, &serde_json::to_string(&message)?, 1)
            .with_context(|| format!("publish cloud event {event_type}"))
    }

    pub fn publish_telemetry(
        &mut self,
        topic_suffix: &str,
        payload: Value,
        qos: u8,
    ) -> Result<bool> {
        if !self.snapshot.mqtt_connected && !self.mqtt.is_connected() {
            return Ok(false);
        }
        let topic_suffix = topic_suffix.trim().trim_matches('/');
        if topic_suffix.is_empty() {
            return Ok(false);
        }
        let key = format!("telemetry/{topic_suffix}");
        if self
            .last_telemetry_payloads
            .get(&key)
            .is_some_and(|last| last == &payload)
        {
            return Ok(false);
        }
        let topic = format!("yoyopod/telemetry/{topic_suffix}");
        let encoded = serde_json::to_string(&payload)?;
        let published = self.mqtt.publish(&topic, &encoded, qos)?;
        if published {
            self.last_telemetry_payloads.insert(key, payload);
        }
        Ok(published)
    }

    pub fn publish_ack(
        &mut self,
        command_id: &str,
        ok: bool,
        reason: Option<&str>,
        payload: Value,
    ) -> Result<bool> {
        if !self.snapshot.mqtt_connected && !self.mqtt.is_connected() {
            return Ok(false);
        }
        let command_id = command_id.trim();
        if command_id.is_empty() {
            return Ok(false);
        }
        let mut message = json!({
            "command_id": command_id,
            "status": if ok { "ack" } else { "nack" },
            "payload": payload,
        });
        if let Some(reason) = reason.filter(|value| !value.trim().is_empty()) {
            message["reason"] = json!(reason);
        }
        self.mqtt
            .publish(
                &self.config.device_ack_topic(),
                &serde_json::to_string(&message)?,
                1,
            )
            .with_context(|| format!("publish cloud ack {command_id}"))
    }

    pub fn persist_status(&self) {
        persist_status(&self.config, &self.snapshot);
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum CloudRuntimeEvent {
    Snapshot(CloudStatusSnapshot),
    Command(Value),
    Error(String),
}

fn command_type(command: &Value) -> Option<String> {
    command
        .get("command")
        .or_else(|| command.get("type"))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}
