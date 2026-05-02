use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_yaml::{Mapping, Value};

const CLOUD_BACKEND_CONFIG: &str = "cloud/backend.yaml";
const CLOUD_SECRETS_CONFIG: &str = "cloud/device.secrets.yaml";
const SYSTEM_CLOUD_SECRETS_FILE: &str = "/etc/yoyopod/cloud/device.secrets.yaml";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct CloudHostConfig {
    pub api_base_url: String,
    pub auth_path: String,
    pub refresh_path: String,
    pub config_path_template: String,
    pub contacts_bootstrap_path_template: String,
    pub timeout_seconds: f64,
    pub config_poll_interval_seconds: u64,
    pub claim_retry_seconds: u64,
    pub cache_file: String,
    pub status_file: String,
    pub mqtt_broker_host: String,
    pub mqtt_broker_port: u16,
    pub mqtt_use_tls: bool,
    pub mqtt_transport: String,
    pub mqtt_username: String,
    pub mqtt_password: String,
    pub battery_report_interval_seconds: u64,
    pub device_id: String,
    pub device_secret: String,
    pub runtime_root: String,
    pub secrets_source: String,
    pub secrets_error: String,
}

impl Default for CloudHostConfig {
    fn default() -> Self {
        Self {
            api_base_url: "https://yoyopod.moraouf.net".to_string(),
            auth_path: "/v1/auth/device".to_string(),
            refresh_path: "/v1/auth/device/refresh".to_string(),
            config_path_template: "/v1/devices/{device_id}/config".to_string(),
            contacts_bootstrap_path_template: "/v1/devices/{device_id}/contacts/bootstrap"
                .to_string(),
            timeout_seconds: 3.0,
            config_poll_interval_seconds: 300,
            claim_retry_seconds: 60,
            cache_file: "data/cloud/config_cache.json".to_string(),
            status_file: "data/cloud/status.json".to_string(),
            mqtt_broker_host: "yoyopod.moraouf.net".to_string(),
            mqtt_broker_port: 1883,
            mqtt_use_tls: false,
            mqtt_transport: "tcp".to_string(),
            mqtt_username: String::new(),
            mqtt_password: String::new(),
            battery_report_interval_seconds: 60,
            device_id: String::new(),
            device_secret: String::new(),
            runtime_root: String::new(),
            secrets_source: String::new(),
            secrets_error: String::new(),
        }
    }
}

impl CloudHostConfig {
    pub fn load(config_dir: impl AsRef<Path>) -> Result<Self> {
        let config_dir = config_dir.as_ref();
        let runtime_root = runtime_root_for_config_dir(config_dir);
        let mut config = Self {
            runtime_root: runtime_root.to_string_lossy().to_string(),
            ..Self::default()
        };

        let backend = load_yaml_mapping(&config_dir.join(CLOUD_BACKEND_CONFIG))?;
        let backend = nested_mapping(&backend, "backend").unwrap_or(&backend);
        apply_backend_mapping(&mut config, backend);

        let secrets_path = resolve_secrets_path(config_dir);
        if secrets_path.exists() {
            match load_yaml_mapping(&secrets_path) {
                Ok(raw_secrets) => {
                    let secrets = nested_mapping(&raw_secrets, "secrets").unwrap_or(&raw_secrets);
                    config.device_id = string_key(secrets, "device_id", "");
                    config.device_secret = string_key(secrets, "device_secret", "");
                    config.secrets_source = secrets_path.to_string_lossy().to_string();
                }
                Err(error) => {
                    config.secrets_source = secrets_path.to_string_lossy().to_string();
                    config.secrets_error = format!("Failed to load cloud provisioning: {error}");
                }
            }
        }

        apply_env_overrides(&mut config)?;
        if (config.device_id.trim().is_empty() && !config.device_secret.trim().is_empty())
            || (!config.device_id.trim().is_empty() && config.device_secret.trim().is_empty())
        {
            config.secrets_error =
                "Provisioning file must contain both device_id and device_secret".to_string();
        }
        Ok(config)
    }

    pub fn default_for_config_dir(config_dir: impl AsRef<Path>) -> Self {
        let runtime_root = runtime_root_for_config_dir(config_dir.as_ref());
        Self {
            runtime_root: runtime_root.to_string_lossy().to_string(),
            ..Self::default()
        }
    }

    pub fn status_path(&self) -> PathBuf {
        resolve_runtime_path(&self.runtime_root, &self.status_file)
    }

