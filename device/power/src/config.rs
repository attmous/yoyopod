use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_yaml::{Mapping, Value};

const POWER_BACKEND_CONFIG: &str = "power/backend.yaml";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct PowerHostConfig {
    pub enabled: bool,
    pub backend: String,
    pub transport: String,
    pub socket_path: String,
    pub tcp_host: String,
    pub tcp_port: u16,
    pub timeout_seconds: f64,
    pub poll_interval_seconds: f64,
    pub runtime_root: String,
    pub watchdog: PowerWatchdogConfig,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(default)]
pub struct PowerWatchdogConfig {
    pub enabled: bool,
    pub timeout_seconds: u64,
    pub feed_interval_seconds: f64,
    pub i2c_bus: u8,
    pub i2c_address: u16,
    pub command_timeout_seconds: f64,
}

impl Default for PowerHostConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            backend: "pisugar".to_string(),
            transport: "auto".to_string(),
            socket_path: "/tmp/pisugar-server.sock".to_string(),
            tcp_host: "127.0.0.1".to_string(),
            tcp_port: 8423,
            timeout_seconds: 2.0,
            poll_interval_seconds: 30.0,
            runtime_root: String::new(),
            watchdog: PowerWatchdogConfig::default(),
        }
    }
}

impl Default for PowerWatchdogConfig {
    fn default() -> Self {
        Self {
            enabled: false,
            timeout_seconds: 60,
            feed_interval_seconds: 15.0,
            i2c_bus: 1,
            i2c_address: 0x57,
            command_timeout_seconds: 5.0,
        }
    }
}

impl PowerHostConfig {
    pub fn load(config_dir: impl AsRef<Path>) -> Result<Self> {
        let config_dir = config_dir.as_ref();
        let runtime_root = runtime_root_for_config_dir(config_dir);
        let mut config = Self {
            runtime_root: runtime_root.to_string_lossy().to_string(),
            ..Self::default()
        };

        let raw = load_yaml_mapping(&config_dir.join(POWER_BACKEND_CONFIG))?;
        let power = nested_mapping(&raw, "power").unwrap_or(&raw);
        apply_power_mapping(&mut config, power);
        apply_env_overrides(&mut config)?;
        Ok(config)
    }

    pub fn default_for_config_dir(config_dir: impl AsRef<Path>) -> Self {
        let runtime_root = runtime_root_for_config_dir(config_dir.as_ref());
        Self {
            runtime_root: runtime_root.to_string_lossy().to_string(),
            ..Self::default()
        }
    }
}

fn apply_power_mapping(config: &mut PowerHostConfig, power: &Mapping) {
    config.enabled = bool_key(power, "enabled", config.enabled);
    config.backend = string_key(power, "backend", &config.backend);
    config.transport = string_key(power, "transport", &config.transport);
    config.socket_path = string_key(power, "socket_path", &config.socket_path);
    config.tcp_host = string_key(power, "tcp_host", &config.tcp_host);
    config.tcp_port = u16_key(power, "tcp_port", config.tcp_port);
    config.timeout_seconds = f64_key(power, "timeout_seconds", config.timeout_seconds);
    config.poll_interval_seconds =
        f64_key(power, "poll_interval_seconds", config.poll_interval_seconds);
    config.watchdog.enabled = bool_key(power, "watchdog_enabled", config.watchdog.enabled);
    config.watchdog.timeout_seconds = u64_key(
        power,
        "watchdog_timeout_seconds",
        config.watchdog.timeout_seconds,
    );
    config.watchdog.feed_interval_seconds = f64_key(
        power,
        "watchdog_feed_interval_seconds",
        config.watchdog.feed_interval_seconds,
    );
    config.watchdog.i2c_bus = u8_key(power, "watchdog_i2c_bus", config.watchdog.i2c_bus);
    config.watchdog.i2c_address =
        u16_key(power, "watchdog_i2c_address", config.watchdog.i2c_address);
    config.watchdog.command_timeout_seconds = f64_key(
        power,
        "watchdog_command_timeout_seconds",
        config.watchdog.command_timeout_seconds,
    );
}

