#![allow(dead_code)]

use std::collections::VecDeque;
use std::io::{self, Read};
use std::sync::{Arc, Condvar, Mutex};
use std::time::Duration;

use serde_json::Value;

use yoyopod_network_host::config::NetworkHostConfig;
use yoyopod_network_host::gps::GpsFix;
use yoyopod_network_host::modem::{
    ModemController, ModemError, ModemRegistration, PppHealth, PppLink,
};
use yoyopod_network_host::protocol::{EnvelopeKind, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};

#[derive(Debug, Clone)]
pub struct FakeModemController {
    inner: Arc<Mutex<FakeModemState>>,
}

#[derive(Debug, Clone)]
pub struct FakeModemState {
    pub probe_results: VecDeque<Result<bool, ModemError>>,
    pub init_results: VecDeque<Result<ModemRegistration, ModemError>>,
    pub live_fact_results: VecDeque<Result<ModemRegistration, ModemError>>,
    pub ppp_results: VecDeque<Result<PppLink, ModemError>>,
    pub ppp_health_results: VecDeque<PppHealth>,
    pub gps_results: VecDeque<Result<Option<GpsFix>, ModemError>>,
    pub reset_results: VecDeque<Result<(), ModemError>>,
    pub open_calls: usize,
    pub close_calls: usize,
    pub query_gps_calls: usize,
    pub refresh_facts_calls: usize,
    pub stop_ppp_calls: usize,
    pub reset_calls: usize,
    pub start_ppp_apns: Vec<Option<String>>,
}

impl Default for FakeModemState {
    fn default() -> Self {
        Self {
            probe_results: VecDeque::from([Ok(true)]),
            init_results: VecDeque::from([Ok(registered_modem())]),
            live_fact_results: VecDeque::from([Ok(registered_modem())]),
            ppp_results: VecDeque::from([Ok(ppp_link())]),
            ppp_health_results: VecDeque::from([PppHealth::Up(ppp_link())]),
            gps_results: VecDeque::from([Ok(None)]),
            reset_results: VecDeque::from([Ok(())]),
            open_calls: 0,
            close_calls: 0,
            query_gps_calls: 0,
            refresh_facts_calls: 0,
            stop_ppp_calls: 0,
            reset_calls: 0,
            start_ppp_apns: Vec::new(),
        }
    }
}

impl FakeModemController {
    pub fn new() -> Self {
        Self {
            inner: Arc::new(Mutex::new(FakeModemState::default())),
        }
    }

    pub fn state(&self) -> FakeModemState {
        self.inner.lock().expect("fake modem lock").clone()
    }

    pub fn set_probe_results(&self, results: impl IntoIterator<Item = Result<bool, ModemError>>) {
        self.inner.lock().expect("fake modem lock").probe_results = results.into_iter().collect();
    }

    pub fn set_init_results(
        &self,
        results: impl IntoIterator<Item = Result<ModemRegistration, ModemError>>,
    ) {
        self.inner.lock().expect("fake modem lock").init_results = results.into_iter().collect();
    }

    pub fn set_ppp_results(&self, results: impl IntoIterator<Item = Result<PppLink, ModemError>>) {
        self.inner.lock().expect("fake modem lock").ppp_results = results.into_iter().collect();
    }

    pub fn set_live_fact_results(
        &self,
        results: impl IntoIterator<Item = Result<ModemRegistration, ModemError>>,
    ) {
        self.inner
            .lock()
            .expect("fake modem lock")
            .live_fact_results = results.into_iter().collect();
    }

    pub fn set_ppp_health_results(&self, results: impl IntoIterator<Item = PppHealth>) {
        self.inner
            .lock()
            .expect("fake modem lock")
            .ppp_health_results = results.into_iter().collect();
    }

    pub fn set_gps_results(
        &self,
        results: impl IntoIterator<Item = Result<Option<GpsFix>, ModemError>>,
    ) {
        self.inner.lock().expect("fake modem lock").gps_results = results.into_iter().collect();
    }

