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

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct NetworkAppStateProjection {
    pub network_enabled: bool,
    pub signal_bars: u8,
    pub connection_type: String,
    pub connected: bool,
    pub gps_has_fix: bool,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct NetworkSetupViewProjection {
    pub network_enabled: bool,
    pub gps_refresh_allowed: bool,
    pub network_rows: Vec<[String; 2]>,
    pub gps_rows: Vec<[String; 2]>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct NetworkCliViewProjection {
    pub probe_ok: bool,
    pub probe_error: String,
    pub status_lines: Vec<String>,
}

#[derive(Debug, Clone, Default, Serialize, Deserialize, PartialEq, Eq)]
pub struct NetworkViewsProjection {
    pub setup: NetworkSetupViewProjection,
    pub cli: NetworkCliViewProjection,
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
    pub connected: bool,
    pub gps_has_fix: bool,
    pub connection_type: String,
    pub network_status: String,
    pub gps_status: String,
    pub recovering: bool,
    pub retryable: bool,
    pub reconnect_attempts: u32,
    pub next_retry_at_ms: Option<u64>,
    pub error_code: String,
    pub error_message: String,
    pub updated_at_ms: u64,
    pub app_state: NetworkAppStateProjection,
    pub views: NetworkViewsProjection,
}

impl NetworkRuntimeSnapshot {
    pub fn offline(config_dir: &str) -> Self {
        let mut snapshot = Self {
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
            connected: false,
            gps_has_fix: false,
            connection_type: String::new(),
            network_status: String::new(),
            gps_status: String::new(),
            recovering: false,
            retryable: false,
            reconnect_attempts: 0,
            next_retry_at_ms: None,
            error_code: String::new(),
            error_message: String::new(),
            updated_at_ms: 0,
            app_state: NetworkAppStateProjection::default(),
            views: NetworkViewsProjection::default(),
        };
        snapshot.refresh_derived();
        snapshot
    }

    pub fn from_config(config_dir: &str, config: &NetworkHostConfig) -> Self {
        let mut snapshot = Self::offline(config_dir);
        snapshot.enabled = config.enabled;
        snapshot.gps_enabled = config.gps_enabled;
        snapshot.refresh_derived();
        snapshot
    }

    pub fn degraded_config_error(config_dir: &str, error: &str) -> Self {
        let mut snapshot = Self::offline(config_dir);
        snapshot.state = NetworkLifecycleState::Degraded;
        snapshot.retryable = false;
        snapshot.error_code = "config_load_failed".to_string();
        snapshot.error_message = error.to_string();
        snapshot.refresh_derived();
        snapshot
    }

    pub fn refresh_derived(&mut self) {
        self.connected = self.enabled && self.ppp.up;
        self.gps_has_fix = self.enabled && self.gps_enabled && self.gps.has_fix;
        self.connection_type = if self.enabled && (self.connected || self.has_cellular_visibility())
        {
            "4g".to_string()
        } else {
            "none".to_string()
        };
        self.network_status = self.derive_network_status().to_string();
        self.gps_status = self.derive_gps_status().to_string();
        self.app_state = self.derive_app_state();
        self.views = self.derive_views();
    }

    fn has_cellular_visibility(&self) -> bool {
        self.registered
            || self.sim_ready
            || !self.carrier.trim().is_empty()
            || !self.network_type.trim().is_empty()
            || self.signal.bars > 0
            || matches!(
                self.state,
                NetworkLifecycleState::Probing
                    | NetworkLifecycleState::Ready
                    | NetworkLifecycleState::Registering
                    | NetworkLifecycleState::Registered
                    | NetworkLifecycleState::PppStarting
                    | NetworkLifecycleState::Online
                    | NetworkLifecycleState::PppStopping
                    | NetworkLifecycleState::Recovering
                    | NetworkLifecycleState::Degraded
            )
    }

    fn derive_network_status(&self) -> &'static str {
        if !self.enabled {
            return "disabled";
        }
        if self.connected {
            return "online";
        }
        match self.state {
            NetworkLifecycleState::Registered
            | NetworkLifecycleState::PppStarting
            | NetworkLifecycleState::PppStopping => "registered",
            NetworkLifecycleState::Probing
            | NetworkLifecycleState::Ready
            | NetworkLifecycleState::Registering
            | NetworkLifecycleState::Recovering => "connecting",
            NetworkLifecycleState::Degraded => "degraded",
            _ => "offline",
        }
    }

    fn derive_gps_status(&self) -> &'static str {
        if !self.enabled || !self.gps_enabled {
            return "disabled";
        }
        if self.gps_has_fix {
            return "fix";
        }
        match self.state {
            NetworkLifecycleState::Off
            | NetworkLifecycleState::Probing
            | NetworkLifecycleState::Ready => "starting",
            NetworkLifecycleState::Registering
            | NetworkLifecycleState::Registered
            | NetworkLifecycleState::PppStarting
            | NetworkLifecycleState::Online
            | NetworkLifecycleState::PppStopping
            | NetworkLifecycleState::Recovering
            | NetworkLifecycleState::Degraded => "searching",
        }
    }

    fn derive_app_state(&self) -> NetworkAppStateProjection {
        NetworkAppStateProjection {
            network_enabled: self.enabled,
            signal_bars: self.signal.bars.min(4),
            connection_type: self.connection_type.clone(),
            connected: self.connected,
            gps_has_fix: self.gps_has_fix,
        }
    }

    fn derive_views(&self) -> NetworkViewsProjection {
        let probe_error = self.cli_probe_error();
        NetworkViewsProjection {
            setup: NetworkSetupViewProjection {
                network_enabled: self.enabled,
                gps_refresh_allowed: self.enabled && self.gps_enabled,
                network_rows: self.build_network_rows(),
                gps_rows: self.build_gps_rows(),
            },
            cli: NetworkCliViewProjection {
                probe_ok: probe_error.is_empty(),
                probe_error: probe_error.clone(),
                status_lines: self.build_cli_status_lines(&probe_error),
            },
        }
    }

    fn build_network_rows(&self) -> Vec<[String; 2]> {
        if !self.enabled {
            return vec![row("Status", "Disabled")];
        }

        let signal_text = if self.signal.csq.is_some() || self.signal.bars > 0 {
            format!("{}/4", self.signal.bars.min(4))
        } else {
            "Unknown".to_string()
        };

        vec![
            row("Status", self.setup_network_status_text()),
            row(
                "Carrier",
                if self.carrier.trim().is_empty() {
                    "Unknown"
                } else {
                    self.carrier.as_str()
                },
            ),
            row(
                "Type",
                if self.network_type.trim().is_empty() {
                    "Unknown"
                } else {
                    self.network_type.as_str()
                },
            ),
            row("Signal", signal_text),
            row("PPP", if self.connected { "Up" } else { "Down" }),
        ]
    }

    fn build_gps_rows(&self) -> Vec<[String; 2]> {
        if !self.enabled || !self.gps_enabled {
            return disabled_gps_rows();
        }
        if self.gps_status != "fix" {
            return vec![
                row("Fix", self.setup_gps_status_text()),
                row("Lat", "--"),
                row("Lng", "--"),
                row("Alt", "--"),
                row("Speed", "--"),
            ];
        }

        vec![
            row("Fix", "Yes"),
            row("Lat", format!("{:.6}", self.gps.lat.unwrap_or(0.0))),
            row("Lng", format!("{:.6}", self.gps.lng.unwrap_or(0.0))),
            row("Alt", format!("{:.1}m", self.gps.altitude.unwrap_or(0.0))),
            row("Speed", format!("{:.1}km/h", self.gps.speed.unwrap_or(0.0))),
        ]
    }

    fn build_cli_status_lines(&self, probe_error: &str) -> Vec<String> {
        vec![
            format!("phase={}", self.state_name()),
            format!("sim_ready={}", self.sim_ready),
            format!(
                "carrier={}",
                if self.carrier.trim().is_empty() {
                    "unknown"
                } else {
                    self.carrier.as_str()
                }
            ),
            format!(
                "network_type={}",
                if self.network_type.trim().is_empty() {
                    "unknown"
                } else {
                    self.network_type.as_str()
                }
            ),
            format!(
                "signal_csq={}",
                self.signal
                    .csq
                    .map(|value| value.to_string())
                    .unwrap_or_else(|| "unknown".to_string())
            ),
            format!("signal_bars={}", self.signal.bars.min(4)),
            format!("ppp_up={}", self.ppp.up),
            format!(
                "error={}",
                if probe_error.is_empty() {
                    "none"
                } else {
                    probe_error
                }
            ),
        ]
    }

    fn cli_probe_error(&self) -> String {
        if !self.error_message.trim().is_empty() {
            return self.error_message.clone();
        }
        if !self.error_code.trim().is_empty() {
            return self.error_code.clone();
        }
        if self.enabled {
            return String::new();
        }
        "network module disabled in config/network/cellular.yaml".to_string()
    }

    fn setup_network_status_text(&self) -> &'static str {
        match self.network_status.as_str() {
            "online" => "Online",
            "registered" => "Registered",
            "connecting" => "Connecting",
            "degraded" => "Degraded",
            "disabled" => "Disabled",
            _ => "Offline",
        }
    }

    fn setup_gps_status_text(&self) -> &'static str {
        match self.gps_status.as_str() {
            "disabled" => "Disabled",
            "starting" => "Starting",
            "unavailable" => "Unavailable",
            _ => "Searching",
        }
    }

    fn state_name(&self) -> &'static str {
        match self.state {
            NetworkLifecycleState::Off => "off",
            NetworkLifecycleState::Probing => "probing",
            NetworkLifecycleState::Ready => "ready",
            NetworkLifecycleState::Registering => "registering",
            NetworkLifecycleState::Registered => "registered",
            NetworkLifecycleState::PppStarting => "ppp_starting",
            NetworkLifecycleState::Online => "online",
            NetworkLifecycleState::PppStopping => "ppp_stopping",
            NetworkLifecycleState::Recovering => "recovering",
            NetworkLifecycleState::Degraded => "degraded",
        }
    }
}

fn row(label: impl Into<String>, value: impl Into<String>) -> [String; 2] {
    [label.into(), value.into()]
}

fn disabled_gps_rows() -> Vec<[String; 2]> {
    vec![
        row("Fix", "Disabled"),
        row("Lat", "--"),
        row("Lng", "--"),
        row("Alt", "--"),
        row("Speed", "--"),
    ]
}