fn apply_env_overrides(config: &mut PowerHostConfig) -> Result<()> {
    if let Some(value) = env_string("YOYOPOD_POWER_ENABLED") {
        config.enabled = parse_bool("YOYOPOD_POWER_ENABLED", &value)?;
    }
    if let Some(value) = env_string("YOYOPOD_POWER_BACKEND") {
        config.backend = value;
    }
    if let Some(value) = env_string("YOYOPOD_POWER_TRANSPORT") {
        config.transport = value;
    }
    if let Some(value) = env_string("YOYOPOD_PISUGAR_SOCKET_PATH") {
        config.socket_path = value;
    }
    if let Some(value) = env_string("YOYOPOD_PISUGAR_HOST") {
        config.tcp_host = value;
    }
    if let Some(value) = env_string("YOYOPOD_PISUGAR_PORT") {
        config.tcp_port = value
            .parse()
            .with_context(|| format!("parse YOYOPOD_PISUGAR_PORT={value}"))?;
    }
    if let Some(value) = env_string("YOYOPOD_POWER_TIMEOUT_SECONDS") {
        config.timeout_seconds = value
            .parse()
            .with_context(|| format!("parse YOYOPOD_POWER_TIMEOUT_SECONDS={value}"))?;
    }
    if let Some(value) = env_string("YOYOPOD_POWER_POLL_INTERVAL_SECONDS") {
        config.poll_interval_seconds = value
            .parse()
            .with_context(|| format!("parse YOYOPOD_POWER_POLL_INTERVAL_SECONDS={value}"))?;
    }
    if let Some(value) = env_string("YOYOPOD_POWER_WATCHDOG_ENABLED") {
        config.watchdog.enabled = parse_bool("YOYOPOD_POWER_WATCHDOG_ENABLED", &value)?;
    }
    if let Some(value) = env_string("YOYOPOD_POWER_WATCHDOG_TIMEOUT_SECONDS") {
        config.watchdog.timeout_seconds = value
            .parse()
            .with_context(|| format!("parse YOYOPOD_POWER_WATCHDOG_TIMEOUT_SECONDS={value}"))?;
    }
    if let Some(value) = env_string("YOYOPOD_POWER_WATCHDOG_FEED_INTERVAL_SECONDS") {
        config.watchdog.feed_interval_seconds = value.parse().with_context(|| {
            format!("parse YOYOPOD_POWER_WATCHDOG_FEED_INTERVAL_SECONDS={value}")
        })?;
    }
    if let Some(value) = env_string("YOYOPOD_POWER_WATCHDOG_I2C_BUS") {
        config.watchdog.i2c_bus = value
            .parse()
            .with_context(|| format!("parse YOYOPOD_POWER_WATCHDOG_I2C_BUS={value}"))?;
    }
    if let Some(value) = env_string("YOYOPOD_POWER_WATCHDOG_I2C_ADDRESS") {
        config.watchdog.i2c_address = parse_u16(&value)
            .with_context(|| format!("parse YOYOPOD_POWER_WATCHDOG_I2C_ADDRESS={value}"))?;
    }
    if let Some(value) = env_string("YOYOPOD_POWER_WATCHDOG_COMMAND_TIMEOUT_SECONDS") {
        config.watchdog.command_timeout_seconds = value.parse().with_context(|| {
            format!("parse YOYOPOD_POWER_WATCHDOG_COMMAND_TIMEOUT_SECONDS={value}")
        })?;
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

fn u16_key(mapping: &Mapping, key: &str, default: u16) -> u16 {
    mapping
        .get(Value::String(key.to_string()))
        .and_then(|value| {
            value
                .as_u64()
                .and_then(|value| u16::try_from(value).ok())
                .or_else(|| parse_u16(value.as_str()?).ok())
        })
        .unwrap_or(default)
}

fn u8_key(mapping: &Mapping, key: &str, default: u8) -> u8 {
    mapping
        .get(Value::String(key.to_string()))
        .and_then(|value| {
            value
                .as_u64()
                .and_then(|value| u8::try_from(value).ok())
                .or_else(|| value.as_str()?.trim().parse::<u8>().ok())
        })
        .unwrap_or(default)
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

fn parse_u16(value: &str) -> Result<u16> {
    let trimmed = value.trim();
    if let Some(hex) = trimmed
        .strip_prefix("0x")
        .or_else(|| trimmed.strip_prefix("0X"))
    {
        Ok(u16::from_str_radix(hex, 16)?)
    } else {
        Ok(trimmed.parse::<u16>()?)
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