    pub fn set_reset_results(&self, results: impl IntoIterator<Item = Result<(), ModemError>>) {
        self.inner.lock().expect("fake modem lock").reset_results = results.into_iter().collect();
    }
}

impl Default for FakeModemController {
    fn default() -> Self {
        Self::new()
    }
}

impl ModemController for FakeModemController {
    fn open(&mut self) -> Result<(), ModemError> {
        self.inner.lock().expect("fake modem lock").open_calls += 1;
        Ok(())
    }

    fn close(&mut self) -> Result<(), ModemError> {
        self.inner.lock().expect("fake modem lock").close_calls += 1;
        Ok(())
    }

    fn probe(&mut self) -> Result<bool, ModemError> {
        self.inner
            .lock()
            .expect("fake modem lock")
            .probe_results
            .pop_front()
            .unwrap_or(Ok(true))
    }

    fn initialize(&mut self, _gps_enabled: bool) -> Result<ModemRegistration, ModemError> {
        self.inner
            .lock()
            .expect("fake modem lock")
            .init_results
            .pop_front()
            .unwrap_or_else(|| Ok(registered_modem()))
    }

    fn start_ppp(&mut self, apn: Option<&str>, _timeout_secs: u64) -> Result<PppLink, ModemError> {
        self.inner
            .lock()
            .expect("fake modem lock")
            .start_ppp_apns
            .push(apn.map(str::to_string));
        self.inner
            .lock()
            .expect("fake modem lock")
            .ppp_results
            .pop_front()
            .unwrap_or_else(|| Ok(ppp_link()))
    }

    fn stop_ppp(&mut self) -> Result<(), ModemError> {
        self.inner.lock().expect("fake modem lock").stop_ppp_calls += 1;
        Ok(())
    }

    fn ppp_health(&mut self) -> Result<PppHealth, ModemError> {
        Ok(self
            .inner
            .lock()
            .expect("fake modem lock")
            .ppp_health_results
            .pop_front()
            .unwrap_or_else(|| PppHealth::Up(ppp_link())))
    }

    fn refresh_facts(&mut self) -> Result<ModemRegistration, ModemError> {
        let mut inner = self.inner.lock().expect("fake modem lock");
        inner.refresh_facts_calls += 1;
        inner
            .live_fact_results
            .pop_front()
            .unwrap_or_else(|| Ok(registered_modem()))
    }

    fn query_gps(&mut self) -> Result<Option<GpsFix>, ModemError> {
        let mut inner = self.inner.lock().expect("fake modem lock");
        inner.query_gps_calls += 1;
        inner.gps_results.pop_front().unwrap_or(Ok(None))
    }

    fn reset(&mut self) -> Result<(), ModemError> {
        let mut inner = self.inner.lock().expect("fake modem lock");
        inner.reset_calls += 1;
        inner.reset_results.pop_front().unwrap_or(Ok(()))
    }
}

pub fn enabled_config() -> NetworkHostConfig {
    NetworkHostConfig {
        enabled: true,
        apn: "internet".to_string(),
        gps_enabled: true,
        ..NetworkHostConfig::default()
    }
}

pub fn disabled_config() -> NetworkHostConfig {
    NetworkHostConfig {
        enabled: false,
        gps_enabled: false,
        ..NetworkHostConfig::default()
    }
}

pub fn blank_apn_config() -> NetworkHostConfig {
    NetworkHostConfig {
        enabled: true,
        apn: "   ".to_string(),
        gps_enabled: false,
        ..NetworkHostConfig::default()
    }
}

pub fn registered_modem() -> ModemRegistration {
    ModemRegistration {
        sim_ready: true,
        registered: true,
        carrier: "T-Mobile".to_string(),
        network_type: "4G".to_string(),
        signal_csq: Some(20),
    }
}

