use std::fs;
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

use crate::config::CloudHostConfig;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct CloudStatusSnapshot {
    pub device_id: String,
    pub provisioning_state: String,
    pub cloud_state: String,
    pub mqtt_connected: bool,
    pub mqtt_broker_host: String,
    pub mqtt_broker_port: u16,
    pub mqtt_transport: String,
    pub config_source: String,
    pub config_version: u64,
    pub backend_reachable: Option<bool>,
    pub last_successful_sync: Option<String>,
    pub last_error_summary: String,
    pub unapplied_keys: Vec<String>,
    pub last_command_type: String,
    pub updated_at_ms: u64,
}

impl CloudStatusSnapshot {
    pub fn from_config(config: &CloudHostConfig) -> Self {
        let provisioning_state = if !config.secrets_error.trim().is_empty() {
            "invalid_provisioning"
        } else if config.device_id.trim().is_empty() && config.device_secret.trim().is_empty() {
            "unprovisioned"
        } else if config.device_id.trim().is_empty() || config.device_secret.trim().is_empty() {
            "invalid_provisioning"
        } else {
            "provisioned"
        };
        let cloud_state = if provisioning_state == "invalid_provisioning" {
            "degraded"
        } else {
            "offline"
        };
        let last_error_summary = if provisioning_state == "invalid_provisioning" {
            config.secrets_error.clone()
        } else {
            String::new()
        };

        Self {
            device_id: config.device_id.trim().to_string(),
            provisioning_state: provisioning_state.to_string(),
            cloud_state: cloud_state.to_string(),
            mqtt_connected: false,
            mqtt_broker_host: config.mqtt_broker_host.clone(),
            mqtt_broker_port: config.mqtt_broker_port,
            mqtt_transport: config.mqtt_transport.clone(),
            config_source: "none".to_string(),
            config_version: 0,
            backend_reachable: None,
            last_successful_sync: None,
            last_error_summary,
            unapplied_keys: Vec::new(),
            last_command_type: String::new(),
            updated_at_ms: current_millis(),
        }
    }

    pub fn mark_config_load_failed(&mut self, error: impl Into<String>) {
        self.provisioning_state = "invalid_provisioning".to_string();
        self.cloud_state = "degraded".to_string();
        self.last_error_summary = error.into();
        self.refresh_timestamp();
    }

    pub fn mark_connecting(&mut self) {
        self.cloud_state = "connecting".to_string();
        self.last_error_summary.clear();
        self.refresh_timestamp();
    }

    pub fn mark_connected(&mut self) {
        self.mqtt_connected = true;
        self.cloud_state = "ready".to_string();
        self.last_error_summary.clear();
        self.refresh_timestamp();
    }

    pub fn mark_disconnected(&mut self, reason: impl Into<String>) {
        self.mqtt_connected = false;
        self.cloud_state = "offline".to_string();
        self.last_error_summary = reason.into();
        self.refresh_timestamp();
    }

    pub fn mark_degraded(&mut self, reason: impl Into<String>) {
        self.mqtt_connected = false;
        self.cloud_state = "degraded".to_string();
        self.last_error_summary = reason.into();
        self.refresh_timestamp();
    }

    pub fn mark_command(&mut self, command_type: impl Into<String>) {
        self.last_command_type = command_type.into();
        self.refresh_timestamp();
    }

    pub fn refresh_timestamp(&mut self) {
        self.updated_at_ms = current_millis();
    }
}

pub fn persist_status(config: &CloudHostConfig, snapshot: &CloudStatusSnapshot) {
    let path = config.status_path();
    if let Some(parent) = path.parent() {
        let _ = fs::create_dir_all(parent);
    }
    if let Ok(payload) = serde_json::to_string_pretty(snapshot) {
        let _ = fs::write(path, payload);
    }
}

pub fn current_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or_default()
}

pub fn current_epoch_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default()
}
