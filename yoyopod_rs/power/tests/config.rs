use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

use yoyopod_power::config::PowerHostConfig;

const CONFIG_ENV_KEYS: &[&str] = &[
    "YOYOPOD_POWER_ENABLED",
    "YOYOPOD_POWER_BACKEND",
    "YOYOPOD_POWER_TRANSPORT",
    "YOYOPOD_PISUGAR_SOCKET_PATH",
    "YOYOPOD_PISUGAR_HOST",
    "YOYOPOD_PISUGAR_PORT",
    "YOYOPOD_POWER_TIMEOUT_SECONDS",
    "YOYOPOD_POWER_POLL_INTERVAL_SECONDS",
    "YOYOPOD_POWER_WATCHDOG_ENABLED",
    "YOYOPOD_POWER_WATCHDOG_TIMEOUT_SECONDS",
    "YOYOPOD_POWER_WATCHDOG_FEED_INTERVAL_SECONDS",
    "YOYOPOD_POWER_WATCHDOG_I2C_BUS",
    "YOYOPOD_POWER_WATCHDOG_I2C_ADDRESS",
    "YOYOPOD_POWER_WATCHDOG_COMMAND_TIMEOUT_SECONDS",
];

struct EnvSnapshot {
    values: Vec<(&'static str, Option<OsString>)>,
}

impl Drop for EnvSnapshot {
    fn drop(&mut self) {
        for (key, value) in self.values.drain(..) {
            match value {
                Some(value) => std::env::set_var(key, value),
                None => std::env::remove_var(key),
            }
        }
    }
}

fn env_lock() -> &'static Mutex<()> {
    static ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    ENV_LOCK.get_or_init(|| Mutex::new(()))
}

fn lock_env() -> MutexGuard<'static, ()> {
    env_lock().lock().unwrap_or_else(|error| error.into_inner())
}

fn clean_config_env() -> EnvSnapshot {
    let values = CONFIG_ENV_KEYS
        .iter()
        .map(|key| (*key, std::env::var_os(key)))
        .collect();
    for key in CONFIG_ENV_KEYS {
        std::env::remove_var(key);
    }
    EnvSnapshot { values }
}

fn temp_config_dir(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-power-host-config-{test_name}-{unique}"))
}

fn write(path: &Path, contents: &str) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("parent dir");
    }
    fs::write(path, contents).expect("write config");
}

#[test]
fn loads_power_backend_yaml_with_python_defaults() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("yaml");
    write(
        &dir.join("power/backend.yaml"),
        r#"
power:
  enabled: false
  backend: "pisugar"
  transport: "tcp"
  socket_path: "/tmp/custom-pisugar.sock"
  tcp_host: "10.0.0.2"
  tcp_port: 18423
  timeout_seconds: 1.5
  poll_interval_seconds: 12.5
  watchdog_enabled: true
  watchdog_timeout_seconds: 44
  watchdog_feed_interval_seconds: 8.5
  watchdog_i2c_bus: 2
  watchdog_i2c_address: 0x58
  watchdog_command_timeout_seconds: 3.25
"#,
    );

    let config = PowerHostConfig::load(&dir).expect("load power config");

    assert!(!config.enabled);
    assert_eq!(config.backend, "pisugar");
    assert_eq!(config.transport, "tcp");
    assert_eq!(config.socket_path, "/tmp/custom-pisugar.sock");
    assert_eq!(config.tcp_host, "10.0.0.2");
    assert_eq!(config.tcp_port, 18423);
    assert_eq!(config.timeout_seconds, 1.5);
    assert_eq!(config.poll_interval_seconds, 12.5);
    assert!(config.watchdog.enabled);
    assert_eq!(config.watchdog.timeout_seconds, 44);
    assert_eq!(config.watchdog.feed_interval_seconds, 8.5);
    assert_eq!(config.watchdog.i2c_bus, 2);
    assert_eq!(config.watchdog.i2c_address, 0x58);
    assert_eq!(config.watchdog.command_timeout_seconds, 3.25);
}

#[test]
fn env_overrides_power_connection_settings() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("env");
    fs::create_dir_all(&dir).expect("config dir");
    std::env::set_var("YOYOPOD_POWER_ENABLED", "false");
    std::env::set_var("YOYOPOD_POWER_TRANSPORT", "socket");
    std::env::set_var("YOYOPOD_PISUGAR_SOCKET_PATH", "/tmp/env.sock");
    std::env::set_var("YOYOPOD_PISUGAR_HOST", "192.0.2.55");
    std::env::set_var("YOYOPOD_PISUGAR_PORT", "8424");
    std::env::set_var("YOYOPOD_POWER_TIMEOUT_SECONDS", "0.75");
    std::env::set_var("YOYOPOD_POWER_POLL_INTERVAL_SECONDS", "9.25");
    std::env::set_var("YOYOPOD_POWER_WATCHDOG_ENABLED", "true");
    std::env::set_var("YOYOPOD_POWER_WATCHDOG_TIMEOUT_SECONDS", "22");
    std::env::set_var("YOYOPOD_POWER_WATCHDOG_FEED_INTERVAL_SECONDS", "4.5");
    std::env::set_var("YOYOPOD_POWER_WATCHDOG_I2C_BUS", "3");
    std::env::set_var("YOYOPOD_POWER_WATCHDOG_I2C_ADDRESS", "0x59");
    std::env::set_var("YOYOPOD_POWER_WATCHDOG_COMMAND_TIMEOUT_SECONDS", "2.25");

    let config = PowerHostConfig::load(&dir).expect("load power config");

    assert!(!config.enabled);
    assert_eq!(config.transport, "socket");
    assert_eq!(config.socket_path, "/tmp/env.sock");
    assert_eq!(config.tcp_host, "192.0.2.55");
    assert_eq!(config.tcp_port, 8424);
    assert_eq!(config.timeout_seconds, 0.75);
    assert_eq!(config.poll_interval_seconds, 9.25);
    assert!(config.watchdog.enabled);
    assert_eq!(config.watchdog.timeout_seconds, 22);
    assert_eq!(config.watchdog.feed_interval_seconds, 4.5);
    assert_eq!(config.watchdog.i2c_bus, 3);
    assert_eq!(config.watchdog.i2c_address, 0x59);
    assert_eq!(config.watchdog.command_timeout_seconds, 2.25);
}
