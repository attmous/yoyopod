use std::collections::VecDeque;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use serde_json::Value;
use time::format_description::well_known::Rfc3339;
use time::OffsetDateTime;
use uuid::Uuid;

use crate::config::NetworkHostConfig;
use crate::gps::GpsFix;
use crate::modem::{
    ModemController, ModemError, ModemRegistration, NoopModemController, PppHealth, PppLink,
};
use crate::snapshot::{
    GpsSnapshot, NetworkLifecycleState, NetworkRuntimeSnapshot, PppSnapshot, SignalSnapshot,
};
use crate::tracking::{LocationFixEvent, LocationSettings, TrackingEngine};

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
const LOCATION_REQUEST_POLL_INTERVAL: Duration = Duration::from_secs(1);

#[derive(Debug)]
struct PendingLocationRequest {
    command_id: String,
    deadline: Instant,
}

#[derive(Debug)]
pub struct LocationRequestResult {
    pub command_id: String,
    pub result: Result<LocationFixEvent, RuntimeCommandError>,
}

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
    pending_location_events: VecDeque<LocationFixEvent>,
    pending_location_requests: VecDeque<PendingLocationRequest>,
    pending_location_results: VecDeque<LocationRequestResult>,
    last_location_request_poll: Option<Instant>,
    last_published_snapshot: Option<NetworkRuntimeSnapshot>,
    tracking: TrackingEngine,
    voice_suspended: bool,
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
            pending_location_events: VecDeque::new(),
            pending_location_requests: VecDeque::new(),
            pending_location_results: VecDeque::new(),
            last_location_request_poll: None,
            last_published_snapshot: None,
            tracking: TrackingEngine::default(),
            voice_suspended: false,
        }
    }

    pub fn snapshot(&self) -> &NetworkRuntimeSnapshot {
        &self.snapshot
    }

    pub fn voice_suspended(&self) -> bool {
        self.voice_suspended
    }

    /// Quiesce cellular data before handing the shared AT interface to voice.
    /// PPP can drop during dialing; its recovery must never reset that call.
    pub fn suspend_for_voice_command(&mut self) -> Result<(), RuntimeCommandError> {
        if self.voice_suspended {
            return Err(Self::voice_busy_error());
        }
        self.controller
            .suspend_for_voice()
            .map_err(RuntimeCommandError::from_modem_error)?;
        self.voice_suspended = true;
        self.fail_location_requests(Self::voice_busy_error());
        self.clear_ppp();
        self.snapshot.state = if self.snapshot.registered {
            NetworkLifecycleState::Registered
        } else if self.config.enabled {
            NetworkLifecycleState::Ready
        } else {
            NetworkLifecycleState::Off
        };
        self.snapshot.retryable = false;
        self.snapshot.recovering = false;
        self.snapshot.next_retry_at_ms = None;
        self.touch(now_ms());
        self.publish_snapshot();
        Ok(())
    }

    pub fn resume_after_voice(&mut self) {
        if self.voice_suspended {
            self.voice_suspended = false;
            if self.config.enabled {
                let now_ms = now_ms();
                if let Err(error) = self.resume_data_at(now_ms) {
                    self.schedule_retry(now_ms, error, NetworkLifecycleState::Degraded);
                }
            }
        }
    }

    fn resume_data_at(&mut self, now_ms: u64) -> Result<(), ModemError> {
        // Voice only released our AT handle and PPP process. Radio/GNSS are
        // still running; initialize() would enable GNSS again and can turn
        // an already-enabled response into a whole-modem recovery/reset.
        self.snapshot.state = NetworkLifecycleState::Ready;
        self.touch(now_ms);
        self.publish_snapshot();
        self.controller.open()?;
        let registration = self.controller.refresh_facts()?;
        if !registration.sim_ready || !registration.registered {
            self.apply_fact_fields(registration);
            return Err(ModemError::retryable(
                "network_not_registered",
                "Cellular service is not ready after the GSM call",
            ));
        }
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

    fn voice_busy_error() -> RuntimeCommandError {
        RuntimeCommandError {
            code: "gsm_call_in_progress".into(),
            message: "The modem is in use for a GSM call".into(),
        }
    }

    fn require_data_access(&self) -> Result<(), RuntimeCommandError> {
        if self.voice_suspended {
            Err(Self::voice_busy_error())
        } else {
            Ok(())
        }
    }

    pub fn drain_snapshot_events(&mut self) -> Vec<NetworkRuntimeSnapshot> {
        self.pending_snapshots.drain(..).collect()
    }

    pub fn drain_location_events(&mut self) -> Vec<LocationFixEvent> {
        self.pending_location_events.drain(..).collect()
    }

    pub fn drain_location_results(&mut self) -> Vec<LocationRequestResult> {
        self.pending_location_results.drain(..).collect()
    }

    pub fn start(&mut self) -> &NetworkRuntimeSnapshot {
        self.start_at(now_ms())
    }

    pub fn start_at(&mut self, now_ms: u64) -> &NetworkRuntimeSnapshot {
        if self.voice_suspended {
            self.touch(now_ms);
            return &self.snapshot;
        }
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
        if self.voice_suspended {
            self.touch(now_ms);
            return &self.snapshot;
        }
        if self.snapshot.state == NetworkLifecycleState::Online {
            let _ = self.poll_ppp_health(now_ms, false);
            let _ = self.refresh_live_facts_if_due(now_ms, false);
        }
        let acquiring_location = !self.pending_location_requests.is_empty();
        self.poll_location_requests_at(now_ms, Instant::now());
        if !acquiring_location {
            self.sample_location_if_due(now_ms);
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
        self.require_data_access()?;
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
        self.require_data_access()?;
        if !self.config.gps_enabled {
            self.snapshot.gps.last_query_result = "disabled".to_string();
            self.touch(now_ms());
            self.publish_snapshot();
            return Ok(&self.snapshot);
        }

        self.read_gps_fix_at(now_ms())?;
        Ok(&self.snapshot)
    }

    pub fn apply_location_settings_command(
        &mut self,
        payload: &Value,
    ) -> Result<LocationSettings, RuntimeCommandError> {
        let settings =
            LocationSettings::from_cloud_config(payload).map_err(|code| RuntimeCommandError {
                code: code.to_string(),
                message: "Location tracking settings are invalid".to_string(),
            })?;
        self.tracking.apply_settings(settings);
        Ok(settings)
    }

    pub fn request_location_command(
        &mut self,
        command_id: String,
        timeout: Duration,
    ) -> Result<(), RuntimeCommandError> {
        self.request_location_at(command_id, timeout, Instant::now())
    }

    fn request_location_at(
        &mut self,
        command_id: String,
        timeout: Duration,
        now: Instant,
    ) -> Result<(), RuntimeCommandError> {
        self.require_data_access()?;
        if !self.config.enabled {
            return Err(RuntimeCommandError {
                code: "network_disabled".to_string(),
                message: "Cellular networking is disabled".to_string(),
            });
        }
        if !self.config.gps_enabled {
            return Err(RuntimeCommandError {
                code: "gps_disabled".to_string(),
                message: "GNSS is disabled".to_string(),
            });
        }
        if self
            .pending_location_requests
            .iter()
            .any(|request| request.command_id == command_id)
        {
            return Err(RuntimeCommandError {
                code: "location_request_pending".to_string(),
                message: "This location request is already pending".to_string(),
            });
        }
        if self.pending_location_requests.is_empty() {
            self.last_location_request_poll = None;
        }
        self.pending_location_requests
            .push_back(PendingLocationRequest {
                command_id,
                deadline: now + timeout,
            });
        Ok(())
    }

    fn poll_location_requests_at(&mut self, now_ms: u64, now: Instant) {
        // Acquisition spans worker ticks. Never wait/sleep for a fix here:
        // stdin must remain available for call controls and other commands.
        let mut pending = VecDeque::new();
        for request in self.pending_location_requests.drain(..) {
            if now >= request.deadline {
                self.pending_location_results
                    .push_back(LocationRequestResult {
                        command_id: request.command_id,
                        result: Err(RuntimeCommandError {
                            code: "gps_fix_timeout".to_string(),
                            message: "No valid GNSS fix was acquired before the request timed out"
                                .to_string(),
                        }),
                    });
            } else {
                pending.push_back(request);
            }
        }
        self.pending_location_requests = pending;
        if self.pending_location_requests.is_empty()
            || self.voice_suspended
            || self.last_location_request_poll.is_some_and(|last| {
                now.saturating_duration_since(last) < LOCATION_REQUEST_POLL_INTERVAL
            })
        {
            return;
        }
        self.last_location_request_poll = Some(now);
        match self.read_gps_fix_at(now_ms) {
            Ok(Some(fix)) => {
                for request in self.pending_location_requests.drain(..) {
                    self.pending_location_results
                        .push_back(LocationRequestResult {
                            command_id: request.command_id.clone(),
                            result: Ok(LocationFixEvent::from_gps(
                                &fix,
                                Uuid::new_v4().to_string(),
                                "on_demand",
                                Some(request.command_id),
                                current_rfc3339(),
                            )),
                        });
                }
            }
            Ok(None) => {}
            Err(error) => self.fail_location_requests(error),
        }
    }

    pub fn poll_location_requests(&mut self) {
        self.poll_location_requests_at(now_ms(), Instant::now());
    }

    fn fail_location_requests(&mut self, error: RuntimeCommandError) {
        for request in self.pending_location_requests.drain(..) {
            self.pending_location_results
                .push_back(LocationRequestResult {
                    command_id: request.command_id,
                    result: Err(error.clone()),
                });
        }
    }

    pub fn reset_modem(&mut self) -> &NetworkRuntimeSnapshot {
        let _ = self.reset_modem_command();
        &self.snapshot
    }

    pub fn reset_modem_command(&mut self) -> Result<&NetworkRuntimeSnapshot, RuntimeCommandError> {
        self.require_data_access()?;
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
        self.fail_location_requests(RuntimeCommandError {
            code: "network_stopped".to_string(),
            message: "The network worker stopped before acquiring a location".to_string(),
        });
        self.voice_suspended = false;
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
        eprintln!("Cellular data recovery scheduled: {}", error.code);
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
            pending_location_events: VecDeque::new(),
            pending_location_requests: VecDeque::new(),
            pending_location_results: VecDeque::new(),
            last_location_request_poll: None,
            last_published_snapshot: None,
            tracking: TrackingEngine::default(),
            voice_suspended: false,
        }
    }
}