    pub fn device_event_topic(&self) -> String {
        format!("yoyopod/{}/evt", self.device_id.trim())
    }

    pub fn device_ack_topic(&self) -> String {
        format!("yoyopod/{}/ack", self.device_id.trim())
    }

    pub fn device_command_topic(&self) -> String {
        format!("yoyopod/{}/cmd", self.device_id.trim())
    }

    pub fn mqtt_configured(&self) -> bool {
        !self.mqtt_broker_host.trim().is_empty() && !self.device_id.trim().is_empty()
    }

    pub fn provisioned(&self) -> bool {
        self.secrets_error.trim().is_empty()
            && !self.device_id.trim().is_empty()
            && !self.device_secret.trim().is_empty()
    }
}

fn apply_backend_mapping(config: &mut CloudHostConfig, backend: &Mapping) {
    config.api_base_url = string_key(backend, "api_base_url", &config.api_base_url);
    config.auth_path = string_key(backend, "auth_path", &config.auth_path);
    config.refresh_path = string_key(backend, "refresh_path", &config.refresh_path);
    config.config_path_template = string_key(
        backend,
        "config_path_template",
        &config.config_path_template,
    );
    config.contacts_bootstrap_path_template = string_key(
        backend,
        "contacts_bootstrap_path_template",
        &config.contacts_bootstrap_path_template,
    );
    config.timeout_seconds = f64_key(backend, "timeout_seconds", config.timeout_seconds);
    config.config_poll_interval_seconds = u64_key(
        backend,
        "config_poll_interval_seconds",
        config.config_poll_interval_seconds,
    );
    config.claim_retry_seconds =
        u64_key(backend, "claim_retry_seconds", config.claim_retry_seconds);
    config.cache_file = string_key(backend, "cache_file", &config.cache_file);
    config.status_file = string_key(backend, "status_file", &config.status_file);
    config.mqtt_broker_host = string_key(backend, "mqtt_broker_host", &config.mqtt_broker_host);
    config.mqtt_broker_port = u16_key(backend, "mqtt_broker_port", config.mqtt_broker_port);
    config.mqtt_use_tls = bool_key(backend, "mqtt_use_tls", config.mqtt_use_tls);
    config.mqtt_transport = string_key(backend, "mqtt_transport", &config.mqtt_transport);
    config.mqtt_username = string_key(backend, "mqtt_username", &config.mqtt_username);
    config.mqtt_password = string_key(backend, "mqtt_password", &config.mqtt_password);
    config.battery_report_interval_seconds = u64_key(
        backend,
        "battery_report_interval_seconds",
        config.battery_report_interval_seconds,
    );
}

fn apply_env_overrides(config: &mut CloudHostConfig) -> Result<()> {
    if let Some(value) = env_string("YOYOPOD_CLOUD_API_BASE_URL") {
        config.api_base_url = value;
    }
    if let Some(value) = env_string("YOYOPOD_CLOUD_TIMEOUT_SECONDS") {
        config.timeout_seconds = value
            .parse()
            .with_context(|| format!("parse YOYOPOD_CLOUD_TIMEOUT_SECONDS={value}"))?;
    }
    if let Some(value) = env_string("YOYOPOD_CLOUD_CONFIG_POLL_INTERVAL_SECONDS") {
        config.config_poll_interval_seconds = value
            .parse()
            .with_context(|| format!("parse YOYOPOD_CLOUD_CONFIG_POLL_INTERVAL_SECONDS={value}"))?;
    }
    if let Some(value) = env_string("YOYOPOD_CLOUD_CACHE_FILE") {
        config.cache_file = value;
    }
    if let Some(value) = env_string("YOYOPOD_CLOUD_STATUS_FILE") {
        config.status_file = value;
    }
    if let Some(value) = env_string("YOYOPOD_CLOUD_MQTT_BROKER_HOST") {
        config.mqtt_broker_host = value;
    }
    if let Some(value) = env_string("YOYOPOD_CLOUD_MQTT_BROKER_PORT") {
        config.mqtt_broker_port = value
            .parse()
            .with_context(|| format!("parse YOYOPOD_CLOUD_MQTT_BROKER_PORT={value}"))?;
    }
    if let Some(value) = env_string("YOYOPOD_CLOUD_MQTT_USE_TLS") {
        config.mqtt_use_tls = parse_bool("YOYOPOD_CLOUD_MQTT_USE_TLS", &value)?;
    }
    if let Some(value) = env_string("YOYOPOD_CLOUD_MQTT_TRANSPORT") {
        config.mqtt_transport = value;
    }
    if let Some(value) = env_string("YOYOPOD_CLOUD_MQTT_USERNAME") {
        config.mqtt_username = value;
    }
    if let Some(value) = env_string("YOYOPOD_CLOUD_MQTT_PASSWORD") {
        config.mqtt_password = value;
    }
    if let Some(value) = env_string("YOYOPOD_CLOUD_BATTERY_REPORT_INTERVAL_SECONDS") {
        config.battery_report_interval_seconds = value.parse().with_context(|| {
            format!("parse YOYOPOD_CLOUD_BATTERY_REPORT_INTERVAL_SECONDS={value}")
        })?;
    }
    if let Some(value) = env_string("YOYOPOD_CLOUD_DEVICE_ID") {
        config.device_id = value;
    }
    if let Some(value) = env_string("YOYOPOD_CLOUD_DEVICE_SECRET") {
        config.device_secret = value;
    }
    Ok(())
}