pub fn roaming_modem() -> ModemRegistration {
    ModemRegistration {
        sim_ready: true,
        registered: true,
        carrier: "Vodafone".to_string(),
        network_type: "3G".to_string(),
        signal_csq: Some(9),
    }
}

pub fn unregistered_modem() -> ModemRegistration {
    ModemRegistration {
        sim_ready: true,
        registered: false,
        carrier: "Vodafone".to_string(),
        network_type: "3G".to_string(),
        signal_csq: Some(9),
    }
}

pub fn ppp_link() -> PppLink {
    PppLink {
        interface: "ppp0".to_string(),
        pid: Some(4242),
        default_route_owned: true,
    }
}

pub fn berlin_fix() -> GpsFix {
    GpsFix {
        lat: 52.52,
        lng: 13.405,
        altitude: 38.0,
        speed: 0.5,
        timestamp: Some("2026-04-30T12:00:00Z".to_string()),
    }
}

pub fn retryable_error(code: &str, message: &str) -> ModemError {
    ModemError::retryable(code, message)
}

pub fn fatal_error(code: &str, message: &str) -> ModemError {
    ModemError::fatal(code, message)
}

pub fn command(message_type: &str, request_id: &str, payload: Value) -> WorkerEnvelope {
    WorkerEnvelope {
        schema_version: SUPPORTED_SCHEMA_VERSION,
        kind: EnvelopeKind::Command,
        message_type: message_type.to_string(),
        request_id: Some(request_id.to_string()),
        timestamp_ms: 0,
        deadline_ms: 0,
        payload,
    }
}

pub fn encode_commands(commands: &[WorkerEnvelope]) -> Vec<u8> {
    commands
        .iter()
        .flat_map(|command| command.encode().expect("command should encode"))
        .collect()
}

pub fn decode_output(output: &[u8]) -> Vec<WorkerEnvelope> {
    String::from_utf8(output.to_vec())
        .expect("worker output should be utf8")
        .lines()
        .map(|line| WorkerEnvelope::decode(line.as_bytes()).expect("decode worker output"))
        .collect()
}

#[derive(Clone)]
pub struct ControlledInputHandle {
    shared: Arc<(Mutex<ControlledInputState>, Condvar)>,
}

pub struct ControlledInput {
    shared: Arc<(Mutex<ControlledInputState>, Condvar)>,
}

#[derive(Default)]
struct ControlledInputState {
    buffer: VecDeque<u8>,
    closed: bool,
}

pub fn controlled_input() -> (ControlledInput, ControlledInputHandle) {
    let shared = Arc::new((Mutex::new(ControlledInputState::default()), Condvar::new()));
    (
        ControlledInput {
            shared: Arc::clone(&shared),
        },
        ControlledInputHandle { shared },
    )
}

impl ControlledInputHandle {
    pub fn send(&self, envelope: &WorkerEnvelope) {
        let (lock, condvar) = &*self.shared;
        let mut state = lock.lock().expect("controlled input lock");
        state.buffer.extend(
            envelope
                .encode()
                .expect("command should encode")
                .into_iter(),
        );
        condvar.notify_all();
    }

    pub fn close(&self) {
        let (lock, condvar) = &*self.shared;
        let mut state = lock.lock().expect("controlled input lock");
        state.closed = true;
        condvar.notify_all();
    }

    pub fn sleep(&self, duration: Duration) {
        std::thread::sleep(duration);
    }
}

impl Read for ControlledInput {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        let (lock, condvar) = &*self.shared;
        let mut state = lock.lock().expect("controlled input lock");
        loop {
            if !state.buffer.is_empty() {
                let mut count = 0;
                while count < buf.len() {
                    let Some(byte) = state.buffer.pop_front() else {
                        break;
                    };
                    buf[count] = byte;
                    count += 1;
                }
                return Ok(count);
            }
            if state.closed {
                return Ok(0);
            }
            state = condvar.wait(state).expect("controlled input condvar");
        }
    }
}
