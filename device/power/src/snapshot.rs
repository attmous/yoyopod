use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct PowerStatusSnapshot {
    pub available: bool,
    pub checked_at_ms: u64,
    pub source: String,
    pub device: PowerDeviceSnapshot,
    pub battery: BatterySnapshot,
    pub rtc: RtcSnapshot,
    pub shutdown: ShutdownSnapshot,
    pub error: String,
}

impl Default for PowerStatusSnapshot {
    fn default() -> Self {
        Self {
            available: false,
            checked_at_ms: current_millis(),
            source: "pisugar".to_string(),
            device: PowerDeviceSnapshot::default(),
            battery: BatterySnapshot::default(),
            rtc: RtcSnapshot::default(),
            shutdown: ShutdownSnapshot::default(),
            error: String::new(),
        }
    }
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct PowerDeviceSnapshot {
    pub model: Option<String>,
    pub firmware_version: Option<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct BatterySnapshot {
    pub level_percent: Option<f64>,
    pub voltage_volts: Option<f64>,
    pub charging: Option<bool>,
    pub power_plugged: Option<bool>,
    pub allow_charging: Option<bool>,
    pub output_enabled: Option<bool>,
    pub temperature_celsius: Option<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct RtcSnapshot {
    pub time: Option<String>,
    pub alarm_enabled: Option<bool>,
    pub alarm_time: Option<String>,
    pub alarm_repeat_mask: Option<i32>,
    pub adjust_ppm: Option<f64>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq)]
pub struct ShutdownSnapshot {
    pub safe_shutdown_level_percent: Option<f64>,
    pub safe_shutdown_delay_seconds: Option<i32>,
}

pub fn current_millis() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or_default()
}