impl<C> NetworkRuntime<C>
where
    C: ModemController,
{
    fn read_gps_fix_at(&mut self, now_ms: u64) -> Result<Option<GpsFix>, RuntimeCommandError> {
        match self.controller.query_gps() {
            Ok(Some(fix)) => {
                self.snapshot.gps = GpsSnapshot {
                    has_fix: true,
                    lat: Some(fix.lat),
                    lng: Some(fix.lng),
                    altitude: Some(fix.altitude),
                    speed: Some(fix.speed),
                    timestamp: fix.timestamp.clone(),
                    last_query_result: "fix".to_string(),
                };
                self.touch(now_ms);
                self.publish_snapshot();
                Ok(Some(fix))
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
                Ok(None)
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

    fn sample_location_if_due(&mut self, now_ms: u64) {
        if !self.config.enabled || !self.tracking.sample_due(now_ms) || !self.config.gps_enabled {
            return;
        }
        match self.read_gps_fix_at(now_ms) {
            Ok(Some(fix)) => {
                if self.tracking.observe(&fix, now_ms) {
                    self.pending_location_events
                        .push_back(LocationFixEvent::from_gps(
                            &fix,
                            Uuid::new_v4().to_string(),
                            "periodic",
                            None,
                            current_rfc3339(),
                        ));
                }
            }
            Ok(None) | Err(_) => self.tracking.record_no_fix(now_ms),
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

fn current_rfc3339() -> String {
    OffsetDateTime::now_utc()
        .format(&Rfc3339)
        .unwrap_or_else(|_| "1970-01-01T00:00:00Z".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Default)]
    struct RecordingController {
        calls: Vec<&'static str>,
        fail_suspend: bool,
        unregistered: bool,
        gps_results: VecDeque<Result<Option<GpsFix>, ModemError>>,
    }

    impl ModemController for RecordingController {
        fn open(&mut self) -> Result<(), ModemError> {
            self.calls.push("open");
            Ok(())
        }
        fn close(&mut self) -> Result<(), ModemError> {
            self.calls.push("close/ATH");
            Ok(())
        }
        fn probe(&mut self) -> Result<bool, ModemError> {
            self.calls.push("probe");
            Ok(true)
        }
        fn initialize(&mut self, _: bool) -> Result<ModemRegistration, ModemError> {
            self.calls.push("initialize");
            Ok(ModemRegistration {
                sim_ready: true,
                registered: !self.unregistered,
                carrier: "Test".into(),
                network_type: "LTE".into(),
                signal_csq: Some(26),
            })
        }
        fn refresh_facts(&mut self) -> Result<ModemRegistration, ModemError> {
            self.calls.push("facts");
            Ok(ModemRegistration {
                sim_ready: true,
                registered: !self.unregistered,
                carrier: "Test".into(),
                network_type: "LTE".into(),
                signal_csq: Some(26),
            })
        }
        fn start_ppp(&mut self, _: Option<&str>, _: u64) -> Result<PppLink, ModemError> {
            self.calls.push("start_ppp");
            Ok(PppLink {
                interface: "ppp0".into(),
                pid: Some(123),
                default_route_owned: false,
            })
        }
        fn stop_ppp(&mut self) -> Result<(), ModemError> {
            self.calls.push("stop_ppp");
            Ok(())
        }
        fn ppp_health(&mut self) -> Result<PppHealth, ModemError> {
            self.calls.push("ppp_health");
            Ok(PppHealth::ProcessExited)
        }
        fn query_gps(&mut self) -> Result<Option<GpsFix>, ModemError> {
            self.calls.push("gps");
            self.gps_results.pop_front().unwrap_or(Ok(None))
        }
        fn reset(&mut self) -> Result<(), ModemError> {
            self.calls.push("reset/CFUN");
            Ok(())
        }
        fn suspend_for_voice(&mut self) -> Result<(), ModemError> {
            self.calls.push("suspend/release_AT");
            if self.fail_suspend {
                Err(ModemError::retryable("stop_failed", "PPP did not stop"))
            } else {
                Ok(())
            }
        }
    }

    #[test]
    fn location_acquisition_returns_control_before_gsm_handoff() {
        let config = NetworkHostConfig {
            enabled: true,
            gps_enabled: true,
            ..Default::default()
        };
        let mut runtime = NetworkRuntime::new("config", config, RecordingController::default());
        let result =
            runtime.request_location_command("location-1".into(), Duration::from_millis(1));
        assert!(
            result.is_ok(),
            "location acquisition must be queued, not awaited: {result:?}"
        );
        assert!(
            runtime.controller.calls.is_empty(),
            "enqueuing a location must not query GNSS"
        );
        runtime.suspend_for_voice_command().unwrap();
        assert_eq!(runtime.controller.calls, ["suspend/release_AT"]);
        let results = runtime.drain_location_results();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].command_id, "location-1");
        assert_eq!(
            results[0].result.as_ref().unwrap_err().code,
            "gsm_call_in_progress"
        );
        runtime.tick_at(u64::MAX);
        assert_eq!(runtime.controller.calls, ["suspend/release_AT"]);
        assert!(runtime.drain_location_results().is_empty());
    }

    fn location_runtime() -> NetworkRuntime<RecordingController> {
        NetworkRuntime::new(
            "config",
            NetworkHostConfig {
                enabled: true,
                gps_enabled: true,
                ..Default::default()
            },
            RecordingController::default(),
        )
    }

    #[test]
    fn location_ticks_retry_at_one_second_and_timeout_each_request_once() {
        let mut runtime = location_runtime();
        let now = Instant::now();
        runtime
            .request_location_at(
                "first".into(),
                Duration::from_secs(90),
                now + Duration::from_secs(1),
            )
            .unwrap();
        runtime
            .request_location_at(
                "second".into(),
                Duration::from_secs(90),
                now + Duration::from_secs(2),
            )
            .unwrap();
        for time in [2_000, 2_100, 2_999, 3_000] {
            runtime.poll_location_requests_at(time, now + Duration::from_millis(time));
        }
        assert_eq!(runtime.controller.calls, ["gps", "gps"]);
        assert!(runtime.drain_location_results().is_empty());
        runtime.poll_location_requests_at(91_000, now + Duration::from_millis(91_000));
        let results = runtime.drain_location_results();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].command_id, "first");
        assert_eq!(
            results[0].result.as_ref().unwrap_err().code,
            "gps_fix_timeout"
        );
        runtime.poll_location_requests_at(92_000, now + Duration::from_millis(92_000));
        let results = runtime.drain_location_results();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].command_id, "second");
        assert_eq!(
            results[0].result.as_ref().unwrap_err().code,
            "gps_fix_timeout"
        );
        runtime.poll_location_requests_at(93_000, now + Duration::from_millis(93_000));
        assert!(runtime.drain_location_results().is_empty());
    }

    #[test]
    fn location_fix_completes_all_pending_requests_with_distinct_correlated_fixes() {
        let mut runtime = location_runtime();
        let now = Instant::now();
        runtime.controller.gps_results.push_back(Ok(None));
        runtime.controller.gps_results.push_back(Ok(Some(GpsFix {
            lat: 52.5,
            lng: 13.4,
            altitude: 40.0,
            speed: 0.0,
            timestamp: None,
        })));
        for id in ["first", "second"] {
            runtime
                .request_location_at(
                    id.into(),
                    Duration::from_secs(90),
                    now + Duration::from_secs(1),
                )
                .unwrap();
        }
        runtime.poll_location_requests_at(1_000, now + Duration::from_millis(1_000));
        assert!(runtime.drain_location_results().is_empty());
        runtime.poll_location_requests_at(2_000, now + Duration::from_millis(2_000));
        let results = runtime.drain_location_results();
        assert_eq!(results.len(), 2);
        for (result, id) in results.iter().zip(["first", "second"]) {
            let fix = result.result.as_ref().unwrap();
            assert_eq!(result.command_id, id);
            assert_eq!(fix.command_id.as_deref(), Some(id));
            assert_eq!(fix.reason, "on_demand");
            assert_eq!(fix.latitude, 52.5);
        }
        assert_ne!(
            results[0].result.as_ref().unwrap().fix_id,
            results[1].result.as_ref().unwrap().fix_id
        );
        runtime.poll_location_requests_at(3_000, now + Duration::from_millis(3_000));
        assert!(runtime.drain_location_results().is_empty());
        assert_eq!(runtime.controller.calls, ["gps", "gps"]);
    }

    #[test]
    fn pending_location_failures_remain_correlated_for_modem_error_and_shutdown() {
        let mut runtime = location_runtime();
        let now = Instant::now();
        runtime
            .request_location_at(
                "modem-error".into(),
                Duration::from_secs(90),
                now + Duration::from_secs(1),
            )
            .unwrap();
        runtime
            .controller
            .gps_results
            .push_back(Err(ModemError::fatal("serial_error", "AT failed")));
        runtime.poll_location_requests_at(1_000, now + Duration::from_millis(1_000));
        let results = runtime.drain_location_results();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].command_id, "modem-error");
        assert_eq!(results[0].result.as_ref().unwrap_err().code, "serial_error");
        runtime
            .request_location_at(
                "shutdown".into(),
                Duration::from_secs(90),
                now + Duration::from_secs(2),
            )
            .unwrap();
        runtime.shutdown_at(2_100);
        let results = runtime.drain_location_results();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].command_id, "shutdown");
        assert_eq!(
            results[0].result.as_ref().unwrap_err().code,
            "network_stopped"
        );
        assert!(runtime.drain_location_results().is_empty());
    }

    #[test]
    fn disabled_gnss_and_duplicate_location_requests_are_rejected_without_io() {
        let mut runtime = location_runtime();
        let now = Instant::now();
        runtime
            .request_location_at(
                "first".into(),
                Duration::from_secs(90),
                now + Duration::from_secs(1),
            )
            .unwrap();
        assert_eq!(
            runtime
                .request_location_at(
                    "first".into(),
                    Duration::from_secs(90),
                    now + Duration::from_secs(1)
                )
                .unwrap_err()
                .code,
            "location_request_pending"
        );
        runtime.config.gps_enabled = false;
        assert_eq!(
            runtime
                .request_location_at(
                    "disabled-gps".into(),
                    Duration::from_secs(90),
                    now + Duration::from_secs(1)
                )
                .unwrap_err()
                .code,
            "gps_disabled"
        );
        runtime.config.enabled = false;
        assert_eq!(
            runtime
                .request_location_at(
                    "disabled-network".into(),
                    Duration::from_secs(90),
                    now + Duration::from_secs(1)
                )
                .unwrap_err()
                .code,
            "network_disabled"
        );
        assert!(runtime.controller.calls.is_empty());
    }

    #[test]
    fn disabled_cellular_runtime_does_not_query_gnss_on_worker_ticks() {
        let config = NetworkHostConfig {
            enabled: false,
            gps_enabled: true,
            ..Default::default()
        };
        let mut runtime = NetworkRuntime::new("config", config, RecordingController::default());
        runtime.start_at(1_000);
        for time in [1_100, 31_100, 61_100] {
            runtime.tick_at(time);
        }
        assert!(runtime.controller.calls.is_empty());
        assert!(runtime.snapshot.error_code.is_empty());
        assert!(runtime.drain_location_events().is_empty());
    }

    #[test]
    fn voice_pause_blocks_pending_recovery_and_all_modem_io_until_resume() {
        let config = NetworkHostConfig {
            enabled: true,
            ..Default::default()
        };
        let mut runtime = NetworkRuntime::new("config", config, RecordingController::default());
        runtime.start_at(1_000);
        runtime.tick_at(1_100); // Lost PPP schedules recovery, as during a real call.
        assert!(runtime.snapshot.retryable);
        runtime.controller.calls.clear();

        runtime.suspend_for_voice_command().unwrap();
        assert!(!runtime.snapshot.ppp.up);
        assert!(!runtime.snapshot.retryable);
        assert!(runtime.snapshot.next_retry_at_ms.is_none());
        assert_eq!(runtime.snapshot.state, NetworkLifecycleState::Registered);
        for time in [2_100, 61_100, 120_000] {
            runtime.tick_at(time);
        }
        runtime.start_at(130_000);
        assert!(runtime.health_command().is_err());
        assert!(runtime.query_gps_command().is_err());
        assert!(runtime
            .request_location_command("test".into(), Duration::ZERO)
            .is_err());
        assert!(runtime.reset_modem_command().is_err());
        assert!(runtime.suspend_for_voice_command().is_err()); // Repeated dial.
        assert_eq!(runtime.controller.calls, ["suspend/release_AT"]);

        runtime.resume_after_voice();
        assert!(!runtime.voice_suspended());
        assert!(runtime.snapshot.ppp.up);
        assert_eq!(runtime.snapshot.state, NetworkLifecycleState::Online);
        assert_eq!(
            runtime.controller.calls,
            ["suspend/release_AT", "open", "facts", "start_ppp"]
        );
        runtime.resume_after_voice();
        assert_eq!(runtime.controller.calls.len(), 4); // Restore data once.
    }

    #[test]
    fn voice_resume_preserves_disabled_cellular_policy() {
        let mut runtime = NetworkRuntime::new(
            "config",
            NetworkHostConfig::default(),
            RecordingController::default(),
        );
        runtime.suspend_for_voice_command().unwrap();
        runtime.tick_at(60_000);
        runtime.resume_after_voice();
        assert!(!runtime.voice_suspended());
        assert_eq!(runtime.snapshot.state, NetworkLifecycleState::Off);
        assert_eq!(runtime.controller.calls, ["suspend/release_AT"]);
    }

    #[test]
    fn failed_voice_handoff_does_not_acquire_the_modem() {
        let controller = RecordingController {
            fail_suspend: true,
            ..Default::default()
        };
        let mut runtime = NetworkRuntime::new("config", NetworkHostConfig::default(), controller);
        assert!(runtime.suspend_for_voice_command().is_err());
        assert!(!runtime.voice_suspended());
    }

    #[test]
    fn lost_registration_after_voice_schedules_data_retry_without_starting_ppp() {
        let config = NetworkHostConfig {
            enabled: true,
            ..Default::default()
        };
        let mut runtime = NetworkRuntime::new("config", config, RecordingController::default());
        runtime.start_at(1_000);
        runtime.suspend_for_voice_command().unwrap();
        runtime.controller.calls.clear();
        runtime.controller.unregistered = true;
        runtime.resume_after_voice();
        assert!(!runtime.voice_suspended());
        assert!(!runtime.snapshot.ppp.up);
        assert!(!runtime.snapshot.registered);
        assert!(runtime.snapshot.retryable);
        assert_eq!(runtime.snapshot.error_code, "network_not_registered");
        assert_eq!(runtime.controller.calls, ["open", "facts"]);
    }
}
