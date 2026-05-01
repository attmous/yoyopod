use std::collections::VecDeque;
use std::time::{SystemTime, UNIX_EPOCH};

use crate::config::NetworkHostConfig;
use crate::modem::{
    ModemController, ModemError, ModemRegistration, NoopModemController, PppHealth, PppLink,
};
use crate::snapshot::{
    GpsSnapshot, NetworkLifecycleState, NetworkRuntimeSnapshot, PppSnapshot, SignalSnapshot,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RecoveryPolicy {
    pub base_delay_ms: u64,
    pub max_delay_ms: u64,
}

impl RecoveryPolicy {
    pub fn new(base_delay_ms: u64, max_delay_ms: u64) -> Self {
        Self {
            base_delay_ms,
            max_delay_ms: max_delay_ms.max(base_delay_ms),
        }
    }

    fn backoff_delay_ms(&self, attempt: u32) -> u64 {
        if attempt <= 1 {
            return self.base_delay_ms;
        }

        let factor = 1_u64 << attempt.saturating_sub(1).min(20);
        self.base_delay_ms
            .saturating_mul(factor)
            .min(self.max_delay_ms)
    }
}

impl Default for RecoveryPolicy {
    fn default() -> Self {
        Self::new(1_000, 30_000)
    }
}

const DEFAULT_LIVE_FACT_POLL_INTERVAL_MS: u64 = 5_000;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeCommandError {
    pub code: String,
    pub message: String,
}

impl RuntimeCommandError {
    fn from_modem_error(error: ModemError) -> Self {
        Self {
            code: error.code,
            message: error.message,
        }
    }
}

#[derive(Debug)]
pub struct NetworkRuntime<C> {
    config: NetworkHostConfig,
    controller: C,
    snapshot: NetworkRuntimeSnapshot,
    recovery_policy: RecoveryPolicy,
    live_fact_poll_interval_ms: u64,
    last_live_fact_poll_at_ms: Option<u64>,
    pending_snapshots: VecDeque<NetworkRuntimeSnapshot>,
    last_published_snapshot: Option<NetworkRuntimeSnapshot>,
}

impl<C> NetworkRuntime<C>
where
    C: ModemController,
{
    pub fn new(config_dir: impl Into<String>, config: NetworkHostConfig, controller: C) -> Self {
        Self::new_with_policy_and_live_fact_poll_interval(
            config_dir,
            config,
            controller,
            RecoveryPolicy::default(),
            DEFAULT_LIVE_FACT_POLL_INTERVAL_MS,
        )
    }

    pub fn new_with_policy(
        config_dir: impl Into<String>,
        config: NetworkHostConfig,
        controller: C,
        recovery_policy: RecoveryPolicy,
    ) -> Self {
        Self::new_with_policy_and_live_fact_poll_interval(
            config_dir,
            config,
            controller,
            recovery_policy,
            DEFAULT_LIVE_FACT_POLL_INTERVAL_MS,
        )
    }

    pub fn new_with_policy_and_live_fact_poll_interval(
        config_dir: impl Into<String>,
        config: NetworkHostConfig,
        controller: C,
        recovery_policy: RecoveryPolicy,
        live_fact_poll_interval_ms: u64,
    ) -> Self {
        let config_dir = config_dir.into();
        let mut snapshot = NetworkRuntimeSnapshot::from_config(&config_dir, &config);
        snapshot.updated_at_ms = now_ms();
        Self {
            config,
            controller,
            snapshot,
            recovery_policy,
            live_fact_poll_interval_ms: live_fact_poll_interval_ms.max(1),
            last_live_fact_poll_at_ms: None,
            pending_snapshots: VecDeque::new(),
            last_published_snapshot: None,
        }
    }

    pub fn snapshot(&self) -> &NetworkRuntimeSnapshot {
        &self.snapshot
    }

    pub fn drain_snapshot_events(&mut self) -> Vec<NetworkRuntimeSnapshot> {
        self.pending_snapshots.drain(..).collect()
    }

    pub fn start(&mut self) -> &NetworkRuntimeSnapshot {
        self.start_at(now_ms())
    }

    pub fn start_at(&mut self, now_ms: u64) -> &NetworkRuntimeSnapshot {
        let reconnect_attempts = self.snapshot.reconnect_attempts;
        let gps = self.snapshot.gps.clone();

        self.snapshot =
            NetworkRuntimeSnapshot::from_config(&self.snapshot.config_dir, &self.config);
        self.snapshot.reconnect_attempts = reconnect_attempts;
        self.snapshot.gps = gps;
        self.snapshot.updated_at_ms = now_ms;
        self.last_live_fact_poll_at_ms = None;

        if !self.config.enabled {
            self.snapshot.state = NetworkLifecycleState::Off;
            self.snapshot.retryable = false;
            self.snapshot.next_retry_at_ms = None;
            self.publish_snapshot();
            return &self.snapshot;
        }

        if let Err(error) = self.attempt_bringup(now_ms) {
            self.schedule_retry(now_ms, error, NetworkLifecycleState::Degraded);
        }

        &self.snapshot
    }

    pub fn tick(&mut self) -> &NetworkRuntimeSnapshot {
        self.tick_at(now_ms())
    }

    pub fn tick_at(&mut self, now_ms: u64) -> &NetworkRuntimeSnapshot {
        if self.snapshot.state == NetworkLifecycleState::Online {
            let _ = self.poll_ppp_health(now_ms, false);
            let _ = self.refresh_live_facts_if_due(now_ms, false);
        }

        if self.snapshot.retryable
            && self
                .snapshot
                .next_retry_at_ms
                .is_some_and(|deadline| now_ms >= deadline)
        {
            let _ = self.run_recovery(now_ms);
        } else {
            self.touch(now_ms);
        }

        &self.snapshot
    }

    pub fn health(&mut self) -> &NetworkRuntimeSnapshot {
        let _ = self.health_command();
        &self.snapshot
    }

    pub fn health_command(&mut self) -> Result<&NetworkRuntimeSnapshot, RuntimeCommandError> {
        let now_ms = now_ms();
        match self.poll_ppp_health(now_ms, true) {
            Some(error) => Err(error),
            None => {
                self.refresh_live_facts_if_due(now_ms, true)?;
                match self.active_fault_error() {
                    Some(error) => Err(error),
                    None => Ok(&self.snapshot),
                }
            }
        }
    }

    pub fn query_gps(&mut self) -> &NetworkRuntimeSnapshot {
        let _ = self.query_gps_command();
        &self.snapshot
    }

    pub fn query_gps_command(&mut self) -> Result<&NetworkRuntimeSnapshot, RuntimeCommandError> {
        if !self.config.gps_enabled {
            self.snapshot.gps.last_query_result = "disabled".to_string();
            self.touch(now_ms());
            self.publish_snapshot();
            return Ok(&self.snapshot);
        }

        let now_ms = now_ms();
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
                self.touch(now_ms);
                self.publish_snapshot();
                Ok(&self.snapshot)
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
                self.touch(now_ms);
                self.publish_snapshot();
                Ok(&self.snapshot)
            }
            Err(error) => {
                let error_for_event = RuntimeCommandError::from_modem_error(error.clone());
                self.snapshot.gps.last_query_result = "error".to_string();
                self.snapshot.error_code = error.code;
                self.snapshot.error_message = error.message;
                self.touch(now_ms);
                self.publish_snapshot();
                Err(error_for_event)
            }
        }
    }

    pub fn reset_modem(&mut self) -> &NetworkRuntimeSnapshot {
        let _ = self.reset_modem_command();
        &self.snapshot
    }

    pub fn reset_modem_command(&mut self) -> Result<&NetworkRuntimeSnapshot, RuntimeCommandError> {
        let now_ms = now_ms();
        match self.run_recovery(now_ms) {
            Ok(()) => Ok(&self.snapshot),
            Err(error) => Err(error),
        }
    }

    pub fn shutdown(&mut self) -> &NetworkRuntimeSnapshot {
        self.shutdown_at(now_ms())
    }

    pub fn shutdown_at(&mut self, now_ms: u64) -> &NetworkRuntimeSnapshot {
        if self.snapshot.ppp.up {
            self.snapshot.state = NetworkLifecycleState::PppStopping;
            self.touch(now_ms);
            self.publish_snapshot();
            let _ = self.controller.stop_ppp();
            self.clear_ppp();
        }

        let _ = self.controller.close();
        let reconnect_attempts = self.snapshot.reconnect_attempts;
        let gps = self.snapshot.gps.clone();
        self.snapshot =
            NetworkRuntimeSnapshot::from_config(&self.snapshot.config_dir, &self.config);
        self.snapshot.state = NetworkLifecycleState::Off;
        self.snapshot.reconnect_attempts = reconnect_attempts;
        self.snapshot.gps = gps;
        self.snapshot.retryable = false;
        self.snapshot.recovering = false;
        self.snapshot.next_retry_at_ms = None;
        self.last_live_fact_poll_at_ms = None;
        self.touch(now_ms);
        self.publish_snapshot();
        &self.snapshot
    }

    fn run_recovery(&mut self, now_ms: u64) -> Result<(), RuntimeCommandError> {
        self.snapshot.state = NetworkLifecycleState::Recovering;
        self.snapshot.recovering = true;
        self.snapshot.next_retry_at_ms = None;
        self.touch(now_ms);
        self.publish_snapshot();

        if self.snapshot.ppp.up {
            self.snapshot.state = NetworkLifecycleState::PppStopping;
            self.touch(now_ms);
            self.publish_snapshot();
            if let Err(error) = self.controller.stop_ppp() {
                let event_error = RuntimeCommandError::from_modem_error(error.clone());
                self.schedule_retry(now_ms, error, NetworkLifecycleState::Degraded);
                return Err(event_error);
            }
            self.clear_ppp();
        }

        if let Err(error) = self.controller.reset() {
            let event_error = RuntimeCommandError::from_modem_error(error.clone());
            self.schedule_retry(now_ms, error, NetworkLifecycleState::Degraded);
            return Err(event_error);
        }

        if let Err(error) = self.attempt_bringup(now_ms) {
            let event_error = RuntimeCommandError::from_modem_error(error.clone());
            self.schedule_retry(now_ms, error, NetworkLifecycleState::Degraded);
            return Err(event_error);
        }

        Ok(())
    }

    fn poll_ppp_health(
        &mut self,
        now_ms: u64,
        explicit_command: bool,
    ) -> Option<RuntimeCommandError> {
        if self.snapshot.state != NetworkLifecycleState::Online {
            self.touch(now_ms);
            return None;
        }

        match self.controller.ppp_health() {
            Ok(PppHealth::Up(link)) => {
                self.apply_online(now_ms, link);
                None
            }
            Ok(PppHealth::ProcessExited) => Some(self.handle_ppp_fault(
                now_ms,
                "ppp_process_exited",
                "PPP process exited",
                explicit_command,
            )),
            Ok(PppHealth::InterfaceDown) => Some(self.handle_ppp_fault(
                now_ms,
                "ppp_interface_down",
                "PPP interface down",
                explicit_command,
            )),
            Err(error) => {
                let event_error = RuntimeCommandError::from_modem_error(error.clone());
                self.schedule_retry(now_ms, error, NetworkLifecycleState::Degraded);
                explicit_command.then_some(event_error)
            }
        }
    }

    fn handle_ppp_fault(
        &mut self,
        now_ms: u64,
        code: &str,
        message: &str,
        explicit_command: bool,
    ) -> RuntimeCommandError {
        self.snapshot.state = NetworkLifecycleState::Registered;
        self.clear_ppp();
        self.snapshot.ppp.last_failure = message.to_string();
        self.schedule_retry(
            now_ms,
            ModemError::retryable(code.to_string(), message.to_string()),
            NetworkLifecycleState::Registered,
        );
        if explicit_command {
            RuntimeCommandError {
                code: code.to_string(),
                message: message.to_string(),
            }
        } else {
            RuntimeCommandError {
                code: String::new(),
                message: String::new(),
            }
        }
    }

    fn attempt_bringup(&mut self, now_ms: u64) -> Result<(), ModemError> {
        self.snapshot.state = NetworkLifecycleState::Probing;
        self.snapshot.recovering = false;
        self.snapshot.retryable = false;
        self.snapshot.next_retry_at_ms = None;
        self.snapshot.error_code.clear();
        self.snapshot.error_message.clear();
        self.touch(now_ms);
        self.publish_snapshot();

        self.controller.open()?;

        match self.controller.probe()? {
            true => {}
            false => {
                return Err(ModemError::retryable(
                    "probe_failed",
                    "Modem probe did not respond",
                ));
            }
        }

        self.snapshot.state = NetworkLifecycleState::Ready;
        self.touch(now_ms);
        self.publish_snapshot();

        self.snapshot.state = NetworkLifecycleState::Registering;
        self.touch(now_ms);
        self.publish_snapshot();

        let registration = self.controller.initialize(self.config.gps_enabled)?;
        self.apply_registration(now_ms, registration);

        self.snapshot.state = NetworkLifecycleState::PppStarting;
        self.touch(now_ms);
        self.publish_snapshot();

        let link = self
            .controller
            .start_ppp(normalized_apn(&self.config.apn), self.config.ppp_timeout)?;
        self.apply_online(now_ms, link);
        Ok(())
    }

    fn refresh_live_facts_if_due(
        &mut self,
        now_ms: u64,
        explicit_command: bool,
    ) -> Result<(), RuntimeCommandError> {
        if !matches!(
            self.snapshot.state,
            NetworkLifecycleState::Online | NetworkLifecycleState::Registered
        ) {
            return Ok(());
        }

        if !explicit_command
            && self
                .last_live_fact_poll_at_ms
                .is_some_and(|last| now_ms.saturating_sub(last) < self.live_fact_poll_interval_ms)
        {
            return Ok(());
        }

        self.last_live_fact_poll_at_ms = Some(now_ms);
        match self.controller.refresh_facts() {
            Ok(facts) => {
                self.apply_live_facts(now_ms, facts);
                Ok(())
            }
            Err(error) => {
                let event_error = RuntimeCommandError::from_modem_error(error.clone());
                self.schedule_retry(now_ms, error, NetworkLifecycleState::Degraded);
                if explicit_command {
                    Err(event_error)
                } else {
                    Ok(())
                }
            }
        }
    }

    fn apply_registration(&mut self, now_ms: u64, registration: ModemRegistration) {
        self.snapshot.state = NetworkLifecycleState::Registered;
        self.apply_fact_fields(registration);
        self.snapshot.error_code.clear();
        self.snapshot.error_message.clear();
        self.touch(now_ms);
        self.publish_snapshot();
    }

    fn apply_live_facts(&mut self, now_ms: u64, facts: ModemRegistration) {
        self.apply_fact_fields(facts);
        self.touch(now_ms);
        self.publish_snapshot();
    }

    fn apply_fact_fields(&mut self, registration: ModemRegistration) {
        self.snapshot.sim_ready = registration.sim_ready;
        self.snapshot.registered = registration.registered;
        self.snapshot.carrier = registration.carrier;
        self.snapshot.network_type = registration.network_type;
        self.snapshot.signal = SignalSnapshot {
            csq: registration.signal_csq,
            bars: registration.signal_csq.map(signal_bars).unwrap_or_default(),
        };
    }

    fn apply_online(&mut self, now_ms: u64, link: PppLink) {
        let was_online = self.snapshot.state == NetworkLifecycleState::Online;
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
        self.snapshot.next_retry_at_ms = None;
        self.snapshot.error_code.clear();
        self.snapshot.error_message.clear();
        if !was_online {
            self.last_live_fact_poll_at_ms = Some(now_ms);
        }
        self.touch(now_ms);
        self.publish_snapshot();
    }

    fn schedule_retry(
        &mut self,
        now_ms: u64,
        error: ModemError,
        fallback_state: NetworkLifecycleState,
    ) {
        self.snapshot.state = fallback_state;
        self.snapshot.recovering = false;
        self.snapshot.retryable = error.retryable;
        self.snapshot.error_code = error.code;
        self.snapshot.error_message = error.message;
        self.snapshot.reconnect_attempts = self.snapshot.reconnect_attempts.saturating_add(1);
        self.snapshot.next_retry_at_ms = error.retryable.then_some(
            now_ms.saturating_add(
                self.recovery_policy
                    .backoff_delay_ms(self.snapshot.reconnect_attempts),
            ),
        );
        self.touch(now_ms);
        self.publish_snapshot();
    }

    fn clear_ppp(&mut self) {
        self.snapshot.ppp = PppSnapshot {
            up: false,
            interface: String::new(),
            pid: None,
            default_route_owned: false,
            last_failure: self.snapshot.ppp.last_failure.clone(),
        };
    }

    fn active_fault_error(&self) -> Option<RuntimeCommandError> {
        let unhealthy = self.snapshot.state == NetworkLifecycleState::Degraded
            || self.snapshot.retryable
            || self.snapshot.recovering;
        if unhealthy && !self.snapshot.error_code.is_empty() {
            Some(RuntimeCommandError {
                code: self.snapshot.error_code.clone(),
                message: self.snapshot.error_message.clone(),
            })
        } else {
            None
        }
    }

    fn touch(&mut self, now_ms: u64) {
        self.snapshot.refresh_derived();
        self.snapshot.updated_at_ms = now_ms;
    }

    fn publish_snapshot(&mut self) {
        let snapshot = self.snapshot.clone();
        if self
            .last_published_snapshot
            .as_ref()
            .is_some_and(|previous| snapshots_equal(previous, &snapshot))
        {
            return;
        }
        self.last_published_snapshot = Some(snapshot.clone());
        self.pending_snapshots.push_back(snapshot);
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
            recovery_policy: RecoveryPolicy::default(),
            live_fact_poll_interval_ms: DEFAULT_LIVE_FACT_POLL_INTERVAL_MS,
            last_live_fact_poll_at_ms: None,
            pending_snapshots: VecDeque::new(),
            last_published_snapshot: None,
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

fn snapshots_equal(previous: &NetworkRuntimeSnapshot, current: &NetworkRuntimeSnapshot) -> bool {
    let mut previous = previous.clone();
    let mut current = current.clone();
    previous.updated_at_ms = 0;
    current.updated_at_ms = 0;
    previous == current
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis() as u64)
        .unwrap_or(0)
}