fn load_yaml_mapping(path: &Path) -> Result<Mapping> {
    if !path.exists() {
        return Ok(Mapping::new());
    }
    let raw = fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    let value: Value =
        serde_yaml::from_str(&raw).with_context(|| format!("parse {}", path.display()))?;
    Ok(match value {
        Value::Mapping(mapping) => mapping,
        _ => Mapping::new(),
    })
}

fn nested_mapping<'a>(mapping: &'a Mapping, key: &str) -> Option<&'a Mapping> {
    mapping
        .get(Value::String(key.to_string()))
        .and_then(Value::as_mapping)
}

fn string_key(mapping: &Mapping, key: &str, default: &str) -> String {
    mapping
        .get(Value::String(key.to_string()))
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .unwrap_or(default)
        .to_string()
}

fn u64_key(mapping: &Mapping, key: &str, default: u64) -> u64 {
    mapping
        .get(Value::String(key.to_string()))
        .and_then(|value| {
            value
                .as_u64()
                .or_else(|| value.as_str()?.trim().parse::<u64>().ok())
        })
        .unwrap_or(default)
}

fn u16_key(mapping: &Mapping, key: &str, default: u16) -> u16 {
    mapping
        .get(Value::String(key.to_string()))
        .and_then(|value| {
            value
                .as_u64()
                .and_then(|value| u16::try_from(value).ok())
                .or_else(|| value.as_str()?.trim().parse::<u16>().ok())
        })
        .unwrap_or(default)
}

fn f64_key(mapping: &Mapping, key: &str, default: f64) -> f64 {
    mapping
        .get(Value::String(key.to_string()))
        .and_then(|value| {
            value
                .as_f64()
                .or_else(|| value.as_str()?.trim().parse::<f64>().ok())
        })
        .unwrap_or(default)
}

fn bool_key(mapping: &Mapping, key: &str, default: bool) -> bool {
    mapping
        .get(Value::String(key.to_string()))
        .and_then(|value| {
            value
                .as_bool()
                .or_else(|| parse_bool(key, value.as_str()?).ok())
        })
        .unwrap_or(default)
}

fn env_string(name: &str) -> Option<String> {
    let value = env::var(name).ok()?;
    let value = value.trim();
    if value.is_empty() {
        None
    } else {
        Some(value.to_string())
    }
}

fn parse_bool(name: &str, value: &str) -> Result<bool> {
    match value.trim().to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Ok(true),
        "0" | "false" | "no" | "off" => Ok(false),
        _ => anyhow::bail!("invalid boolean for {name}: {value}"),
    }
}

fn resolve_secrets_path(config_dir: &Path) -> PathBuf {
    let local = config_dir.join(CLOUD_SECRETS_CONFIG);
    if local.exists() {
        local
    } else {
        PathBuf::from(SYSTEM_CLOUD_SECRETS_FILE)
    }
}

fn runtime_root_for_config_dir(config_dir: &Path) -> PathBuf {
    let config_dir = if config_dir.is_absolute() {
        config_dir.to_path_buf()
    } else {
        env::current_dir()
            .map(|cwd| cwd.join(config_dir))
            .unwrap_or_else(|_| config_dir.to_path_buf())
    };
    config_dir
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or(config_dir)
}

fn resolve_runtime_path(runtime_root: &str, raw_path: &str) -> PathBuf {
    let path = Path::new(raw_path);
    if path.is_absolute() || raw_path.starts_with('/') {
        path.to_path_buf()
    } else {
        Path::new(runtime_root).join(path)
    }
}
