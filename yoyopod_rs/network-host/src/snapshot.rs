use serde::{Deserialize, Serialize};

use crate::config::NetworkHostConfig;

#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum NetworkLifecycleState {
    Off,
    Probing,
    Ready,
    Registering,
    Registered,
    PppStarting,
    Online,
    PppStopping,
    Recovering,
    Degraded,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct SignalSnapshot {
    pub csq: Option<u8>,
    pub bars: u8,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PppSnapshot {
    pub up: bool,
    pub interface: String,
    pub pid: Option<u32>,
    pub default_route_owned: bool,
    pub last_failure: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct GpsSnapshot {
    pub has_fix: bool,
    pub lat: Option<f64>,
    pub lng: Option<f64>,
    pub altitude: Option<f64>,
    pub speed: Option<f64>,
    pub timestamp: Option<String>,
    pub last_query_result: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct NetworkRuntimeSnapshot {
    pub enabled: bool,
    pub gps_enabled: bool,
    pub config_dir: String,
    pub state: NetworkLifecycleState,
    pub sim_ready: bool,
    pub registered: bool,
    pub carrier: String,
    pub network_type: String,
    pub signal: SignalSnapshot,
    pub ppp: PppSnapshot,
    pub gps: GpsSnapshot,
    pub recovering: bool,
    pub retryable: bool,
    pub reconnect_attempts: u32,
    pub next_retry_at_ms: Option<u64>,
    pub error_code: String,
    pub error_message: String,
    pub updated_at_ms: u64,
}

impl NetworkRuntimeSnapshot {
    pub fn offline(config_dir: &str) -> Self {
        Self {
            enabled: false,
            gps_enabled: false,
            config_dir: config_dir.to_string(),
            state: NetworkLifecycleState::Off,
            sim_ready: false,
            registered: false,
            carrier: String::new(),
            network_type: String::new(),
            signal: SignalSnapshot { csq: None, bars: 0 },
            ppp: PppSnapshot {
                up: false,
                interface: String::new(),
                pid: None,
                default_route_owned: false,
                last_failure: String::new(),
            },
            gps: GpsSnapshot {
                has_fix: false,
                lat: None,
                lng: None,
                altitude: None,
                speed: None,
                timestamp: None,
                last_query_result: "idle".to_string(),
            },
            recovering: false,
            retryable: false,
            reconnect_attempts: 0,
            next_retry_at_ms: None,
            error_code: String::new(),
            error_message: String::new(),
            updated_at_ms: 0,
        }
    }

    pub fn from_config(config_dir: &str, config: &NetworkHostConfig) -> Self {
        let mut snapshot = Self::offline(config_dir);
        snapshot.enabled = config.enabled;
        snapshot.gps_enabled = config.gps_enabled;
        snapshot
    }
}
