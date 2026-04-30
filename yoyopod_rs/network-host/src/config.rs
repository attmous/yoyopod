use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::Deserialize;
use serde_yaml::{Mapping, Value};

const NETWORK_CELLULAR_CONFIG: &str = "network/cellular.yaml";

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(default)]
pub struct NetworkHostConfig {
    pub enabled: bool,
    pub serial_port: String,
    pub ppp_port: String,
    pub baud_rate: u32,
    pub apn: String,
    pub pin: Option<String>,
    pub gps_enabled: bool,
    pub ppp_timeout: u64,
}

impl Default for NetworkHostConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            serial_port: "/dev/ttyUSB2".to_string(),
            ppp_port: "/dev/ttyUSB3".to_string(),
            baud_rate: 115200,
            apn: String::new(),
            pin: None,
            gps_enabled: true,
            ppp_timeout: 30,
        }
    }
}

impl NetworkHostConfig {
    pub fn load(config_dir: impl AsRef<Path>) -> Result<Self> {
        let config_dir = config_dir.as_ref();
        let layers = resolve_network_layers(config_dir);
        let merged = load_yaml_layers(&layers)?;
        let payload = extract_network_payload(merged);
        let mut config: Self = serde_yaml::from_value(payload).context("parse network config")?;
        apply_env_overrides(&mut config)?;
        Ok(config)
    }
}

fn resolve_network_layers(config_dir: &Path) -> Vec<PathBuf> {
    let mut layers = vec![config_dir.join(NETWORK_CELLULAR_CONFIG)];
    if let Some(board) = active_board() {
        let board_path = config_dir
            .join("boards")
            .join(board)
            .join(NETWORK_CELLULAR_CONFIG);
        if board_path.exists() {
            layers.push(board_path);
        }
    }
    layers
}

fn active_board() -> Option<String> {
    let board = env::var("YOYOPOD_CONFIG_BOARD").ok()?;
    let board = board.trim();
    if board.is_empty() {
        None
    } else {
        Some(board.to_string())
    }
}

fn load_yaml_layers(paths: &[PathBuf]) -> Result<Value> {
    let mut merged = Value::Mapping(Mapping::new());
    for path in paths {
        if !path.exists() {
            continue;
        }
        let raw = fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
        let value: Value =
            serde_yaml::from_str(&raw).with_context(|| format!("parse {}", path.display()))?;
        merged = deep_merge(merged, value);
    }
    Ok(merged)
}

fn extract_network_payload(payload: Value) -> Value {
    match payload {
        Value::Mapping(mapping) => match mapping.get(Value::String("network".to_string())) {
            Some(Value::Mapping(network)) => Value::Mapping(network.clone()),
            Some(_) => Value::Mapping(Mapping::new()),
            None => Value::Mapping(mapping),
        },
        _ => Value::Mapping(Mapping::new()),
    }
}

fn deep_merge(base: Value, overlay: Value) -> Value {
    match (base, overlay) {
        (Value::Mapping(mut base), Value::Mapping(overlay)) => {
            for (key, overlay_value) in overlay {
                let merged_value = match base.remove(&key) {
                    Some(base_value) => deep_merge(base_value, overlay_value),
                    None => overlay_value,
                };
                base.insert(key, merged_value);
            }
            Value::Mapping(base)
        }
        (_, overlay) => overlay,
    }
}

fn apply_env_overrides(config: &mut NetworkHostConfig) -> Result<()> {
    if let Some(value) = env_string("YOYOPOD_NETWORK_ENABLED") {
        config.enabled = parse_bool("YOYOPOD_NETWORK_ENABLED", &value)?;
    }
    if let Some(value) = env_string("YOYOPOD_MODEM_PORT") {
        config.serial_port = value;
    }
    if let Some(value) = env_string("YOYOPOD_MODEM_PPP_PORT") {
        config.ppp_port = value;
    }
    if let Some(value) = env_string("YOYOPOD_MODEM_BAUD") {
        config.baud_rate = value
            .parse()
            .with_context(|| format!("parse YOYOPOD_MODEM_BAUD={value}"))?;
    }
    if let Some(value) = env_string("YOYOPOD_MODEM_APN") {
        config.apn = value;
    }
    if let Some(value) = env_string("YOYOPOD_MODEM_GPS_ENABLED") {
        config.gps_enabled = parse_bool("YOYOPOD_MODEM_GPS_ENABLED", &value)?;
    }
    if let Some(value) = env_string("YOYOPOD_MODEM_PPP_TIMEOUT") {
        config.ppp_timeout = value
            .parse()
            .with_context(|| format!("parse YOYOPOD_MODEM_PPP_TIMEOUT={value}"))?;
    }
    Ok(())
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
