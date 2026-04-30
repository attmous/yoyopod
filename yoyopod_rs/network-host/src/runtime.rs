use std::time::{SystemTime, UNIX_EPOCH};

use crate::config::NetworkHostConfig;
use crate::modem::{
    ModemController, ModemError, ModemRegistration, NoopModemController, PppHealth, PppLink,
};
use crate::snapshot::{
    GpsSnapshot, NetworkLifecycleState, NetworkRuntimeSnapshot, PppSnapshot, SignalSnapshot,
};

#[derive(Debug)]
pub struct NetworkRuntime<C> {
    config: NetworkHostConfig,
    controller: C,
    snapshot: NetworkRuntimeSnapshot,
}

impl<C> NetworkRuntime<C>
where
    C: ModemController,
{
    pub fn new(config_dir: impl Into<String>, config: NetworkHostConfig, controller: C) -> Self {
        let config_dir = config_dir.into();
        let mut snapshot = NetworkRuntimeSnapshot::from_config(&config_dir, &config);
        snapshot.updated_at_ms = now_ms();
        Self {
            config,
            controller,
            snapshot,
        }
    }

    pub fn snapshot(&self) -> &NetworkRuntimeSnapshot {
        &self.snapshot
    }

    pub fn start(&mut self) -> &NetworkRuntimeSnapshot {
        let reconnect_attempts = self.snapshot.reconnect_attempts;
        if !self.config.enabled {
            self.snapshot =
                NetworkRuntimeSnapshot::from_config(&self.snapshot.config_dir, &self.config);
            self.snapshot.state = NetworkLifecycleState::Off;
            self.snapshot.reconnect_attempts = reconnect_attempts;
            self.touch();
            return &self.snapshot;
        }

        self.snapshot =
            NetworkRuntimeSnapshot::from_config(&self.snapshot.config_dir, &self.config);
        self.snapshot.reconnect_attempts = reconnect_attempts;
        self.snapshot.state = NetworkLifecycleState::Probing;
        self.touch();

        if let Err(error) = self.controller.open() {
            self.apply_degraded(error);
            return &self.snapshot;
        }

        match self.controller.probe() {
            Ok(true) => {}
            Ok(false) => {
                self.apply_degraded(ModemError::retryable(
                    "probe_failed",
                    "Modem probe did not respond",
                ));
                return &self.snapshot;
            }
            Err(error) => {
                self.apply_degraded(error);
                return &self.snapshot;
            }
        }

        match self.controller.initialize(self.config.gps_enabled) {
            Ok(registration) => self.apply_registration(registration),
            Err(error) => {
                self.apply_degraded(error);
                return &self.snapshot;
            }
        }

        match self
            .controller
            .start_ppp(normalized_apn(&self.config.apn), self.config.ppp_timeout)
        {
            Ok(link) => self.apply_online(link),
            Err(error) => self.apply_degraded(error),
        }

        &self.snapshot
    }

    pub fn health(&mut self) -> &NetworkRuntimeSnapshot {
        if self.snapshot.state != NetworkLifecycleState::Online {
            self.touch();
            return &self.snapshot;
        }

        match self.controller.ppp_health() {
            Ok(PppHealth::Up(link)) => self.apply_online(link),
            Ok(PppHealth::ProcessExited) => {
                self.apply_ppp_drop("ppp_process_exited", "PPP process exited")
            }
            Ok(PppHealth::InterfaceDown) => {
                self.apply_ppp_drop("ppp_interface_down", "PPP interface down")
            }
            Err(error) => self.apply_degraded(error),
        }

        &self.snapshot
    }

    pub fn query_gps(&mut self) -> &NetworkRuntimeSnapshot {
        if !self.config.gps_enabled {
            self.snapshot.gps.last_query_result = "disabled".to_string();
            self.touch();
            return &self.snapshot;
        }

        match self.controller.query_gps() {
            Ok(Some(fix)) => {
                self.snapshot.gps = GpsSnapshot {
                    has_fix: true,
                    lat: Some(fix.lat),
                    lng: Some(fix.lng),
                    altitude: Some(fix.altitude),
                    speed: Some(fix.speed),
                    timestamp: fix.timestamp,
                    last_query_result: "fix".to_string(),
                };
            }
            Ok(None) => {
                self.snapshot.gps = GpsSnapshot {
                    has_fix: false,
                    lat: None,
                    lng: None,
                    altitude: None,
                    speed: None,
                    timestamp: None,
                    last_query_result: "no_fix".to_string(),
                };
            }
            Err(error) => {
                self.snapshot.gps.last_query_result = "error".to_string();
                self.snapshot.error_code = error.code;
                self.snapshot.error_message = error.message;
            }
        }

        self.touch();
        &self.snapshot
    }

    pub fn reset_modem(&mut self) -> &NetworkRuntimeSnapshot {
        self.snapshot.recovering = true;
        self.snapshot.retryable = false;
        self.snapshot.reconnect_attempts = self.snapshot.reconnect_attempts.saturating_add(1);
        self.touch();

        if let Err(error) = self.controller.reset() {
            self.apply_degraded(error);
            return &self.snapshot;
        }

        self.start();
        self.snapshot.recovering = false;
        self.touch();
        &self.snapshot
    }

    pub fn shutdown(&mut self) -> &NetworkRuntimeSnapshot {
        let _ = self.controller.close();
        self.snapshot =
            NetworkRuntimeSnapshot::from_config(&self.snapshot.config_dir, &self.config);
        self.snapshot.state = NetworkLifecycleState::Off;
        self.snapshot.recovering = false;
        self.snapshot.retryable = false;
        self.touch();
        &self.snapshot
    }

    fn apply_registration(&mut self, registration: ModemRegistration) {
        self.snapshot.state = NetworkLifecycleState::Registered;
        self.snapshot.sim_ready = registration.sim_ready;
        self.snapshot.registered = registration.registered;
        self.snapshot.carrier = registration.carrier;
        self.snapshot.network_type = registration.network_type;
        self.snapshot.signal = SignalSnapshot {
            csq: registration.signal_csq,
            bars: registration.signal_csq.map(signal_bars).unwrap_or_default(),
        };
        self.snapshot.error_code.clear();
        self.snapshot.error_message.clear();
        self.touch();
    }

    fn apply_online(&mut self, link: PppLink) {
        self.snapshot.state = NetworkLifecycleState::Online;
        self.snapshot.ppp = PppSnapshot {
            up: true,
            interface: link.interface,
            pid: link.pid,
            default_route_owned: link.default_route_owned,
            last_failure: String::new(),
        };
        self.snapshot.recovering = false;
        self.snapshot.retryable = false;
        self.snapshot.error_code.clear();
        self.snapshot.error_message.clear();
        self.touch();
    }

    fn apply_ppp_drop(&mut self, code: &str, message: &str) {
        self.snapshot.state = NetworkLifecycleState::Registered;
        self.snapshot.ppp = PppSnapshot {
            up: false,
            interface: String::new(),
            pid: None,
            default_route_owned: false,
            last_failure: message.to_string(),
        };
        self.snapshot.retryable = true;
        self.snapshot.error_code = code.to_string();
        self.snapshot.error_message = message.to_string();
        self.touch();
    }

    fn apply_degraded(&mut self, error: ModemError) {
        self.snapshot.state = NetworkLifecycleState::Degraded;
        self.snapshot.ppp.up = false;
        self.snapshot.ppp.interface.clear();
        self.snapshot.ppp.pid = None;
        self.snapshot.ppp.default_route_owned = false;
        self.snapshot.retryable = error.retryable;
        self.snapshot.recovering = false;
        self.snapshot.error_code = error.code;
        self.snapshot.error_message = error.message;
        self.touch();
    }

    fn touch(&mut self) {
        self.snapshot.updated_at_ms = now_ms();
    }
}

impl NetworkRuntime<NoopModemController> {
    pub fn degraded_config(config_dir: impl Into<String>, error: impl Into<String>) -> Self {
        let config_dir = config_dir.into();
        let message = error.into();
        let mut snapshot = NetworkRuntimeSnapshot::degraded_config_error(&config_dir, &message);
        snapshot.updated_at_ms = now_ms();
        Self {
            config: NetworkHostConfig::default(),
            controller: NoopModemController,
            snapshot,
        }
    }
}

fn normalized_apn(apn: &str) -> Option<&str> {
    let apn = apn.trim();
    if apn.is_empty() {
        None
    } else {
        Some(apn)
    }
}

fn signal_bars(csq: u8) -> u8 {
    match csq {
        99 | 0 => 0,
        1..=9 => 1,
        10..=14 => 2,
        15..=24 => 3,
        _ => 4,
    }
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or(0)
}
