use std::collections::HashMap;
use std::sync::mpsc::{self, Receiver, Sender};
use std::sync::{
    atomic::{AtomicU64, Ordering},
    Arc,
};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use crate::gsm_calls::CallManagerWireEvent;
use anyhow::{bail, Context, Result};
use serde::Serialize;
use yoyopod_protocol::call::{CallCommand, CallPhase, SessionKey};
use zbus::blocking::{connection::Builder, Connection, Proxy};
use zbus::fdo::ManagedObjects;
use zvariant::OwnedObjectPath;

#[cfg(test)]
use crate::gsm_audio::UsbPcmAudio;
use crate::gsm_pcm::{ActivePcm, PcmAdapter, PreparedPcm};
use crate::gsm_provider::VerifiedPcm;

const DESTINATION: &str = "org.freedesktop.ModemManager1";
const MODEM_INTERFACE: &str = "org.freedesktop.ModemManager1.Modem";
const VOICE_INTERFACE: &str = "org.freedesktop.ModemManager1.Modem.Voice";
const CALL_INTERFACE: &str = "org.freedesktop.ModemManager1.Call";

fn audio_inventory_contains(ports: &[(String, u32)], audio_port: &str) -> bool {
    let name = audio_port.strip_prefix("/dev/").unwrap_or(audio_port);
    !name.is_empty()
        && !name.contains('/')
        && ports
            .iter()
            .any(|(port, kind)| *kind == 8 && port.strip_prefix("/dev/").unwrap_or(port) == name)
}

// MM 1.24's generic AT implementation falls back to global +CHUP. Only the
// pinned SIMTech QMI class has verified source-level per-native-ID termination.
fn isolated_voice_backend(
    version: &str,
    model: &str,
    plugin: &str,
    primary: &str,
    ports: &[(String, u32)],
) -> bool {
    version == "1.24.0"
        && model.contains("SIM7600")
        && plugin == "simtech"
        && ports
            .iter()
            .any(|(name, kind)| name == primary && *kind == 6)
}

fn modem_call_phase(state: i32) -> CallPhase {
    match state {
        1 | 2 => CallPhase::Outgoing,
        3 => CallPhase::Ringing,
        4 => CallPhase::Active,
        5 => CallPhase::Held,
        6 => CallPhase::Waiting,
        7 => CallPhase::Ended,
        _ => CallPhase::Preparing,
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GsmCallState {
    pub available: bool,
    pub unavailable_reason: String,
    pub state: String,
    pub peer_number: String,
    pub duration_seconds: u64,
    pub muted: bool,
}

impl Default for GsmCallState {
    fn default() -> Self {
        Self {
            available: false,
            unavailable_reason: "Unavailable".into(),
            state: "idle".into(),
            peer_number: String::new(),
            duration_seconds: 0,
            muted: false,
        }
    }
}

pub enum GsmCommand {
    Configure {
        request_id: String,
        generation: u64,
        pcm_sample_rate_hz: Option<u32>,
    },
    Action {
        request_id: String,
        command: CallCommand,
    },
    DialSession {
        request_id: String,
        key: SessionKey,
        number: String,
    },
    Dial(String),
    Hangup,
    Mute(bool),
    Stop,
}

#[derive(Debug)]
pub enum GsmEvent {
    Call(CallManagerWireEvent),
    Reconciled(GsmReconciliation),
    ModemLost {
        generation: u64,
    },
    Completed {
        request_id: String,
        key: SessionKey,
        error: Option<String>,
        voice_held: bool,
    },
    Configured {
        request_id: String,
        generation: u64,
        error: Option<String>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct GsmReconciliation {
    pub generation: u64,
    pub admission_epoch: u64,
    pub native_owner: Option<String>,
    pub native_calls_quiescent: bool,
    pub audio_released: bool,
}

pub struct GsmObservation {
    pub availability: GsmCallState,
    pub calls: Vec<CallManagerWireEvent>,
}

/// ModemManager owns modem discovery and call control; the network worker never
/// competes with its QMI control channel or hard-codes a transient modem index.
pub trait GsmBackend: Send + 'static {
    fn selected_modem_epoch(&self) -> u64 {
        0
    }
    fn take_modem_loss(&mut self) -> Option<u64> {
        None
    }
    fn refresh_observation(&mut self) -> Result<GsmObservation> {
        let availability = self.refresh()?;
        Ok(GsmObservation {
            availability,
            calls: self.drain_call_events(),
        })
    }
    fn reconciliation(&self) -> Option<GsmReconciliation> {
        None
    }
    fn refresh(&mut self) -> Result<GsmCallState>;
    fn dial(&mut self, number: &str) -> Result<()>;
    fn hangup(&mut self) -> Result<()>;
    fn mute(&mut self, muted: bool) -> Result<()>;
    fn configure(&mut self, _generation: u64, _pcm_sample_rate_hz: Option<u32>) -> Result<()> {
        Ok(())
    }
    fn owns_voice(&self, _key: &SessionKey) -> bool {
        false
    }
    fn apply_call(&mut self, _command: &CallCommand) -> Result<()> {
        bail!("Session control unavailable")
    }
    fn apply_call_with_request(&mut self, _request_id: &str, command: &CallCommand) -> Result<()> {
        self.apply_call(command)
    }
    fn dial_session(&mut self, _key: &SessionKey, _number: &str) -> Result<()> {
        bail!("Session dialing unavailable")
    }
    fn drain_call_events(&mut self) -> Vec<CallManagerWireEvent> {
        Vec::new()
    }
}

// Per-action diagnostics only: no polling, modem reads, or protocol output.
// Identity comes from cached registry/owner facts; JSON escapes native errors.
struct GsmActionDiagnostic<'a> {
    request_id: &'a str,
    command: &'a CallCommand,
    native_id: Option<String>,
    native_owner: Option<String>,
    // None at the worker boundary: only the native backend knows dispatch.
    native_accept_dispatched: Option<bool>,
}

impl GsmActionDiagnostic<'_> {
    fn record(&self, stage: &str, outcome: &str, error: Option<&anyhow::Error>) {
        eprintln!(
            "{}",
            serde_json::json!({
                "event": "gsm_action",
                "request_id": self.request_id,
                "key": self.command.key,
                "native_id": self.native_id,
                "native_owner": self.native_owner,
                "operation": self.command.action,
                "stage": stage,
                "outcome": outcome,
                "native_accept_dispatched": self.native_accept_dispatched,
                "error": error.map(|error| format!("{error:#}")),
            })
        );
    }

    fn observe<T>(&self, stage: &str, result: Result<T>) -> Result<T> {
        self.record(
            stage,
            if result.is_ok() { "ok" } else { "error" },
            result.as_ref().err(),
        );
        result
    }
}
pub struct GsmWorker {
    commands: Sender<(u64, GsmCommand)>,
    selected_epoch: Arc<AtomicU64>,
    states: Receiver<GsmCallState>,
    events: Receiver<GsmEvent>,
    thread: Option<JoinHandle<()>>,
    cancellations: Option<Arc<AdmissionCancellations>>,
}

#[derive(Default)]
struct AdmissionCancellations(std::sync::Mutex<AdmissionLedger>);

#[derive(Default)]
struct AdmissionLedger {
    generation: Option<u64>,
    retired: [u64; 2],
    entries: Vec<(SessionKey, u64, bool)>,
}

impl AdmissionCancellations {
    fn configure(&self, generation: u64) -> Result<()> {
        let mut ledger = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("GSM admission lock poisoned"))?;
        if ledger.generation == Some(generation) {
            return Ok(());
        }
        anyhow::ensure!(
            ledger.entries.is_empty() && ledger.generation.is_none_or(|old| generation > old),
            "GSM admission generation still live or stale"
        );
        *ledger = AdmissionLedger {
            generation: Some(generation),
            ..Default::default()
        };
        Ok(())
    }

    fn register(&self, key: &SessionKey, epoch: u64) -> Result<()> {
        anyhow::ensure!(
            key.transport == yoyopod_protocol::call::CallTransport::Gsm,
            "Invalid GSM admission transport"
        );
        let (namespace, serial) =
            yoyopod_protocol::call::call_ordinal(&key.transport, &key.call_id)
                .context("Invalid GSM admission key")?;
        let mut ledger = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("GSM admission lock poisoned"))?;
        anyhow::ensure!(
            ledger
                .generation
                .is_none_or(|generation| generation == key.generation),
            "GSM admission generation changed"
        );
        ledger.generation = Some(key.generation);
        if let Some((_, admitted_epoch, cancelled)) = ledger
            .entries
            .iter()
            .find(|(candidate, _, _)| candidate == key)
        {
            anyhow::ensure!(
                *admitted_epoch == epoch && !cancelled,
                "GSM admission cancelled or expired"
            );
        } else {
            anyhow::ensure!(
                serial > ledger.retired[namespace],
                "GSM admission key retired"
            );
            anyhow::ensure!(
                ledger.entries.len() < yoyopod_protocol::call::MAX_LIVE_CALLS,
                "GSM admission capacity exhausted"
            );
            ledger.entries.push((key.clone(), epoch, false));
        }
        Ok(())
    }

    fn cancel(&self, key: &SessionKey) -> Result<()> {
        let mut ledger = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("GSM admission lock poisoned"))?;
        if let Some((_, _, cancelled)) = ledger
            .entries
            .iter_mut()
            .find(|(candidate, _, _)| candidate == key)
        {
            *cancelled = true;
        }
        Ok(())
    }

    fn retire(&self, key: &SessionKey) -> Result<()> {
        let mut ledger = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("GSM admission lock poisoned"))?;
        if let Some(index) = ledger
            .entries
            .iter()
            .position(|(candidate, _, _)| candidate == key)
        {
            let (namespace, serial) =
                yoyopod_protocol::call::call_ordinal(&key.transport, &key.call_id)
                    .context("Invalid GSM admission key")?;
            ledger.retired[namespace] = ledger.retired[namespace].max(serial);
            ledger.entries.remove(index);
        }
        Ok(())
    }

    fn ensure_current(ledger: &AdmissionLedger, key: &SessionKey, epoch: u64) -> Result<()> {
        anyhow::ensure!(
            ledger
                .entries
                .iter()
                .any(|(candidate, admitted_epoch, cancelled)| candidate == key
                    && *admitted_epoch == epoch
                    && !cancelled),
            "GSM admission cancelled or expired"
        );
        Ok(())
    }

    fn check(&self, key: &SessionKey, epoch: u64) -> Result<()> {
        let entries = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("GSM admission lock poisoned"))?;
        Self::ensure_current(&entries, key, epoch)
    }
}

impl GsmWorker {
    pub fn start() -> Self {
        Self::with_modem_backend(ModemManagerVoice::default())
    }

    fn with_modem_backend(backend: ModemManagerVoice) -> Self {
        let cancellations = backend.cancellations.clone();
        Self::with_backend_and_cancellations(backend, Some(cancellations))
    }

    pub fn with_backend(backend: impl GsmBackend) -> Self {
        Self::with_backend_and_cancellations(backend, None)
    }

    fn with_backend_and_cancellations(
        mut backend: impl GsmBackend,
        cancellations: Option<Arc<AdmissionCancellations>>,
    ) -> Self {
        let (commands, receive_commands) = mpsc::channel();
        let (send_states, states) = mpsc::channel();
        let (send_events, events) = mpsc::channel();
        let selected_epoch = Arc::new(AtomicU64::new(backend.selected_modem_epoch()));
        let thread_epoch = selected_epoch.clone();
        let thread_cancellations = cancellations.clone();
        let thread = thread::spawn(move || {
            let mut previous = None;
            let mut previous_reconciliation = None;
            loop {
                let queued = receive_commands.recv_timeout(Duration::from_millis(500));
                // Observe removal before dispatch, including commands accepted while a
                // previous bounded native request was waiting for its response.
                let preflight = backend.refresh_observation();
                let preflight_epoch = backend.selected_modem_epoch();
                thread_epoch.store(backend.selected_modem_epoch(), Ordering::SeqCst);
                if let Some(generation) = backend.take_modem_loss() {
                    let _ = send_events.send(GsmEvent::ModemLost { generation });
                }
                let command = queued
                    .map(|(epoch, command)| (epoch == backend.selected_modem_epoch(), command));
                let mut completion = None;
                let command = match command {
                    Ok((
                        false,
                        GsmCommand::Action {
                            request_id,
                            command,
                        },
                    )) => {
                        completion = Some(GsmEvent::Completed {
                            request_id,
                            voice_held: backend.owns_voice(&command.key),
                            key: command.key,
                            error: Some("Selected modem lifetime ended; command fenced".into()),
                        });
                        Err(mpsc::RecvTimeoutError::Timeout)
                    }
                    Ok((
                        false,
                        GsmCommand::DialSession {
                            request_id, key, ..
                        },
                    )) => {
                        completion = Some(GsmEvent::Completed {
                            request_id,
                            voice_held: backend.owns_voice(&key),
                            key,
                            error: Some("Selected modem lifetime ended; command fenced".into()),
                        });
                        Err(mpsc::RecvTimeoutError::Timeout)
                    }
                    Ok((false, GsmCommand::Dial(_) | GsmCommand::Hangup | GsmCommand::Mute(_))) => {
                        Err(mpsc::RecvTimeoutError::Timeout)
                    }
                    Ok((_, command)) => Ok(command),
                    Err(error) => Err(error),
                };
                let dial_attempt = matches!(&command, Ok(GsmCommand::Dial(_)));
                let result = match command {
                    Ok(GsmCommand::Stop) | Err(mpsc::RecvTimeoutError::Disconnected) => {
                        let _ = backend.hangup();
                        break;
                    }
                    Ok(GsmCommand::Dial(number)) => {
                        normalize_phone_number(&number).and_then(|number| {
                            backend.dial(&number)?;
                            let outgoing = GsmCallState {
                                available: true,
                                unavailable_reason: String::new(),
                                state: "outgoing".into(),
                                peer_number: number,
                                ..GsmCallState::default()
                            };
                            send_states
                                .send(outgoing.clone())
                                .context("GSM state receiver closed")?;
                            previous = Some(outgoing);
                            Ok(())
                        })
                    }
                    Ok(GsmCommand::Hangup) => backend.hangup(),
                    Ok(GsmCommand::Mute(muted)) => backend.mute(muted),
                    Ok(GsmCommand::Configure {
                        request_id,
                        generation,
                        pcm_sample_rate_hz,
                    }) => {
                        let error = backend
                            .configure(generation, pcm_sample_rate_hz)
                            .and_then(|()| {
                                thread_cancellations
                                    .as_ref()
                                    .map_or(Ok(()), |latch| latch.configure(generation))
                            })
                            .err()
                            .map(|error| format!("{error:#}"));
                        let _ = send_events.send(GsmEvent::Configured {
                            request_id,
                            generation,
                            error,
                        });
                        Ok(())
                    }
                    Ok(GsmCommand::Action {
                        request_id,
                        command,
                    }) => {
                        let diagnostic = GsmActionDiagnostic {
                            request_id: &request_id,
                            command: &command,
                            native_id: None,
                            native_owner: backend
                                .reconciliation()
                                .and_then(|fact| fact.native_owner),
                            native_accept_dispatched: None,
                        };
                        diagnostic.record("command", "dispatch", None);
                        let result = backend.apply_call_with_request(&request_id, &command);
                        let error = diagnostic
                            .observe("command", result)
                            .err()
                            .map(|error| format!("{error:#}"));
                        let voice_held = backend.owns_voice(&command.key);
                        completion = Some(GsmEvent::Completed {
                            request_id,
                            key: command.key,
                            error,
                            voice_held,
                        });
                        Ok(())
                    }
                    Ok(GsmCommand::DialSession {
                        request_id,
                        key,
                        number,
                    }) => {
                        let error = normalize_phone_number(&number)
                            .and_then(|number| backend.dial_session(&key, &number))
                            .err()
                            .map(|error| format!("{error:#}"));
                        let voice_held = backend.owns_voice(&key);
                        completion = Some(GsmEvent::Completed {
                            request_id,
                            key,
                            error,
                            voice_held,
                        });
                        Ok(())
                    }
                    Err(mpsc::RecvTimeoutError::Timeout) => Ok(()),
                };
                let mut refresh_ok = true;
                let mut preflight_calls = Vec::new();
                let mut call_events = Vec::new();
                if let Ok(observation) = preflight {
                    preflight_calls.extend(observation.calls);
                }
                let mut state = match backend.refresh_observation() {
                    Ok(observation) => {
                        call_events.extend(observation.calls);
                        observation.availability
                    }
                    Err(error) => {
                        refresh_ok = false;
                        eprintln!("GSM state refresh failed: {error:#}");
                        GsmCallState {
                            state: "error".into(),
                            ..GsmCallState::default()
                        }
                    }
                };
                call_events.extend(backend.drain_call_events());
                if backend.selected_modem_epoch() != preflight_epoch {
                    preflight_calls.retain(|event|!matches!(event,CallManagerWireEvent::Update(update)
                        if matches!(update.phase,CallPhase::Active | CallPhase::Held | CallPhase::Outgoing)));
                }
                preflight_calls.extend(call_events);
                let call_events = preflight_calls;
                thread_epoch.store(backend.selected_modem_epoch(), Ordering::SeqCst);
                if let Some(generation) = backend.take_modem_loss() {
                    let _ = send_events.send(GsmEvent::ModemLost { generation });
                }
                if let Some(mut reconciled) = backend.reconciliation() {
                    if !refresh_ok {
                        reconciled.native_calls_quiescent = false;
                    }
                    if previous_reconciliation.as_ref() != Some(&reconciled) {
                        let _ = send_events.send(GsmEvent::Reconciled(reconciled.clone()));
                        previous_reconciliation = Some(reconciled);
                    }
                }
                // Publish generation-to-native-owner evidence before session facts.
                for event in call_events {
                    if let (Some(latch), CallManagerWireEvent::Update(update)) =
                        (&thread_cancellations, &event)
                    {
                        if update.phase == CallPhase::Ended {
                            let _ = latch.retire(&update.key);
                        }
                    }
                    let _ = send_events.send(GsmEvent::Call(event));
                }
                // Loss and native facts must close the outer data barrier before
                // a keyed completion can decide whether its reservation releases.
                if let Some(completion) = completion {
                    if let (
                        Some(latch),
                        GsmEvent::Completed {
                            key,
                            voice_held: false,
                            ..
                        },
                    ) = (&thread_cancellations, &completion)
                    {
                        let _ = latch.retire(key);
                    }
                    let _ = send_events.send(completion);
                }
                if let Err(error) = result {
                    eprintln!("GSM call command failed: {error:#}");
                    if !matches!(state.state.as_str(), "outgoing" | "active") {
                        let _ = backend.hangup();
                        state.state = "error".to_string();
                    }
                }
                if dial_attempt || previous.as_ref() != Some(&state) {
                    if send_states.send(state.clone()).is_err() {
                        break;
                    }
                    previous = Some(state);
                }
            }
        });
        Self {
            commands,
            selected_epoch,
            states,
            events,
            thread: Some(thread),
            cancellations,
        }
    }

    pub fn send(&self, command: GsmCommand) -> Result<()> {
        self.send_at_epoch(command, self.selected_epoch.load(Ordering::SeqCst))
    }
    pub(crate) fn admission_epoch(&self) -> u64 {
        self.selected_epoch.load(Ordering::SeqCst)
    }
    pub(crate) fn send_at_epoch(&self, command: GsmCommand, epoch: u64) -> Result<()> {
        use yoyopod_protocol::call::CallAction;
        if let Some(latch) = &self.cancellations {
            match &command {
                GsmCommand::DialSession { key, .. } => latch.register(key, epoch)?,
                GsmCommand::Action { command, .. } => match command.action {
                    CallAction::Answer => latch.register(&command.key, epoch)?,
                    CallAction::Reject(_) | CallAction::Hangup => latch.cancel(&command.key)?,
                    CallAction::SetMute(_) => {}
                },
                _ => {}
            }
        }
        self.commands
            .send((epoch, command))
            .context("GSM worker unavailable")
    }

    pub fn drain(&self) -> Vec<GsmCallState> {
        self.states.try_iter().collect()
    }
    pub fn drain_events(&self) -> Vec<GsmEvent> {
        self.events.try_iter().collect()
    }
}

impl Drop for GsmWorker {
    fn drop(&mut self) {
        let _ = self
            .commands
            .send((self.selected_epoch.load(Ordering::SeqCst), GsmCommand::Stop));
        // The call backend has a bounded D-Bus timeout and releases call audio
        // when stopped; the network worker must not leave an orphan call.
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

pub fn normalize_phone_number(number: &str) -> Result<String> {
    let number: String = number
        .chars()
        .filter(|ch| !matches!(ch, ' ' | '-' | '(' | ')'))
        .collect();
    let digits = number.strip_prefix('+').unwrap_or(&number);
    if !(7..=15).contains(&digits.len()) || !digits.bytes().all(|byte| byte.is_ascii_digit()) {
        bail!("Invalid phone number");
    }
    Ok(number)
}

fn voice_service_unavailable_reason(
    state: i32,
    unlock_required: u32,
    voice_available: bool,
    emergency_only: bool,
) -> Option<&'static str> {
    // MMModemLock: NONE = 1, SIM_PIN2 = 3, SIM_PUK2 = 5. ModemManager
    // considers PIN2/PUK2 restrictions operational without unlocking them.
    if !matches!(unlock_required, 1 | 3 | 5) {
        Some("SIM locked")
    } else if !voice_available {
        Some("No voice service")
    } else if state < 8 || emergency_only {
        Some("No mobile service")
    } else {
        None
    }
}

/// A failed native operation can synthesize MM's Terminated state. Never turn
/// that property alone into a cleanup acknowledgement after an uncertain action.
#[derive(Default)]
struct CleanupEvidence {
    uncertain: std::collections::HashSet<String>,
}
impl CleanupEvidence {
    fn observe_initial(&mut self, path: &str, phase: &CallPhase) {
        if *phase == CallPhase::Ended {
            self.failed(path);
        }
    }
    fn failed(&mut self, path: &str) {
        self.uncertain.insert(path.into());
    }
    fn confirmed(&mut self, path: &str) {
        self.uncertain.remove(path);
    }
    fn terminal_is_trusted(&self, path: &str) -> bool {
        !self.uncertain.contains(path)
    }
}

#[cfg(test)]
type CollectorGate = Arc<std::sync::Mutex<Option<(Sender<()>, Receiver<()>)>>>;

struct ModemSignals {
    connection: Connection,
    messages: Receiver<zbus::Message>,
    evidence_gap: Arc<std::sync::atomic::AtomicBool>,
    progress: Arc<(
        std::sync::Mutex<zbus::message::Sequence>,
        std::sync::Condvar,
    )>,
    #[cfg(test)]
    pause_before_forward: CollectorGate,
    thread: Option<JoinHandle<()>>,
}
impl ModemSignals {
    fn start(connection: &Connection, owner: &str) -> Result<Self> {
        Self::start_with_capacity(connection, owner, 128)
    }
    fn start_with_capacity(connection: &Connection, owner: &str, capacity: usize) -> Result<Self> {
        let connection = connection.clone();
        let rule = zbus::MatchRule::builder()
            .msg_type(zbus::message::Type::Signal)
            .sender(owner.to_owned())?
            .path_namespace("/org/freedesktop/ModemManager1")?
            .build();
        // This ordered stream includes this connection's method replies. The
        // exact-owner bus match still admits only our native signal namespace;
        // the stream does not request other connections' traffic.
        let mut stream = zbus::blocking::MessageIterator::from(&connection);
        connection.call_method(
            Some("org.freedesktop.DBus"),
            "/org/freedesktop/DBus",
            Some("org.freedesktop.DBus"),
            "AddMatch",
            &rule.to_string(),
        )?;
        let (sender, messages) = mpsc::sync_channel(capacity);
        let evidence_gap = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let thread_gap = evidence_gap.clone();
        let progress = Arc::new((
            std::sync::Mutex::new(zbus::message::Sequence::default()),
            std::sync::Condvar::new(),
        ));
        let thread_progress = progress.clone();
        #[cfg(test)]
        let pause_before_forward =
            Arc::new(std::sync::Mutex::new(None::<(Sender<()>, Receiver<()>)>));
        #[cfg(test)]
        let thread_pause = pause_before_forward.clone();
        let thread = thread::spawn(move || {
            for message in &mut stream {
                let Ok(message) = message else {
                    thread_gap.store(true, Ordering::SeqCst);
                    thread_progress.1.notify_all();
                    break;
                };
                let position = message.recv_position();
                let relevant = match rule.matches(&message) {
                    Ok(relevant) => relevant,
                    Err(_) => {
                        thread_gap.store(true, Ordering::SeqCst);
                        false
                    }
                };
                #[cfg(test)]
                if relevant
                    && matches!(
                        message.header().member().map(|m| m.as_str()),
                        Some("InterfacesRemoved" | "PropertiesChanged" | "StateChanged")
                    )
                {
                    let gate = thread_pause.lock().unwrap().take();
                    if let Some((entered, release)) = gate {
                        let _ = entered.send(());
                        let _ = release.recv_timeout(Duration::from_secs(3));
                    }
                }
                // Keep the retained subscription alive through a property storm.
                // A missing removal can hide a reused native incarnation, so any
                // gap permanently quarantines this backend's native evidence.
                if relevant {
                    match sender.try_send(message) {
                        Ok(()) => {}
                        Err(mpsc::TrySendError::Full(_)) => {
                            thread_gap.store(true, Ordering::SeqCst);
                        }
                        Err(mpsc::TrySendError::Disconnected(_)) => break,
                    }
                }
                // ACK only after relevant evidence was forwarded or a gap was
                // latched. Sequence is zbus's receive order on this connection.
                *thread_progress.0.lock().unwrap() = position;
                thread_progress.1.notify_all();
            }
        });
        Ok(Self {
            connection,
            messages,
            evidence_gap,
            progress,
            #[cfg(test)]
            pause_before_forward,
            thread: Some(thread),
        })
    }

    fn wait_through(&self, position: zbus::message::Sequence, deadline: Duration) -> Result<()> {
        let (lock, changed) = &*self.progress;
        let progress = lock.lock().map_err(|_| {
            self.evidence_gap.store(true, Ordering::SeqCst);
            anyhow::anyhow!("Signal collector progress poisoned")
        })?;
        let (progress, _) = changed
            .wait_timeout_while(progress, deadline, |processed| {
                *processed < position && !self.evidence_gap.load(Ordering::SeqCst)
            })
            .map_err(|_| {
                self.evidence_gap.store(true, Ordering::SeqCst);
                anyhow::anyhow!("Signal collector progress poisoned")
            })?;
        if *progress < position || self.evidence_gap.load(Ordering::SeqCst) {
            self.evidence_gap.store(true, Ordering::SeqCst);
            bail!("Native signal collector progress unproven");
        }
        Ok(())
    }
}
impl Drop for ModemSignals {
    fn drop(&mut self) {
        let _ = self.connection.clone().close();
        if let Some(thread) = self.thread.take() {
            let _ = thread.join();
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
enum OutgoingStage {
    Creating,
    CreatedUnstarted { path: String },
    StartDispatched { path: String },
}

#[derive(Default)]
struct ModemManagerVoice {
    selected_epoch: u64,
    modem_lost: bool,
    loss_pending: bool,
    clean_rediscovery: bool,
    idle_calls_proven: bool,
    native_membership_revision: u64,
    membership_reconcile_pending: bool,
    initial_scan: bool,
    service_owner: Option<String>,
    service_bus_id: Option<String>,
    service_invalidated: bool,
    terminating: std::collections::HashSet<String>,
    // Exact successful EndCall proof belongs to the still-registered old key.
    // A later path tombstone fences reuse, while fresh absence can release it.
    confirmed_hangups: Vec<(SessionKey, String)>,
    connection: Option<Connection>,
    modem: Option<OwnedObjectPath>,
    signals: Option<ModemSignals>,
    registry: Option<crate::gsm_calls::GsmCallRegistry>,
    generation: Option<u64>,
    provider: crate::gsm_provider::ProviderGate,
    provider_identity: Option<crate::gsm_provider::ProviderIdentity>,
    provider_invalidated: bool,
    format_admission: Option<(SessionKey, u64, u32)>,
    owned_audio_port: Option<String>,
    isolated: bool,
    pending_events: Vec<CallManagerWireEvent>,
    owner: Option<SessionKey>,
    pcm: PcmAdapter,
    prepared_audio: Option<Box<dyn PreparedPcm>>,
    audio: Option<Box<dyn ActivePcm>>,
    audio_deadline: Option<Instant>,
    active_since: Option<Instant>,
    cleanup: CleanupEvidence,
    cached: GsmCallState,
    next_discovery: Option<Instant>,
    next_recovery: Option<Instant>,
    // CreateCall timeout may create an object later. Retain the data lease;
    // discovery cannot supply the exact returned identity of a lost reply.
    uncertain_create: Option<SessionKey>,
    outgoing_stage: Option<(SessionKey, OutgoingStage)>,
    // Removal followed by reuse cannot lend the new object's identity to an
    // old key. Only trusted absence (never-started) or recovery can clear it.
    lost_call_paths: std::collections::HashSet<String>,
    accept_dispatched: Option<SessionKey>,
    cancellations: Arc<AdmissionCancellations>,
}

impl ModemManagerVoice {
    fn call_identity_removed(&mut self, path: &str) {
        if self
            .registry
            .as_ref()
            .is_none_or(|registry| !registry.tracked().iter().any(|(known, _)| known == path))
        {
            return;
        }
        self.lost_call_paths.insert(path.into());
        self.cleanup.failed(path);
        self.call_format_lost(path);
    }
    fn audio_key(&self) -> Option<&SessionKey> {
        self.owner
            .as_ref()
            .or_else(|| self.format_admission.as_ref().map(|(key, _, _)| key))
    }

    fn call_format_lost(&mut self, path: &str) {
        if self
            .audio_key()
            .and_then(|key| self.registry.as_ref()?.path_for(key))
            == Some(path)
        {
            self.invalidate_provider_audio();
            return;
        }
        // An unowned Call cannot invalidate another session's audio proof.
        // Keep this exact key/path in Ending even if its dictionary recovers.
        let Some(key) = self.registry.as_ref().and_then(|r| {
            r.tracked()
                .into_iter()
                .find(|(p, _)| p == path)
                .map(|(_, k)| k)
        }) else {
            return;
        };
        self.cleanup.failed(path);
        self.terminating.insert(path.into());
        self.pending_events.retain(|event|!matches!(event,CallManagerWireEvent::Update(update)
            if update.key == key && matches!(update.phase,CallPhase::Active | CallPhase::Held | CallPhase::Outgoing)));
        if let Some(registry) = self.registry.as_mut() {
            if let Some(old) = registry.latest(&key).cloned() {
                self.pending_events.extend(registry.observe(
                    path,
                    old.direction,
                    CallPhase::Ending,
                    &old.address,
                ));
            }
        }
    }

    fn invalidate_provider_audio(&mut self) {
        if self.provider_invalidated || self.modem_lost || self.service_invalidated {
            return;
        }
        self.provider_invalidated = true;
        self.loss_pending = true;
        self.selected_epoch = self
            .selected_epoch
            .checked_add(1)
            .expect("modem epoch exhausted");
        self.provider_identity = None;
        self.format_admission = None;
        self.owned_audio_port = None;
        self.audio.take();
        self.prepared_audio.take();
        self.audio_deadline = None;
        self.cached.available = false;
        self.cached.unavailable_reason = "Audio unavailable".into();
        self.pending_events.retain(|event| {
            !matches!(event,CallManagerWireEvent::Update(update)
            if matches!(update.phase,CallPhase::Active | CallPhase::Held | CallPhase::Outgoing))
        });
        // The same signaling objects remain usable for targeted termination.
        // Neither recovered metadata nor stopped local PCM proves native release.
        if let Some(registry) = self.registry.as_mut() {
            for (path, key) in registry.tracked() {
                self.cleanup.failed(&path);
                if let Some(old) = registry.latest(&key).cloned() {
                    self.pending_events.extend(registry.observe(
                        &path,
                        old.direction,
                        CallPhase::Ending,
                        &old.address,
                    ));
                }
            }
        }
    }

    fn provider_baseline(&mut self) -> Result<crate::gsm_provider::ProviderIdentity> {
        let result = self.provider.read(
            self.connection.as_ref().context("No modem connection")?,
            self.bound_owner()?,
            self.modem.as_ref().context("No modem")?.as_str(),
        );
        let actual = match result {
            Ok(actual) => actual,
            Err(error) => {
                if self.provider_identity.is_some() {
                    self.invalidate_provider_audio();
                }
                self.cached.available = false;
                self.cached.unavailable_reason = "Audio unavailable".into();
                return Err(error);
            }
        };
        self.check_selected_modem()?;
        if self
            .provider_identity
            .as_ref()
            .is_some_and(|old| old != &actual)
        {
            self.invalidate_provider_audio();
        }
        if self.provider_invalidated {
            anyhow::ensure!(
                self.idle_calls_proven
                    && self.registry()?.tracked().is_empty()
                    && self.owner.is_none()
                    && self.terminating.is_empty()
                    && self.uncertain_create.is_none()
                    && self.cleanup.uncertain.is_empty(),
                "GSM old audio lifetime requires clean native reconciliation"
            );
            self.provider_invalidated = false;
        }
        self.provider_identity = Some(actual.clone());
        Ok(actual)
    }

    fn selected_modem_lost(&mut self) {
        if self.modem_lost {
            return;
        }
        self.clean_rediscovery = self.idle_calls_proven
            && self
                .registry
                .as_ref()
                .is_some_and(|r| r.tracked().is_empty())
            && self.terminating.is_empty()
            && self.owner.is_none()
            && self.uncertain_create.is_none()
            && self.cleanup.uncertain.is_empty()
            && self.audio.is_none()
            && self.prepared_audio.is_none()
            && self.audio_deadline.is_none()
            && self.pending_events.is_empty();
        self.modem_lost = true;
        self.loss_pending = true;
        if !self.provider_invalidated {
            self.selected_epoch = self
                .selected_epoch
                .checked_add(1)
                .expect("modem epoch exhausted");
        }
        self.provider_invalidated = true;
        self.provider_identity = None;
        self.format_admission = None;
        self.owned_audio_port = None;
        self.isolated = false;
        self.idle_calls_proven = false;
        self.cached.available = false;
        self.cached.unavailable_reason =
            "Selected modem lost; native reconciliation required".into();
        self.audio.take();
        self.prepared_audio.take();
        self.pending_events.clear();
        if let Some(registry) = self.registry.as_mut() {
            for (path, key) in registry.tracked() {
                self.cleanup.failed(&path);
                if let Some(old) = registry.latest(&key).cloned() {
                    self.pending_events.extend(registry.observe(
                        &path,
                        old.direction,
                        CallPhase::Ending,
                        &old.address,
                    ));
                }
            }
        }
        if self.clean_rediscovery {
            self.modem = None;
            self.initial_scan = true;
            self.next_discovery = Some(Instant::now() + Duration::from_secs(3));
        }
    }

    fn removal_signal(&mut self, message: &zbus::Message) {
        let header = message.header();
        if header.sender().map(|s| s.as_str()) == self.service_owner.as_deref() {
            let path = header.path().map(|p| p.as_str());
            let modem = self.modem.as_ref().map(|p| p.as_str().to_owned());
            if path == modem.as_deref()
                && header.interface().map(|i| i.as_str()) == Some(MODEM_INTERFACE)
                && header.member().map(|m| m.as_str()) == Some("StateChanged")
                && message
                    .body()
                    .deserialize::<(i32, i32, u32)>()
                    .map_or(true, |(old, new, _)| old < 6 || new < 6)
            {
                self.invalidate_provider_audio();
            }
            if header.interface().map(|i| i.as_str()) == Some("org.freedesktop.DBus.Properties")
                && header.member().map(|m| m.as_str()) == Some("PropertiesChanged")
            {
                if let Ok((interface, changed, invalidated)) = message.body().deserialize::<(
                    String,
                    HashMap<String, zvariant::OwnedValue>,
                    Vec<String>,
                )>() {
                    let unknown = |name: &str| invalidated.iter().any(|s| s == name);
                    let modem_loss = path == modem.as_deref()
                        && (interface == MODEM_INTERFACE
                            && (unknown("State")
                                || changed
                                    .get("State")
                                    .is_some_and(|v| i32::try_from(v).map_or(true, |s| s < 6)))
                            || interface == VOICE_INTERFACE
                                && (unknown("EmergencyOnly")
                                    || changed
                                        .get("EmergencyOnly")
                                        .is_some_and(|v| bool::try_from(v).unwrap_or(true))));
                    let owned_path = self
                        .owner
                        .as_ref()
                        .and_then(|key| self.registry.as_ref()?.path_for(key));
                    let tracked = path.is_some_and(|p| {
                        self.registry
                            .as_ref()
                            .is_some_and(|r| r.tracked().iter().any(|(known, _)| known == p))
                    });
                    let mut format_loss = false;
                    if tracked && interface == CALL_INTERFACE {
                        format_loss = unknown("AudioFormat");
                        if let Some(value) = changed.get("AudioFormat") {
                            format_loss |= value
                                .try_clone()
                                .ok()
                                .and_then(|v| {
                                    HashMap::<String, zvariant::OwnedValue>::try_from(v).ok()
                                })
                                .is_none_or(|format| {
                                    !crate::gsm_provider::current_format_matches(&format)
                                });
                        }
                    }
                    let port_loss = path == owned_path
                        && self.owned_audio_port.is_some()
                        && (unknown("AudioPort")
                            || changed.get("AudioPort").is_some_and(|v| {
                                <&str>::try_from(v).ok() != self.owned_audio_port.as_deref()
                            }));
                    let inventory_loss = path == modem.as_deref()
                        && self.owned_audio_port.is_some()
                        && interface == MODEM_INTERFACE
                        && (unknown("Ports")
                            || changed.get("Ports").is_some_and(|value| {
                                value
                                    .try_clone()
                                    .ok()
                                    .and_then(|v| Vec::<(String, u32)>::try_from(v).ok())
                                    .is_none_or(|ports| {
                                        !audio_inventory_contains(
                                            &ports,
                                            self.owned_audio_port.as_deref().unwrap(),
                                        )
                                    })
                            }));
                    if format_loss {
                        if let Some(path) = path {
                            self.call_format_lost(path);
                        }
                    }
                    if modem_loss || port_loss || inventory_loss {
                        self.invalidate_provider_audio();
                    }
                } else if path == modem.as_deref()
                    || self.owner.as_ref().is_some_and(|key| {
                        self.registry.as_ref().and_then(|r| r.path_for(key)) == path
                    })
                {
                    self.invalidate_provider_audio();
                }
            }
        }
        if header.sender().map(|s| s.as_str()) == self.service_owner.as_deref()
            && header.path().map(|p| p.as_str()) == self.modem.as_ref().map(|p| p.as_str())
            && header.interface().map(|s| s.as_str()) == Some(VOICE_INTERFACE)
            && matches!(
                header.member().map(|s| s.as_str()),
                Some("CallAdded" | "CallDeleted")
            )
        {
            // Every drain retains membership work. Neither an older Calls
            // snapshot nor a failed fresh observation may acknowledge it.
            self.native_membership_revision = self
                .native_membership_revision
                .checked_add(1)
                .expect("native membership revision exhausted");
            self.membership_reconcile_pending = true;
            if header.member().map(|s| s.as_str()) == Some("CallAdded") {
                self.idle_calls_proven = false;
            } else if let Ok((path,)) = message.body().deserialize::<(OwnedObjectPath,)>() {
                self.call_identity_removed(path.as_str());
            }
        }
        if header.sender().map(|s| s.as_str()) != self.service_owner.as_deref()
            || header.interface().map(|s| s.as_str()) != Some("org.freedesktop.DBus.ObjectManager")
            || header.member().map(|s| s.as_str()) != Some("InterfacesRemoved")
        {
            return;
        }
        if let Ok((path, interfaces)) = message
            .body()
            .deserialize::<(OwnedObjectPath, Vec<String>)>()
        {
            if interfaces.iter().any(|i| i == CALL_INTERFACE) {
                self.call_identity_removed(path.as_str());
            }
            if self.modem.as_ref() == Some(&path)
                && interfaces
                    .iter()
                    .any(|i| i == MODEM_INTERFACE || i == VOICE_INTERFACE)
            {
                self.selected_modem_lost();
            }
        }
    }

    fn check_selected_modem(&mut self) -> Result<()> {
        self.verify_service_owner()?;
        let messages: Vec<_> = self
            .signals
            .as_ref()
            .map(|s| s.messages.try_iter().collect())
            .unwrap_or_default();
        for message in messages {
            self.removal_signal(&message);
        }
        anyhow::ensure!(!self.modem_lost, "Selected modem lost");
        let modem = self.modem.as_ref().context("No selected modem")?.clone();
        let reply = self
            .connection
            .as_ref()
            .context("No connection")?
            .call_method(
                Some(self.bound_owner()?),
                "/org/freedesktop/ModemManager1",
                Some("org.freedesktop.DBus.ObjectManager"),
                "GetManagedObjects",
                &(),
            )?;
        let signals = self
            .signals
            .as_ref()
            .context("No retained native signal collector")?;
        if let Err(error) = signals.wait_through(reply.recv_position(), Duration::from_secs(5)) {
            // Missing progress cannot establish old-lifetime quiescence.
            self.verify_service_owner()?;
            return Err(error);
        }
        let objects: ManagedObjects = reply.body().deserialize()?;
        self.verify_service_owner()?;
        // The collector has now forwarded every native signal received before
        // this exact OM reply. Consume that ordered evidence before its facts.
        let messages: Vec<_> = self
            .signals
            .as_ref()
            .map(|signals| signals.messages.try_iter().collect())
            .unwrap_or_default();
        for message in messages {
            self.removal_signal(&message);
        }
        anyhow::ensure!(!self.modem_lost, "Selected modem lost");
        if !objects.get(&modem).is_some_and(|interfaces| {
            interfaces.contains_key(MODEM_INTERFACE) && interfaces.contains_key(VOICE_INTERFACE)
        }) {
            self.selected_modem_lost();
        } else if objects
            .get(&modem)
            .and_then(|i| i.get(MODEM_INTERFACE))
            .and_then(|p| p.get("State"))
            .and_then(|v| i32::try_from(v).ok())
            .is_none_or(|state| state < 6)
        {
            self.invalidate_provider_audio();
        }
        anyhow::ensure!(!self.modem_lost, "Selected modem lost");
        Ok(())
    }
    fn connection(&mut self) -> Result<&Connection> {
        if self.connection.is_none() {
            self.connection = Some(
                Builder::system()?
                    .method_timeout(Duration::from_secs(5))
                    .build()?,
            );
        }
        Ok(self.connection.as_ref().expect("connected"))
    }

    fn discover(&mut self) -> Result<()> {
        let connection = self.connection()?.clone();
        // A registry and every piece of native evidence belong to this captured
        // unique connection for their entire lifetime. Never rebind on rediscovery.
        if self.service_owner.is_none() {
            let bus_id = Self::bus_id(&connection)?;
            self.service_owner = Some(Self::current_service_owner(&connection)?);
            self.service_bus_id = Some(bus_id);
        }
        self.verify_service_owner()?;
        let native_owner = self.bound_owner()?.to_owned();
        if self.signals.is_none() {
            self.signals = Some(ModemSignals::start(&connection, &native_owner)?);
        }
        let manager = Proxy::new(
            &connection,
            native_owner.as_str(),
            "/org/freedesktop/ModemManager1",
            "org.freedesktop.DBus.ObjectManager",
        )?;
        let objects: ManagedObjects = manager.call("GetManagedObjects", &())?;
        let version: String = Proxy::new(
            &connection,
            native_owner.as_str(),
            "/org/freedesktop/ModemManager1",
            DESTINATION,
        )?
        .get_property("Version")?;
        self.cached.available = false;
        self.cached.unavailable_reason = "No modem".into();
        let mut objects: Vec<_> = objects.into_iter().collect();
        objects.sort_by(|a, b| a.0.cmp(&b.0));
        for (path, interfaces) in objects {
            let Some(modem) = interfaces.get(MODEM_INTERFACE) else {
                continue;
            };
            let string = |name: &str| {
                modem
                    .get(name)
                    .and_then(|v| <&str>::try_from(v).ok())
                    .unwrap_or_default()
            };
            let model = string("Model");
            if !model.contains("SIM7600") {
                continue;
            }
            let proxy = Proxy::new(
                &connection,
                native_owner.as_str(),
                path.as_str(),
                MODEM_INTERFACE,
            )?;
            let ports: Vec<(String, u32)> = proxy.get_property("Ports")?;
            drop(proxy);
            self.verify_service_owner()?;
            self.isolated = isolated_voice_backend(
                &version,
                model,
                string("Plugin"),
                string("PrimaryPort"),
                &ports,
            );
            let state = modem
                .get("State")
                .and_then(|v| i32::try_from(v).ok())
                .unwrap_or_default();
            let lock = modem
                .get("UnlockRequired")
                .and_then(|v| u32::try_from(v).ok())
                .unwrap_or_default();
            let voice = interfaces.get(VOICE_INTERFACE);
            let emergency = voice
                .and_then(|v| v.get("EmergencyOnly"))
                .and_then(|v| bool::try_from(v).ok())
                .unwrap_or(true);
            let reason = if !self.isolated {
                Some("Isolated GSM control unsupported: requires ModemManager 1.24.0 SIMTech QMI primary port")
            } else {
                voice_service_unavailable_reason(state, lock, voice.is_some(), emergency)
            };
            self.cached.available = reason.is_none();
            self.cached.unavailable_reason = reason.unwrap_or_default().into();
            self.modem = Some(path);
            self.modem_lost = false;
            self.clean_rediscovery = false;
            // Subsequent Calls scans use the selected Voice property. Native
            // observations still fence selected incarnation through ordered OM.
            self.reconcile_paths()?;
            self.initial_scan = false;
            break;
        }
        self.verify_service_owner()?;
        self.next_discovery = Some(Instant::now() + Duration::from_secs(3));
        Ok(())
    }

    fn proxy_for(&self, path: &str) -> Result<Proxy<'_>> {
        Ok(Proxy::new(
            self.connection.as_ref().context("No modem connection")?,
            self.bound_owner()?.to_owned(),
            path.to_owned(),
            CALL_INTERFACE,
        )?)
    }
    fn bound_owner(&self) -> Result<&str> {
        anyhow::ensure!(
            !self.service_invalidated,
            "ModemManager owner lost; native call reconciliation required"
        );
        let owner = self
            .service_owner
            .as_deref()
            .context("No validated ModemManager owner")?;
        zbus::names::UniqueName::try_from(owner)
            .context("ModemManager destination is not a unique owner")?;
        Ok(owner)
    }

    fn invalidate_service_owner(&mut self) {
        if !self.service_invalidated && !self.modem_lost && !self.provider_invalidated {
            self.selected_epoch = self
                .selected_epoch
                .checked_add(1)
                .expect("modem epoch exhausted");
            self.loss_pending = true;
        }
        self.service_invalidated = true;
        self.provider_invalidated = true;
        self.provider_identity = None;
        self.format_admission = None;
        self.owned_audio_port = None;
        self.isolated = false;
        self.cached.available = false;
        self.cached.unavailable_reason =
            "ModemManager owner lost; native call reconciliation required".into();
        // Stop local PCM, but keep the keyed data reservation and every native
        // path. Replacement-service facts cannot resolve these sessions.
        self.audio.take();
        self.prepared_audio.take();
        self.pending_events.clear();
        if let Some(registry) = self.registry.as_mut() {
            for (path, key) in registry.tracked() {
                self.cleanup.failed(&path);
                if let Some(old) = registry.latest(&key).cloned() {
                    self.pending_events.extend(registry.observe(
                        &path,
                        old.direction,
                        CallPhase::Ending,
                        &old.address,
                    ));
                }
            }
        }
    }

    fn verify_service_owner(&mut self) -> Result<()> {
        if !self.service_invalidated
            && self
                .signals
                .as_ref()
                .is_some_and(|signals| signals.evidence_gap.swap(false, Ordering::SeqCst))
        {
            self.invalidate_service_owner();
            self.modem_lost = true;
            self.clean_rediscovery = false;
            self.loss_pending = true;
            self.cached.unavailable_reason =
                "GSM signal evidence lost; native reconciliation required".into();
            bail!("{}", self.cached.unavailable_reason);
        }
        let expected = self.bound_owner()?.to_owned();
        let current =
            Self::current_service_owner(self.connection.as_ref().context("No modem connection")?);
        if current.as_deref().ok() != Some(expected.as_str()) {
            self.invalidate_service_owner();
            bail!("{}", self.cached.unavailable_reason);
        }
        Ok(())
    }
    fn bus_id(connection: &Connection) -> Result<String> {
        Ok(Proxy::new(
            connection,
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
        )?
        .call("GetId", &())?)
    }
    fn current_service_owner(connection: &Connection) -> Result<String> {
        Ok(Proxy::new(
            connection,
            "org.freedesktop.DBus",
            "/org/freedesktop/DBus",
            "org.freedesktop.DBus",
        )?
        .call("GetNameOwner", &(DESTINATION,))?)
    }
    fn registry(&self) -> Result<&crate::gsm_calls::GsmCallRegistry> {
        self.registry
            .as_ref()
            .context("GSM worker is not configured")
    }
    fn path_for(&self, key: &SessionKey) -> Result<String> {
        self.registry()?
            .path_for(key)
            .map(str::to_owned)
            .context("Unknown or stale GSM session")
    }
    fn ensure_control(&mut self) -> Result<()> {
        self.verify_service_owner()?;
        if self.signals.is_some() {
            self.check_selected_modem()?;
        }
        anyhow::ensure!(
            !self.modem_lost,
            "Selected modem lost; native reconciliation required"
        );
        anyhow::ensure!(
            self.isolated,
            "Isolated GSM control unsupported; refusing unsafe modem fallback"
        );
        Ok(())
    }

    fn reconcile_paths(&mut self) -> Result<()> {
        self.verify_service_owner()?;
        let membership_revision = self.native_membership_revision;
        let Some(modem) = self.modem.as_ref() else {
            return Ok(());
        };
        let voice: Proxy<'_> = zbus::blocking::proxy::Builder::new(
            self.connection.as_ref().context("No modem connection")?,
        )
        .destination(self.bound_owner()?.to_owned())?
        .path(modem.as_str())?
        .interface(VOICE_INTERFACE)?
        .cache_properties(zbus::proxy::CacheProperties::No)
        .build()?;
        let result = voice.get_property::<Vec<OwnedObjectPath>>("Calls");
        drop(voice);
        // A response belongs to the bound unique owner, but owner loss during
        // the request still invalidates quiescence before registry mutation.
        self.verify_service_owner()?;
        self.check_selected_modem()?;
        let paths = match result {
            Ok(paths) => paths,
            Err(error) => {
                self.idle_calls_proven = false;
                return Err(error.into());
            }
        };
        // A newer membership change consumed by the post-response checks makes this
        // Calls snapshot stale. Preserve its unresolved ownership evidence
        // until a fresh scan instead of certifying idle or deleting old keys.
        if self.native_membership_revision != membership_revision {
            self.idle_calls_proven = false;
            return Ok(());
        }
        self.idle_calls_proven = paths.is_empty();
        let old = self.registry()?.tracked();
        for path in &paths {
            self.observe_path(path.as_str())?;
        }
        self.verify_service_owner()?;
        self.check_selected_modem()?;
        if self.native_membership_revision != membership_revision {
            self.idle_calls_proven = false;
            return Ok(());
        }
        for (path, key) in old {
            if !paths.iter().any(|candidate| candidate.as_str() == path) {
                self.object_deleted(&path, &key);
            }
        }
        self.membership_reconcile_pending = false;
        Ok(())
    }

    fn object_deleted(&mut self, path: &str, key: &SessionKey) {
        if (self.accept_dispatched.as_ref() == Some(key)
            || self
                .outgoing_stage
                .as_ref()
                .is_some_and(|(candidate, stage)| {
                    candidate == key && matches!(stage, OutgoingStage::StartDispatched { .. })
                }))
            && !self
                .confirmed_hangups
                .iter()
                .any(|(candidate, acknowledged)| candidate == key && acknowledged == path)
        {
            // Absence/CallDeleted can race a dispatched Start. It cannot prove
            // that its native operation ended; retain this exact key and lease.
            self.cleanup.failed(path);
            self.audio.take();
            self.prepared_audio.take();
            return;
        }
        self.terminating.remove(path);
        self.confirmed_hangups
            .retain(|(candidate, acknowledged)| candidate != key || acknowledged != path);
        self.lost_call_paths.remove(path);
        if let Some(old) = self.registry.as_ref().and_then(|r| r.latest(key)).cloned() {
            self.cleanup.confirmed(path);
            let events = self.registry.as_mut().expect("configured").observe(
                path,
                old.direction,
                CallPhase::Ended,
                &old.address,
            );
            self.pending_events.extend(events);
        }
        self.release_audio(key);
        if let Some(registry) = self.registry.as_mut() {
            registry.remove(key);
        }
    }

    fn release_audio(&mut self, key: &SessionKey) {
        if self.owner.as_ref() == Some(key) {
            // Drop joins relays and reaps the endpoint-owning exec children before
            // the matching Ended update can be drained by the network worker.
            self.audio.take();
            self.prepared_audio.take();
            self.format_admission = None;
            self.owned_audio_port = None;
            self.audio_deadline = None;
            self.active_since = None;
            self.owner = None;
            if let Err(error) = self.cancellations.retire(key) {
                eprintln!("GSM admission retirement failed: {error:#}");
            }
            if self
                .outgoing_stage
                .as_ref()
                .is_some_and(|(candidate, _)| candidate == key)
            {
                self.outgoing_stage = None;
            }
            if self.accept_dispatched.as_ref() == Some(key) {
                self.accept_dispatched = None;
            }
            if self.uncertain_create.as_ref() == Some(key) {
                self.uncertain_create = None;
            }
            self.cached.state = "idle".into();
            self.cached.peer_number.clear();
            self.cached.duration_seconds = 0;
            self.cached.muted = false;
        }
    }

    fn finish_terminal(
        &mut self,
        key: &SessionKey,
        events: Vec<CallManagerWireEvent>,
        delete: impl FnOnce() -> Result<()>,
    ) -> Result<()> {
        self.release_audio(key);
        // Native terminal proof and joined audio cleanup precede bookkeeping.
        // DeleteCall failure must not discard the data-lease release fact.
        self.pending_events.extend(events);
        delete()?;
        if let Some(path) = self
            .registry
            .as_mut()
            .context("Not configured")?
            .remove(key)
        {
            self.terminating.remove(&path);
            self.confirmed_hangups
                .retain(|(candidate, acknowledged)| candidate != key || acknowledged != &path);
            self.lost_call_paths.remove(&path);
        }
        Ok(())
    }

    fn refresh_availability(&mut self) -> Result<()> {
        if !self.isolated {
            return Ok(());
        }
        self.verify_service_owner()?;
        let connection = self
            .connection
            .as_ref()
            .context("No modem connection")?
            .clone();
        let modem = self.modem.as_ref().context("No modem")?.clone();
        let native_owner = self.bound_owner()?.to_owned();
        let proxy = Proxy::new(
            &connection,
            native_owner.as_str(),
            modem.as_str(),
            MODEM_INTERFACE,
        )?;
        let state: i32 = proxy.get_property("State")?;
        let lock: u32 = proxy.get_property("UnlockRequired")?;
        let voice = Proxy::new(
            &connection,
            native_owner.as_str(),
            modem.as_str(),
            VOICE_INTERFACE,
        )?;
        let emergency: bool = voice.get_property("EmergencyOnly")?;
        self.verify_service_owner()?;
        let reason = voice_service_unavailable_reason(state, lock, true, emergency);
        self.check_selected_modem()?;
        if reason.is_some() && (self.provider_identity.is_some() || self.format_admission.is_some())
        {
            self.invalidate_provider_audio();
        }
        self.cached.available = reason.is_none();
        self.cached.unavailable_reason = if reason.is_some() {
            "Modem unavailable"
        } else {
            ""
        }
        .into();
        if self.cached.available {
            let provider_ready = self.provider_baseline().and_then(|_| {
                if let Some(key) = self.audio_key().cloned() {
                    self.sample_rate(&self.path_for(&key)?)?;
                } else {
                    for (path, key) in self.registry()?.tracked() {
                        if self
                            .registry()?
                            .latest(&key)
                            .is_some_and(|u| u.phase == CallPhase::Ringing)
                        {
                            self.sample_rate(&path)?;
                        }
                    }
                }
                Ok(())
            });
            if let Err(error) = provider_ready {
                eprintln!("GSM provider audio unavailable: {error:#}");
                self.cached.available = false;
                self.cached.unavailable_reason = "Audio unavailable".into();
            }
        }
        if !self.cleanup.uncertain.is_empty() || self.uncertain_create.is_some() {
            self.cached.available = false;
            self.cached.unavailable_reason = "GSM native call reconciliation required".into();
        }
        Ok(())
    }

    fn targeted_hangup(&mut self, key: &SessionKey) -> Result<()> {
        self.ensure_control()?;
        let path = self.path_for(key)?;
        let owner = self.owner.clone();
        let stage = self.outgoing_stage.clone();
        anyhow::ensure!(
            !self.lost_call_paths.contains(&path),
            "GSM native call identity was lost"
        );
        let state: i32 = self.proxy_for(&path)?.get_property("State")?;
        self.ensure_control()?;
        self.ensure_cleanup_identity(key, &path, owner.as_ref(), stage.as_ref())?;
        if state == 0
            && self.outgoing_stage.as_ref()
                == Some(&(
                    key.clone(),
                    OutgoingStage::CreatedUnstarted { path: path.clone() },
                ))
        {
            return self.delete_created_unstarted(key);
        }
        anyhow::ensure!(state != 0, "Cannot Hangup an UNKNOWN GSM call");
        self.terminating.insert(path.clone());
        self.cleanup.failed(&path);
        if self.owner.as_ref() == Some(key) {
            self.audio.take();
            self.prepared_audio.take();
            self.format_admission = None;
            self.owned_audio_port = None;
            self.audio_deadline = None;
        }
        self.ensure_control()?;
        self.ensure_cleanup_identity(key, &path, owner.as_ref(), stage.as_ref())?;
        let result = self.proxy_for(&path)?.call::<_, _, ()>("Hangup", &());
        self.ensure_control()?;
        self.ensure_cleanup_identity(key, &path, owner.as_ref(), stage.as_ref())?;
        match result {
            Ok(()) => {
                if !self
                    .confirmed_hangups
                    .iter()
                    .any(|(candidate, acknowledged)| candidate == key && acknowledged == &path)
                {
                    self.confirmed_hangups.push((key.clone(), path.clone()));
                }
                self.cleanup.confirmed(&path);
                Ok(())
            }
            Err(error) => {
                self.cleanup.failed(&path);
                Err(error.into())
            }
        }
    }

    fn ensure_cleanup_identity(
        &self,
        key: &SessionKey,
        path: &str,
        owner: Option<&SessionKey>,
        stage: Option<&(SessionKey, OutgoingStage)>,
    ) -> Result<()> {
        anyhow::ensure!(
            self.registry()?.path_for(key) == Some(path)
                && self.owner.as_ref() == owner
                && self.outgoing_stage.as_ref() == stage
                && !self.lost_call_paths.contains(path),
            "GSM cleanup native identity changed"
        );
        Ok(())
    }

    fn delete_created_unstarted(&mut self, key: &SessionKey) -> Result<()> {
        self.ensure_control()?;
        let path = self.path_for(key)?;
        let owner = self.owner.clone();
        let stage = self.outgoing_stage.clone();
        anyhow::ensure!(
            self.owner.as_ref() == Some(key)
                && !self.lost_call_paths.contains(&path)
                && self.outgoing_stage.as_ref()
                    == Some(&(
                        key.clone(),
                        OutgoingStage::CreatedUnstarted { path: path.clone() }
                    )),
            "GSM call is not an exact never-started creation"
        );
        let state: i32 = self.proxy_for(&path)?.get_property("State")?;
        self.ensure_control()?;
        self.ensure_cleanup_identity(key, &path, owner.as_ref(), stage.as_ref())?;
        anyhow::ensure!(
            state == 0,
            "Only a never-started UNKNOWN call may be deleted"
        );
        self.terminating.insert(path.clone());
        self.cleanup.failed(&path);
        // Drop joins before any following reconciliation can publish Ended.
        self.audio.take();
        self.prepared_audio.take();
        self.format_admission = None;
        self.owned_audio_port = None;
        self.audio_deadline = None;
        self.ensure_control()?;
        self.ensure_cleanup_identity(key, &path, owner.as_ref(), stage.as_ref())?;
        let object = OwnedObjectPath::try_from(path)?;
        let result = Proxy::new(
            self.connection.as_ref().context("No modem connection")?,
            self.bound_owner()?,
            self.modem.as_ref().context("No modem")?.as_str(),
            VOICE_INTERFACE,
        )?
        .call::<_, _, ()>("DeleteCall", &(object,));
        self.ensure_control()?;
        result?;
        // Even a successful Delete reply is bookkeeping, not native absence.
        // Keep cleanup uncertainty until a fresh same-owner Calls snapshot.
        self.reconcile_paths()
    }

    fn observe_path(&mut self, path: &str) -> Result<()> {
        use yoyopod_protocol::call::CallDirection;
        anyhow::ensure!(
            self.registry()?.can_observe(path),
            "GSM registry capacity exhausted; ownership remains uncertain"
        );
        let proxy = self.proxy_for(path)?;
        let state: i32 = proxy.get_property("State")?;
        let native_direction: i32 = proxy.get_property("Direction")?;
        let number: String = proxy.get_property("Number")?;
        drop(proxy);
        self.verify_service_owner()?;
        self.check_selected_modem()?;
        let direction = match native_direction {
            1 => CallDirection::Incoming,
            2 => CallDirection::Outgoing,
            _ => bail!("Unknown GSM call direction"),
        };
        let mut phase = modem_call_phase(state);
        if self.provider_invalidated
            && self.registry()?.tracked().iter().any(|(p, _)| p == path)
            && phase != CallPhase::Ended
        {
            phase = CallPhase::Ending;
        }
        if self.initial_scan {
            self.cleanup.observe_initial(path, &phase);
        }
        if phase == CallPhase::Ended && !self.cleanup.terminal_is_trusted(path) {
            phase = CallPhase::Ending;
        }
        if self.lost_call_paths.contains(path) {
            phase = CallPhase::Ending;
        }
        // A new outgoing object after an errored Create is not the missing
        // exact reply. Observe it independently; never borrow it for that key.
        let observed_phase = phase.clone();
        let events = self.registry.as_mut().context("Not configured")?.observe(
            path,
            direction.clone(),
            phase.clone(),
            &number,
        );
        let key = self
            .registry()?
            .tracked()
            .into_iter()
            .find(|(p, _)| p == path)
            .context("Untracked call")?
            .1;
        if !self.cleanup.terminal_is_trusted(path) {
            if state != 7 {
                let _ = self.targeted_hangup(&key);
            }
            phase = CallPhase::Ending;
        } else if self.terminating.contains(path) && phase != CallPhase::Ended {
            phase = CallPhase::Ending;
        }
        // Re-project a cleanup-pending native Active as Ending, never as audio readiness.
        let events = if phase != observed_phase {
            self.registry.as_mut().expect("configured").observe(
                path,
                direction.clone(),
                phase.clone(),
                &number,
            )
        } else {
            events
        };
        if phase == CallPhase::Ended && self.cleanup.terminal_is_trusted(path) {
            let connection = self.connection.as_ref().context("No connection")?.clone();
            let modem = self.modem.as_ref().context("No modem")?.clone();
            let object = OwnedObjectPath::try_from(path.to_owned())?;
            let native_owner = self.bound_owner()?.to_owned();
            return self.finish_terminal(&key, events, || {
                let voice = Proxy::new(
                    &connection,
                    native_owner.as_str(),
                    modem.as_str(),
                    VOICE_INTERFACE,
                )?;
                let _: () = voice.call("DeleteCall", &(object,))?;
                Ok(())
            });
        }
        // Fresh discovery of a pre-existing active/held/outgoing call is never
        // offered for admission. Reconcile it through isolated termination.
        if self.owner.as_ref() != Some(&key)
            && matches!(
                phase,
                CallPhase::Active | CallPhase::Held | CallPhase::Outgoing
            )
        {
            if let Err(error) = self.targeted_hangup(&key) {
                eprintln!("GSM unowned call reconciliation failed: {error:#}");
            }
        }
        if self.owner.as_ref() == Some(&key) {
            self.cached.peer_number = number.clone();
            match phase {
                CallPhase::Active => {
                    if let Err(error) = self.start_owned_audio(&key, path) {
                        eprintln!("GSM audio unavailable: {error:#}");
                        self.audio.take();
                        self.prepared_audio.take();
                        let _ = self.targeted_hangup(&key);
                        // Do not publish Active after audio preparation failed.
                        let ending = self.registry.as_mut().expect("configured").observe(
                            path,
                            direction,
                            CallPhase::Ending,
                            &number,
                        );
                        self.pending_events.extend(ending);
                        return Ok(());
                    }
                    if self.audio.is_none() {
                        // A native Active alone is not audio readiness.
                        self.pending_events.extend(
                            self.registry.as_mut().expect("configured").observe(
                                path,
                                direction.clone(),
                                CallPhase::Preparing,
                                &number,
                            ),
                        );
                        return Ok(());
                    }
                    self.cached.state = "active".into();
                    let since = self.active_since.get_or_insert_with(Instant::now);
                    self.cached.duration_seconds = since.elapsed().as_secs();
                }
                CallPhase::Held | CallPhase::Waiting => {
                    self.audio.take();
                    self.cached.state = if phase == CallPhase::Held {
                        "held"
                    } else {
                        "waiting"
                    }
                    .into();
                }
                _ => {}
            }
        }
        self.pending_events.extend(events);
        if self.owner.as_ref() == Some(&key) && self.audio.is_some() {
            if let Some(update) = self.registry.as_mut().expect("configured").observe_audio(
                &key,
                self.cached.duration_seconds,
                self.cached.muted,
            ) {
                self.pending_events
                    .push(CallManagerWireEvent::Update(update));
            }
        }
        Ok(())
    }

    fn verified_format(&mut self, path: &str) -> Result<VerifiedPcm> {
        self.ensure_control()?;
        let connection = self
            .connection
            .as_ref()
            .context("No modem connection")?
            .clone();
        let owner = self.bound_owner()?.to_owned();
        let modem = self.modem.as_ref().context("No modem")?.clone();
        let proxy = Proxy::new(&connection, owner.as_str(), modem.as_str(), MODEM_INTERFACE)?;
        let state: i32 = proxy.get_property("State")?;
        let lock: u32 = proxy.get_property("UnlockRequired")?;
        let emergency: bool =
            Proxy::new(&connection, owner.as_str(), modem.as_str(), VOICE_INTERFACE)?
                .get_property("EmergencyOnly")?;
        self.ensure_control()?;
        if voice_service_unavailable_reason(state, lock, true, emergency).is_some() {
            self.invalidate_provider_audio();
            self.cached.unavailable_reason = "Modem unavailable".into();
            bail!("Modem unavailable");
        }
        let epoch = self.selected_epoch;
        let actual = self.provider_baseline()?;
        let format_result = {
            let proxy = self.proxy_for(path)?;
            proxy.get_property("AudioFormat")
        };
        let format: HashMap<String, zvariant::OwnedValue> = match format_result {
            Ok(format) => format,
            Err(error) => {
                if self
                    .audio_key()
                    .and_then(|key| self.registry.as_ref()?.path_for(key))
                    == Some(path)
                {
                    self.invalidate_provider_audio();
                }
                return Err(error.into());
            }
        };
        self.ensure_control()?;
        anyhow::ensure!(
            epoch == self.selected_epoch && !self.provider_invalidated,
            "GSM audio lifetime changed"
        );
        match self.provider.format(&actual, &format) {
            Ok(pcm) => Ok(pcm),
            Err(error) => {
                self.call_format_lost(path);
                Err(error)
            }
        }
    }

    fn sample_rate(&mut self, path: &str) -> Result<u32> {
        self.verified_format(path).map(|pcm| pcm.sample_rate_hz())
    }

    fn ensure_prepared_current(&mut self, key: &SessionKey, path: &str) -> Result<()> {
        let rate = self.sample_rate(path)?;
        anyhow::ensure!(
            self.format_admission.as_ref() == Some(&(key.clone(), self.selected_epoch, rate)),
            "GSM prepared audio belongs to an old admission"
        );
        Ok(())
    }

    fn ensure_created_current(&mut self, key: &SessionKey, path: &str, epoch: u64) -> Result<()> {
        self.ensure_control()?;
        self.cancellations.check(key, epoch)?;
        anyhow::ensure!(
            self.selected_epoch == epoch
                && !self.provider_invalidated
                && self.owner.as_ref() == Some(key)
                && !self.lost_call_paths.contains(path)
                && self.registry()?.path_for(key) == Some(path)
                && self.outgoing_stage.as_ref()
                    == Some(&(
                        key.clone(),
                        OutgoingStage::CreatedUnstarted { path: path.into() }
                    ))
                && !self.terminating.contains(path)
                && self.cleanup.terminal_is_trusted(path),
            "GSM created call belongs to an old or cancelled admission"
        );
        let proxy = self.proxy_for(path)?;
        let state: i32 = proxy.get_property("State")?;
        let direction: i32 = proxy.get_property("Direction")?;
        drop(proxy);
        self.ensure_control()?;
        anyhow::ensure!(
            state == 0
                && direction == 2
                && self.selected_epoch == epoch
                && !self.provider_invalidated,
            "GSM created call is no longer the admitted UNKNOWN outgoing object"
        );
        Ok(())
    }

    fn start_owned_audio(&mut self, key: &SessionKey, path: &str) -> Result<()> {
        self.cancellations.check(key, self.selected_epoch)?;
        self.ensure_prepared_current(key, path)?;
        let audio_port: String = self.proxy_for(path)?.get_property("AudioPort")?;
        self.ensure_control()?;
        if let Some(audio) = self.audio.as_mut() {
            anyhow::ensure!(
                self.owned_audio_port.as_deref() == Some(audio_port.as_str())
                    && self.provider_identity.as_ref().is_some_and(|identity| {
                        audio_inventory_contains(&identity.ports, &audio_port)
                    }),
                "GSM active audio endpoint changed"
            );
            anyhow::ensure!(audio.healthy()?, "GSM audio bridge stopped");
            return Ok(());
        }
        if self.prepared_audio.is_none() {
            let format = self.verified_format(path)?;
            self.ensure_control()?;
            self.prepared_audio = Some(self.pcm.prepare(&format)?);
        }
        if audio_port.is_empty() {
            anyhow::ensure!(
                self.audio_deadline
                    .is_some_and(|deadline| Instant::now() < deadline),
                "Modem USB audio readiness timed out"
            );
            return Ok(());
        }
        anyhow::ensure!(
            self.provider_identity
                .as_ref()
                .is_some_and(|identity| audio_inventory_contains(&identity.ports, &audio_port)),
            "GSM AudioPort is absent from current AUDIO inventory"
        );
        self.owned_audio_port = Some(audio_port.clone());
        let port = if audio_port.starts_with("/dev/") {
            std::path::PathBuf::from(audio_port)
        } else {
            std::path::PathBuf::from("/dev").join(audio_port)
        };
        let prepared = self
            .prepared_audio
            .as_ref()
            .context("USB audio not prepared")?;
        anyhow::ensure!(
            std::fs::canonicalize(port)? == prepared.port(),
            "Modem audio endpoint differs from prepared USB endpoint"
        );
        self.audio = Some(self.prepared_audio.take().expect("prepared").start()?);
        if let Err(error) = self.ensure_prepared_current(key, path) {
            self.invalidate_provider_audio();
            return Err(error);
        }
        Ok(())
    }
}

impl ModemManagerVoice {
    fn refresh_selected(&mut self) -> Result<GsmCallState> {
        if self.modem_lost && !self.clean_rediscovery {
            return Ok(self.cached.clone());
        }
        if self.generation.is_none() {
            self.cached.unavailable_reason = "GSM worker is not configured".into();
            return Ok(self.cached.clone());
        }
        if self.modem.is_none()
            && self
                .next_discovery
                .is_none_or(|next| Instant::now() >= next)
        {
            self.discover()?;
        }
        if self.modem.is_none() {
            return Ok(self.cached.clone());
        }
        self.verify_service_owner()?;
        // Cached availability is also an admission fact. A nonblocking drain
        // cannot publish it while the collector has not forwarded older loss.
        self.check_selected_modem()?;
        let messages: Vec<_> = self
            .signals
            .as_ref()
            .map(|signals| signals.messages.try_iter().collect())
            .unwrap_or_default();
        for message in messages {
            self.removal_signal(&message);
            if self.modem_lost {
                return Ok(self.cached.clone());
            }
            let header = message.header();
            if header.sender().map(|sender| sender.as_str()) != self.service_owner.as_deref() {
                continue;
            }
            if let Some("PropertiesChanged" | "StateChanged") =
                header.member().map(|member| member.as_str())
            {
                if let Some(path) = header.path() {
                    if self
                        .registry()?
                        .tracked()
                        .iter()
                        .any(|(known, _)| known == path.as_str())
                    {
                        self.observe_path(path.as_str())?;
                    }
                }
            }
        }
        // Bounded Calls-property recovery handles missed signals and bus bursts;
        // this is not global D-Bus enumeration. Tracked properties poll at 500ms.
        if self.membership_reconcile_pending
            || self.next_recovery.is_none_or(|next| Instant::now() >= next)
        {
            self.reconcile_paths()?;
            self.next_recovery = Some(Instant::now() + Duration::from_secs(3));
        } else {
            for (path, _) in self.registry()?.tracked() {
                self.observe_path(&path)?;
            }
        }
        self.refresh_availability()?;
        Ok(self.cached.clone())
    }
}

impl GsmBackend for ModemManagerVoice {
    fn selected_modem_epoch(&self) -> u64 {
        self.selected_epoch
    }
    fn take_modem_loss(&mut self) -> Option<u64> {
        if std::mem::take(&mut self.loss_pending) {
            self.generation
        } else {
            None
        }
    }
    fn reconciliation(&self) -> Option<GsmReconciliation> {
        Some(GsmReconciliation {
            generation: self.generation?,
            admission_epoch: self.selected_epoch,
            native_owner: self
                .service_bus_id
                .as_ref()
                .zip(self.service_owner.as_ref())
                .map(|(bus, owner)| format!("{bus}/{owner}")),
            native_calls_quiescent: !self.service_invalidated
                && !self.modem_lost
                && self.idle_calls_proven
                && self.service_owner.is_some()
                && self.service_bus_id.is_some()
                && self.isolated
                && self.modem.is_some()
                && self.registry.as_ref()?.tracked().is_empty()
                && self.terminating.is_empty()
                && self.owner.is_none()
                && self.audio_deadline.is_none()
                && self.uncertain_create.is_none()
                && self.cleanup.uncertain.is_empty(),
            audio_released: self.audio.is_none() && self.prepared_audio.is_none(),
        })
    }
    fn configure(&mut self, generation: u64, pcm_sample_rate_hz: Option<u32>) -> Result<()> {
        anyhow::ensure!(
            pcm_sample_rate_hz.is_none(),
            "GSM PCM rate override bypasses current provider evidence"
        );
        if let Some(current) = self.generation {
            anyhow::ensure!(
                !self.service_invalidated
                    && generation > current
                    && self.registry()?.tracked().is_empty()
                    && self.owner.is_none(),
                "GSM generation change requires resolved sessions"
            );
        }
        self.cancellations.configure(generation)?;
        self.generation = Some(generation);
        self.registry = Some(crate::gsm_calls::GsmCallRegistry::new(generation));
        self.initial_scan = true;
        self.modem = None;
        self.next_discovery = None;
        Ok(())
    }
    fn owns_voice(&self, key: &SessionKey) -> bool {
        self.owner.as_ref() == Some(key)
    }
    fn drain_call_events(&mut self) -> Vec<CallManagerWireEvent> {
        std::mem::take(&mut self.pending_events)
    }

    fn refresh(&mut self) -> Result<GsmCallState> {
        let result = self.refresh_selected();
        if result.is_err() && self.modem.is_some() && !self.modem_lost && !self.service_invalidated
        {
            // A timeout or permission failure is not proof of disappearance.
            // Confirm the selected interfaces through the retained owner's OM.
            let _ = self.check_selected_modem();
        }
        result
    }

    fn dial_session(&mut self, key: &SessionKey, number: &str) -> Result<()> {
        use yoyopod_protocol::call::CallTransport;
        let epoch = self.selected_epoch;
        anyhow::ensure!(
            key.transport == CallTransport::Gsm && Some(key.generation) == self.generation,
            "Unknown or stale GSM generation"
        );
        anyhow::ensure!(self.owner.is_none(), "GSM voice already owned");
        anyhow::ensure!(
            self.registry()?.is_fresh_key(key),
            "GSM session key is stale or already used"
        );
        anyhow::ensure!(
            self.registry()?.tracked().is_empty() && self.cleanup.uncertain.is_empty(),
            "GSM native reconciliation required before dialing"
        );
        self.cancellations.register(key, epoch)?;
        self.ensure_control()?;
        self.refresh_availability()?;
        anyhow::ensure!(self.cached.available, "{}", self.cached.unavailable_reason);
        anyhow::ensure!(
            epoch == self.selected_epoch && !self.provider_invalidated,
            "GSM dialing admission expired"
        );
        let properties = HashMap::from([(
            "number",
            zvariant::OwnedValue::try_from(zvariant::Value::from(number.to_owned()))?,
        )]);
        let cancellations = self.cancellations.clone();
        let admission = cancellations
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("GSM admission lock poisoned"))?;
        AdmissionCancellations::ensure_current(&admission, key, epoch)?;
        self.owner = Some(key.clone());
        self.uncertain_create = Some(key.clone());
        self.outgoing_stage = Some((key.clone(), OutgoingStage::Creating));
        self.idle_calls_proven = false;
        drop(admission);
        let create = Proxy::new(
            self.connection.as_ref().context("No modem connection")?,
            self.bound_owner()?,
            self.modem.as_ref().context("No modem")?.as_str(),
            VOICE_INTERFACE,
        )?
        .call::<_, _, OwnedObjectPath>("CreateCall", &(properties,));
        let path = match create {
            Ok(path) => path,
            Err(error) => {
                // Neither timeout nor a late native error proves no creation.
                let _ = self.ensure_control();
                return Err(error.into());
            }
        };
        // Bind the returned native identity before consuming any lifecycle
        // evidence or clearing Create uncertainty. Validation still owns it.
        self.registry
            .as_mut()
            .context("Not configured")?
            .register_outgoing(key, path.as_str())?;
        self.outgoing_stage = Some((
            key.clone(),
            OutgoingStage::CreatedUnstarted {
                path: path.to_string(),
            },
        ));
        self.uncertain_create = None;
        self.pending_events
            .extend(self.registry.as_mut().expect("configured").observe(
                path.as_str(),
                yoyopod_protocol::call::CallDirection::Outgoing,
                CallPhase::Preparing,
                number,
            ));
        let preparation = (|| {
            self.ensure_created_current(key, path.as_str(), epoch)?;
            let format = self.verified_format(path.as_str())?;
            self.format_admission = Some((key.clone(), epoch, format.sample_rate_hz()));
            self.ensure_created_current(key, path.as_str(), epoch)?;
            self.prepared_audio = Some(self.pcm.prepare(&format)?);
            self.audio_deadline = Some(Instant::now() + Duration::from_secs(8));
            self.ensure_created_current(key, path.as_str(), epoch)?;
            self.ensure_prepared_current(key, path.as_str())?;
            self.ensure_created_current(key, path.as_str(), epoch)?;
            let cancellations = self.cancellations.clone();
            let admission = cancellations
                .0
                .lock()
                .map_err(|_| anyhow::anyhow!("GSM admission lock poisoned"))?;
            AdmissionCancellations::ensure_current(&admission, key, epoch)?;
            // The same lock used by send/enqueue linearizes cancellation with
            // this sticky dispatch decision; cancellation after it needs proof.
            self.outgoing_stage = Some((
                key.clone(),
                OutgoingStage::StartDispatched {
                    path: path.to_string(),
                },
            ));
            self.cleanup.failed(path.as_str());
            Ok(())
        })();
        if let Err(error) = preparation {
            let _ = self.delete_created_unstarted(key);
            return Err(error);
        }
        // Sticky before dispatch: no reply/error/UNKNOWN/CallDeleted can turn
        // this key back into a deletable never-started object.
        let result = self
            .proxy_for(path.as_str())?
            .call::<_, _, ()>("Start", &());
        self.ensure_control()?;
        anyhow::ensure!(
            epoch == self.selected_epoch
                && !self.provider_invalidated
                && self.owner.as_ref() == Some(key)
                && self.registry()?.path_for(key) == Some(path.as_str())
                && !self.terminating.contains(path.as_str()),
            "GSM Start response belongs to an old admission"
        );
        self.ensure_prepared_current(key, path.as_str())?;
        self.cancellations.check(key, epoch)?;
        result?;
        self.cleanup.confirmed(path.as_str());
        Ok(())
    }

    fn apply_call(&mut self, command: &CallCommand) -> Result<()> {
        self.apply_call_with_request("", command)
    }
    fn apply_call_with_request(&mut self, request_id: &str, command: &CallCommand) -> Result<()> {
        use yoyopod_protocol::call::CallAction;
        let mut diagnostic = GsmActionDiagnostic {
            request_id,
            command,
            native_id: self
                .registry
                .as_ref()
                .and_then(|registry| registry.path_for(&command.key))
                .map(str::to_owned),
            native_owner: self.reconciliation().and_then(|fact| fact.native_owner),
            native_accept_dispatched: Some(false),
        };
        let result = (|| {
            let path = diagnostic.observe("session_lookup", self.path_for(&command.key))?;
            diagnostic.observe("session_control", self.ensure_control())?;
            match command.action {
                CallAction::Answer => {
                    let epoch = self.selected_epoch;
                    self.cancellations.register(&command.key, epoch)?;
                    anyhow::ensure!(self.owner.is_none(), "GSM voice already owned");
                    anyhow::ensure!(
                        self.cleanup.uncertain.is_empty()
                            && self
                                .registry()?
                                .tracked()
                                .iter()
                                .all(|(_, key)| key == &command.key),
                        "GSM native reconciliation required before answering"
                    );
                    let update = self
                        .registry()?
                        .latest(&command.key)
                        .context("Unobserved call")?;
                    anyhow::ensure!(
                        update.phase == CallPhase::Ringing,
                        "GSM call is not ringing"
                    );
                    self.owner = Some(command.key.clone());
                    let preparation = diagnostic
                        .observe("audio_metadata", self.verified_format(&path))
                        .and_then(|format| {
                            self.format_admission = Some((
                                command.key.clone(),
                                self.selected_epoch,
                                format.sample_rate_hz(),
                            ));
                            diagnostic.observe("pcm_control", self.ensure_control())?;
                            diagnostic.observe("pcm_prepare", self.pcm.prepare(&format))
                        });
                    match preparation {
                        Ok(prepared) => self.prepared_audio = Some(prepared),
                        Err(error) => {
                            let _ = self.targeted_hangup(&command.key);
                            return Err(error);
                        }
                    }
                    self.audio_deadline = Some(Instant::now() + Duration::from_secs(8));
                    diagnostic.observe("accept_control", self.ensure_control())?;
                    diagnostic.observe(
                        "accept_format",
                        self.ensure_prepared_current(&command.key, &path),
                    )?;
                    let cancellations = self.cancellations.clone();
                    let admission = cancellations
                        .0
                        .lock()
                        .map_err(|_| anyhow::anyhow!("GSM admission lock poisoned"))?;
                    AdmissionCancellations::ensure_current(&admission, &command.key, epoch)?;
                    self.accept_dispatched = Some(command.key.clone());
                    self.cleanup.failed(&path);
                    diagnostic.native_accept_dispatched = Some(true);
                    drop(admission);
                    let proxy = diagnostic.observe("accept_proxy", self.proxy_for(&path))?;
                    diagnostic.record("native_accept", "dispatch", None);
                    let accept_result = diagnostic.observe(
                        "native_accept",
                        proxy.call::<_, _, ()>("Accept", &()).map_err(Into::into),
                    );
                    drop(proxy);
                    diagnostic.observe("accept_response_control", self.ensure_control())?;
                    anyhow::ensure!(
                        epoch == self.selected_epoch && !self.provider_invalidated,
                        "GSM Accept response belongs to an old audio lifetime"
                    );
                    self.cancellations.check(&command.key, epoch)?;
                    if let Err(error) = accept_result {
                        self.cleanup.failed(&path);
                        return Err(error);
                    }
                    self.cleanup.confirmed(&path);
                    Ok(())
                }
                CallAction::Reject(_) | CallAction::Hangup => self.targeted_hangup(&command.key),
                CallAction::SetMute(muted) => {
                    anyhow::ensure!(
                        self.owner.as_ref() == Some(&command.key),
                        "GSM session does not own audio"
                    );
                    self.audio
                        .as_ref()
                        .context("No GSM call audio")?
                        .set_mute(muted);
                    self.cached.muted = muted;
                    Ok(())
                }
            }
        })();
        diagnostic.observe("backend_action", result)
    }
    fn dial(&mut self, number: &str) -> Result<()> {
        let _ = number;
        bail!("GSM dialing requires a runtime-owned canonical session key")
    }
    fn hangup(&mut self) -> Result<()> {
        if let Some(key) = self.owner.clone() {
            self.targeted_hangup(&key)?;
        }
        self.audio.take();
        self.prepared_audio.take();
        Ok(())
    }
    fn mute(&mut self, muted: bool) -> Result<()> {
        let key = self.owner.clone().context("No GSM audio owner")?;
        self.apply_call(&CallCommand {
            key,
            action: yoyopod_protocol::call::CallAction::SetMute(muted),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};

    #[test]
    fn gsm_outgoing_cancellation_lifetime_is_bounded_without_reviving_retired_or_older_live_keys() {
        let latch = AdmissionCancellations::default();
        latch.configure(9).unwrap();
        let key = |serial| SessionKey {
            transport: yoyopod_protocol::call::CallTransport::Gsm,
            generation: 9,
            call_id: format!("runtime-outgoing-{serial}"),
        };
        let older = key(1);
        latch.register(&older, 3).unwrap();
        for serial in 2..2048 {
            let current = key(serial);
            latch.register(&current, 3).unwrap();
            latch.cancel(&current).unwrap();
            assert!(latch.check(&current, 3).is_err());
            latch.retire(&current).unwrap();
            assert!(latch.register(&current, 3).is_err());
            latch.cancel(&key(10_000 + serial)).unwrap();
            assert_eq!(latch.0.lock().unwrap().entries.len(), 1);
            latch.check(&older, 3).unwrap();
        }
        for serial in 2048..2048 + yoyopod_protocol::call::MAX_LIVE_CALLS as u64 - 1 {
            latch.register(&key(serial), 3).unwrap();
        }
        assert!(latch.register(&key(9000), 3).is_err());
        assert_eq!(
            latch.0.lock().unwrap().entries.len(),
            yoyopod_protocol::call::MAX_LIVE_CALLS
        );
        assert!(latch.configure(10).is_err());
        let outstanding: Vec<_> = latch
            .0
            .lock()
            .unwrap()
            .entries
            .iter()
            .map(|(key, _, _)| key.clone())
            .collect();
        for key in outstanding {
            latch.retire(&key).unwrap();
        }
        latch.configure(10).unwrap();
        let fresh = SessionKey {
            generation: 10,
            ..older.clone()
        };
        latch.register(&fresh, 4).unwrap();
        latch.cancel(&older).unwrap();
        latch.retire(&older).unwrap();
        latch.check(&fresh, 4).unwrap();
        assert_eq!(latch.0.lock().unwrap().entries.len(), 1);
    }

    struct PrivateBus {
        daemon: std::process::Child,
        address: String,
    }
    impl PrivateBus {
        fn start() -> Self {
            use std::io::BufRead;
            let mut daemon = std::process::Command::new("/usr/bin/dbus-daemon")
                .args(["--session", "--nofork", "--print-address=1"])
                .stdin(std::process::Stdio::null())
                .stdout(std::process::Stdio::piped())
                .spawn()
                .expect("private test D-Bus daemon");
            let mut address = String::new();
            std::io::BufReader::new(daemon.stdout.take().unwrap())
                .read_line(&mut address)
                .unwrap();
            Self {
                daemon,
                address: address.trim().into(),
            }
        }
        fn connection(&self) -> Connection {
            Builder::address(self.address.as_str())
                .unwrap()
                .method_timeout(Duration::from_secs(3))
                .build()
                .unwrap()
        }
    }
    impl Drop for PrivateBus {
        fn drop(&mut self) {
            let _ = self.daemon.kill();
            let _ = self.daemon.wait();
        }
    }

    struct DiagnosticCall {
        pcm_format: bool,
    }
    #[zbus::interface(name = "org.freedesktop.ModemManager1.Call")]
    impl DiagnosticCall {
        #[zbus(property)]
        fn state(&self) -> i32 {
            3
        }
        #[zbus(property)]
        fn direction(&self) -> i32 {
            1
        }
        #[zbus(property)]
        fn number(&self) -> &str {
            "+49123456789"
        }
        #[zbus(property)]
        fn audio_format(&self) -> zbus::fdo::Result<HashMap<String, zvariant::OwnedValue>> {
            if !self.pcm_format {
                return Err(zbus::fdo::Error::Failed("metadata\n\"root cause\"".into()));
            }
            Ok(HashMap::from([
                ("rate".into(), 16000_u32.into()),
                ("encoding".into(), zvariant::Str::from("pcm").into()),
                ("resolution".into(), zvariant::Str::from("s16le").into()),
            ]))
        }
        fn accept(&self) {
            panic!("preparation failure must precede native Accept");
        }
        fn hangup(&self) -> zbus::fdo::Result<()> {
            eprintln!("fixture-targeted-hangup:{TEST_RINGING_CALL}");
            Err(zbus::fdo::Error::Failed(
                "cleanup failure must not replace preparation error".into(),
            ))
        }
    }

    // Removing an error-stage log, losing request/key correlation, swallowing the
    // original error, or dispatching Accept before preparation must fail this test.
    #[test]
    fn gsm_answer_diagnostics_preserve_keyed_failure_before_targeted_cleanup() {
        const CHILD: &str = "YOYOPOD_TEST_ACCEPT_DIAGNOSTIC";
        const REQUEST: &str = "accept-request\n\"quoted\"";
        if let Ok(scenario) = std::env::var(CHILD) {
            let bus = PrivateBus::start();
            let (owner, mut backend, _) = reconnect_fixture(&bus);
            let pcm_format = scenario == "pcm";
            if pcm_format {
                assert!(
                    !UsbPcmAudio::available(),
                    "off-Pi fixture must not own real PCM hardware"
                );
            }
            owner
                .object_server()
                .at(TEST_RINGING_CALL, DiagnosticCall { pcm_format })
                .unwrap();
            owner
                .object_server()
                .interface::<_, ReconnectVoice>(TEST_MODEM0)
                .unwrap()
                .get()
                .paths
                .lock()
                .unwrap()
                .push(OwnedObjectPath::try_from(TEST_RINGING_CALL).unwrap());
            backend.next_recovery = None;
            backend.refresh().unwrap();
            let key = backend.registry().unwrap().tracked()[0].1.clone();
            backend.drain_call_events();
            let worker = GsmWorker::with_backend(backend);
            worker
                .send(GsmCommand::Action {
                    request_id: REQUEST.into(),
                    command: CallCommand {
                        key: key.clone(),
                        action: yoyopod_protocol::call::CallAction::Answer,
                    },
                })
                .unwrap();
            loop {
                if let GsmEvent::Completed {
                    request_id,
                    key: completed,
                    error,
                    voice_held,
                } = worker.events.recv_timeout(Duration::from_secs(5)).unwrap()
                {
                    assert_eq!(request_id, REQUEST);
                    assert_eq!(completed, key);
                    let error = error.unwrap();
                    assert!(!error.contains("cleanup failure"));
                    if pcm_format {
                        assert_eq!(error, "GSM USB PCM or ALSA tools unavailable");
                    } else {
                        assert!(error.contains("metadata\n\"root cause\""), "{error}");
                    }
                    assert!(
                        voice_held,
                        "uncertain targeted cleanup must retain keyed ownership"
                    );
                    break;
                }
            }
            return;
        }
        for (scenario, stage, error_text) in [
            ("metadata", "audio_metadata", "metadata\n\"root cause\""),
            (
                "pcm",
                "pcm_prepare",
                "GSM USB PCM or ALSA tools unavailable",
            ),
        ] {
            let output = std::process::Command::new(std::env::current_exe().unwrap())
                .args(["--exact", "gsm::tests::gsm_answer_diagnostics_preserve_keyed_failure_before_targeted_cleanup", "--nocapture"])
                .env(CHILD, scenario).output().unwrap();
            assert!(
                output.status.success(),
                "{}",
                String::from_utf8_lossy(&output.stderr)
            );
            let stderr = String::from_utf8(output.stderr).unwrap();
            let records: Vec<(usize, serde_json::Value)> = stderr
                .lines()
                .enumerate()
                .filter(|(_, line)| line.starts_with('{'))
                .map(|(index, line)| {
                    (
                        index,
                        serde_json::from_str::<serde_json::Value>(line)
                            .expect("single escaped JSON log line"),
                    )
                })
                .filter(|(_, record)| record["event"] == "gsm_action")
                .collect();
            let (failed_at, failure) = records
                .iter()
                .find(|(_, record)| record["stage"] == stage && record["outcome"] == "error")
                .unwrap_or_else(|| panic!("missing {stage} failure diagnostics: {stderr}"));
            assert_eq!(failure["request_id"], REQUEST);
            assert_eq!(failure["key"]["transport"], "gsm");
            assert_eq!(failure["key"]["generation"], 7);
            assert_eq!(failure["key"]["call_id"], "gsm-1");
            assert_eq!(failure["native_id"], TEST_RINGING_CALL);
            assert!(failure["native_owner"]
                .as_str()
                .is_some_and(|owner| owner.contains("/:")));
            assert_eq!(failure["operation"], "answer");
            assert_eq!(failure["native_accept_dispatched"], false);
            assert!(failure["error"].as_str().unwrap().contains(error_text));
            let cleanup_at = stderr
                .lines()
                .position(|line| line.starts_with("fixture-targeted-hangup:"))
                .unwrap();
            assert!(
                *failed_at < cleanup_at,
                "failure evidence must precede native cleanup"
            );
            let completion = records
                .iter()
                .find(|(_, record)| record["stage"] == "command" && record["outcome"] == "error")
                .unwrap();
            assert_eq!(completion.1["error"], failure["error"]);
            assert!(
                records
                    .iter()
                    .any(|(_, record)| record["stage"] == "command"
                        && record["outcome"] == "dispatch")
            );
            assert!(!records
                .iter()
                .any(|(_, record)| record["stage"] == "native_accept"));
            assert!(
                !stderr.contains("+49123456789"),
                "diagnostics leaked a phone number"
            );
            assert!(
                !String::from_utf8(output.stdout)
                    .unwrap()
                    .contains("gsm_action"),
                "stdout is protocol-owned"
            );
        }
    }
    struct ReplacementCall(Arc<std::sync::atomic::AtomicUsize>);
    #[zbus::interface(name = "org.freedesktop.ModemManager1.Call")]
    impl ReplacementCall {
        fn hangup(&self) {
            self.0.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        }
    }
    struct EmptyCalls {
        gate: Mutex<Option<(Sender<()>, Receiver<()>)>>,
    }
    #[zbus::interface(name = "org.freedesktop.ModemManager1.Modem.Voice")]
    impl EmptyCalls {
        #[zbus(property)]
        fn calls(&self) -> Vec<OwnedObjectPath> {
            if let Some((entered, release)) = self.gate.lock().unwrap().take() {
                entered.send(()).unwrap();
                release.recv_timeout(Duration::from_secs(3)).unwrap();
            }
            Vec::new()
        }
    }
    fn old_native_backend(bus: &PrivateBus, old: &Connection) -> (ModemManagerVoice, SessionKey) {
        use yoyopod_protocol::call::{CallDirection, CallTransport};
        let mut backend = ModemManagerVoice::default();
        backend.configure(7, None).unwrap();
        backend.connection = Some(bus.connection());
        backend.service_owner = Some(old.unique_name().unwrap().to_string());
        backend.service_bus_id =
            Some(ModemManagerVoice::bus_id(backend.connection.as_ref().unwrap()).unwrap());
        backend.isolated = true;
        backend.modem = Some(OwnedObjectPath::try_from("/modem/0").unwrap());
        let key = SessionKey {
            transport: CallTransport::Gsm,
            generation: 7,
            call_id: "runtime-outgoing-1".into(),
        };
        let registry = backend.registry.as_mut().unwrap();
        registry.register_outgoing(&key, "/call/0").unwrap();
        registry.observe(
            "/call/0",
            CallDirection::Outgoing,
            CallPhase::Active,
            "+49123456789",
        );
        backend.owner = Some(key.clone());
        (backend, key)
    }
    fn allow_replacement(connection: &Connection) {
        use zbus::fdo::RequestNameFlags;
        connection
            .request_name_with_flags(
                DESTINATION,
                RequestNameFlags::AllowReplacement | RequestNameFlags::DoNotQueue,
            )
            .unwrap();
    }

    const TEST_MODEM0: &str = "/org/freedesktop/ModemManager1/Modem/0";
    const TEST_MODEM2: &str = "/org/freedesktop/ModemManager1/Modem/2";
    const TEST_RINGING_CALL: &str = "/org/freedesktop/ModemManager1/Call/42";
    struct ReconnectRingingCall;
    #[zbus::interface(name = "org.freedesktop.ModemManager1.Call")]
    impl ReconnectRingingCall {
        #[zbus(property)]
        fn state(&self) -> i32 {
            3
        }
        #[zbus(property)]
        fn direction(&self) -> i32 {
            1
        }
        #[zbus(property)]
        fn number(&self) -> &str {
            "+49123456789"
        }
    }
    struct ReconnectManager {
        version: &'static str,
    }
    #[zbus::interface(name = "org.freedesktop.ModemManager1")]
    impl ReconnectManager {
        #[zbus(property)]
        fn version(&self) -> &str {
            self.version
        }
    }
    struct ReconnectModem;
    #[zbus::interface(name = "org.freedesktop.ModemManager1.Modem")]
    impl ReconnectModem {
        #[zbus(property)]
        fn manufacturer(&self) -> &str {
            "QUALCOMM INCORPORATED"
        }
        #[zbus(property)]
        fn model(&self) -> &str {
            "SIMCOM_SIM7600G-H"
        }
        #[zbus(property)]
        fn revision(&self) -> &str {
            "LE20B04SIM7600G22"
        }
        #[zbus(property)]
        fn hardware_revision(&self) -> &str {
            "10000"
        }
        #[zbus(property)]
        fn plugin(&self) -> &str {
            "simtech"
        }
        #[zbus(property)]
        fn primary_port(&self) -> &str {
            "cdc-wdm0"
        }
        #[zbus(property)]
        fn ports(&self) -> Vec<(String, u32)> {
            vec![("cdc-wdm0".into(), 6)]
        }
        #[zbus(property)]
        fn state(&self) -> i32 {
            8
        }
        #[zbus(property)]
        fn unlock_required(&self) -> u32 {
            1
        }
    }
    type PropertyGate = Arc<Mutex<Option<(Sender<()>, Receiver<()>)>>>;
    struct ReconnectVoice {
        reads: Arc<std::sync::atomic::AtomicUsize>,
        creates: Arc<std::sync::atomic::AtomicUsize>,
        gate: PropertyGate,
        fail: Arc<std::sync::atomic::AtomicBool>,
        paths: Arc<Mutex<Vec<OwnedObjectPath>>>,
    }
    #[zbus::interface(name = "org.freedesktop.ModemManager1.Modem.Voice")]
    impl ReconnectVoice {
        fn create_call(
            &self,
            _properties: HashMap<String, zvariant::OwnedValue>,
        ) -> OwnedObjectPath {
            self.creates.fetch_add(1, Ordering::SeqCst);
            OwnedObjectPath::try_from("/org/freedesktop/ModemManager1/Call/99").unwrap()
        }
        #[zbus(property)]
        fn emergency_only(&self) -> bool {
            false
        }
        #[zbus(property)]
        async fn calls(&self) -> zbus::fdo::Result<Vec<OwnedObjectPath>> {
            self.reads.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            let paths = self.paths.lock().unwrap().clone();
            let gate = self.gate.lock().unwrap().take();
            if let Some((entered, release)) = gate {
                entered.send(()).unwrap();
                let deadline = Instant::now() + Duration::from_secs(3);
                loop {
                    match release.try_recv() {
                        Ok(()) => break,
                        Err(mpsc::TryRecvError::Empty) if Instant::now() < deadline => {
                            async_io::Timer::after(Duration::from_millis(5)).await;
                        }
                        _ => return Err(zbus::fdo::Error::Failed("fixture gate expired".into())),
                    }
                }
            }
            if self.fail.load(Ordering::SeqCst) {
                return Err(zbus::fdo::Error::Failed("transient read error".into()));
            }
            Ok(paths)
        }
    }
    fn reconnect_fixture(
        bus: &PrivateBus,
    ) -> (
        Connection,
        ModemManagerVoice,
        Arc<std::sync::atomic::AtomicUsize>,
    ) {
        reconnect_fixture_timeout(bus, Duration::from_secs(3))
    }
    fn reconnect_fixture_timeout(
        bus: &PrivateBus,
        deadline: Duration,
    ) -> (
        Connection,
        ModemManagerVoice,
        Arc<std::sync::atomic::AtomicUsize>,
    ) {
        reconnect_fixture_capacity(bus, deadline, 128)
    }
    fn reconnect_fixture_capacity(
        bus: &PrivateBus,
        deadline: Duration,
        capacity: usize,
    ) -> (
        Connection,
        ModemManagerVoice,
        Arc<std::sync::atomic::AtomicUsize>,
    ) {
        let owner = bus.connection();
        owner
            .object_server()
            .at("/org/freedesktop/ModemManager1", zbus::fdo::ObjectManager)
            .unwrap();
        owner
            .object_server()
            .at(
                "/org/freedesktop/ModemManager1",
                ReconnectManager { version: "1.24.0" },
            )
            .unwrap();
        let reads = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        owner
            .object_server()
            .at(TEST_MODEM0, ReconnectModem)
            .unwrap();
        owner
            .object_server()
            .at(
                TEST_MODEM0,
                ReconnectVoice {
                    reads: reads.clone(),
                    creates: Arc::new(std::sync::atomic::AtomicUsize::new(0)),
                    gate: Arc::new(Mutex::new(None)),
                    fail: Arc::new(std::sync::atomic::AtomicBool::new(false)),
                    paths: Arc::new(Mutex::new(Vec::new())),
                },
            )
            .unwrap();
        allow_replacement(&owner);
        let mut backend = ModemManagerVoice::default();
        backend.configure(7, None).unwrap();
        backend.provider = crate::gsm_provider::ProviderGate::test_fixture();
        backend.connection = Some(
            Builder::address(bus.address.as_str())
                .unwrap()
                .method_timeout(deadline)
                .build()
                .unwrap(),
        );
        backend.signals = Some(
            ModemSignals::start_with_capacity(
                backend.connection.as_ref().unwrap(),
                owner.unique_name().unwrap().as_str(),
                capacity,
            )
            .unwrap(),
        );
        assert!(backend.refresh().unwrap().available);
        (owner, backend, reads)
    }
    fn remove_reconnect_modem(owner: &Connection) {
        owner
            .object_server()
            .remove::<ReconnectModem, _>(TEST_MODEM0)
            .unwrap();
        owner
            .object_server()
            .remove::<ReconnectVoice, _>(TEST_MODEM0)
            .unwrap();
    }

    #[test]
    fn gsm_outgoing_qualified_clean_idle_dispatches_create_without_a_call_format() {
        let bus = PrivateBus::start();
        let (owner, mut backend, _) = reconnect_fixture(&bus);
        backend.configure(9, None).unwrap();
        assert!(backend.refresh().unwrap().available);
        assert!(backend.registry().unwrap().tracked().is_empty());
        assert!(backend.prepared_audio.is_none());
        let voice = owner
            .object_server()
            .interface::<_, ReconnectVoice>(TEST_MODEM0)
            .unwrap();
        assert!(voice.get().paths.lock().unwrap().is_empty());
        let creates = voice.get().creates.clone();
        let key = SessionKey {
            transport: yoyopod_protocol::call::CallTransport::Gsm,
            generation: 9,
            call_id: "runtime-outgoing-1".into(),
        };
        let result = backend.dial_session(&key, "+49123456789");
        // This baseline asserts real RPC dispatch only. Ordered returned-UNKNOWN,
        // PCM preparation and Start fixtures follow after the genuine RED gate.
        assert_eq!(
            creates.load(Ordering::SeqCst),
            1,
            "qualified idle did not dispatch CreateCall: {result:?}"
        );
    }

    const TEST_OUTGOING_CALL: &str = "/org/freedesktop/ModemManager1/Call/99";

    #[derive(Clone, Copy, Debug, PartialEq, Eq)]
    enum ControlBoundary {
        Create,
        Prepare,
        Start,
        Accept,
    }

    async fn wait_native_boundary(gate: &PropertyGate) -> zbus::fdo::Result<()> {
        let held = gate.lock().unwrap().take();
        if let Some((entered, release)) = held {
            entered.send(()).unwrap();
            let deadline = Instant::now() + Duration::from_secs(3);
            loop {
                match release.try_recv() {
                    Ok(()) => break,
                    Err(mpsc::TryRecvError::Empty) if Instant::now() < deadline => {
                        async_io::Timer::after(Duration::from_millis(5)).await;
                    }
                    _ => {
                        return Err(zbus::fdo::Error::Failed(
                            "synthetic native boundary expired".into(),
                        ))
                    }
                }
            }
        }
        Ok(())
    }

    #[derive(Default)]
    struct OutgoingEffects {
        trace: Mutex<Vec<String>>,
        paths: Mutex<Vec<OwnedObjectPath>>,
        created: std::sync::atomic::AtomicBool,
        format_seen: std::sync::atomic::AtomicBool,
        state: std::sync::atomic::AtomicI32,
        direction: std::sync::atomic::AtomicI32,
        rate: std::sync::atomic::AtomicU32,
        starts: std::sync::atomic::AtomicUsize,
        accepts: std::sync::atomic::AtomicUsize,
        hangups: std::sync::atomic::AtomicUsize,
        deletes: Mutex<Vec<String>>,
        fail_delete: std::sync::atomic::AtomicBool,
        fail_prepare: std::sync::atomic::AtomicBool,
        fail_create: std::sync::atomic::AtomicBool,
        fail_start: std::sync::atomic::AtomicBool,
        fail_hangup: std::sync::atomic::AtomicBool,
        empty_port: std::sync::atomic::AtomicBool,
        state_gate: PropertyGate,
        create_gate: PropertyGate,
        prepare_gate: PropertyGate,
        start_gate: PropertyGate,
        accept_gate: PropertyGate,
    }
    impl OutgoingEffects {
        fn record(&self, effect: &str) {
            self.trace.lock().unwrap().push(effect.into());
        }
    }
    struct OutgoingVoice(Arc<OutgoingEffects>);
    #[zbus::interface(name = "org.freedesktop.ModemManager1.Modem.Voice")]
    impl OutgoingVoice {
        #[zbus(property)]
        fn emergency_only(&self) -> bool {
            false
        }
        #[zbus(property)]
        fn calls(&self) -> Vec<OwnedObjectPath> {
            self.0.paths.lock().unwrap().clone()
        }
        async fn create_call(
            &self,
            properties: HashMap<String, zvariant::OwnedValue>,
        ) -> zbus::fdo::Result<OwnedObjectPath> {
            assert_eq!(
                properties
                    .get("number")
                    .and_then(|v| <&str>::try_from(v).ok()),
                Some("+49123456789")
            );
            self.0.record("create");
            if self.0.fail_create.load(Ordering::SeqCst) {
                return Err(zbus::fdo::Error::Failed(
                    "synthetic ambiguous Create error".into(),
                ));
            }
            self.0.created.store(true, Ordering::SeqCst);
            let path = OwnedObjectPath::try_from(TEST_OUTGOING_CALL).unwrap();
            self.0.paths.lock().unwrap().push(path.clone());
            wait_native_boundary(&self.0.create_gate).await?;
            Ok(path)
        }
        fn delete_call(&self, path: OwnedObjectPath) -> zbus::fdo::Result<()> {
            self.0.record("delete");
            self.0.deletes.lock().unwrap().push(path.to_string());
            if self.0.fail_delete.load(Ordering::SeqCst) {
                return Err(zbus::fdo::Error::Failed("synthetic delete failure".into()));
            }
            self.0.paths.lock().unwrap().retain(|p| p != &path);
            Ok(())
        }
    }
    struct OutgoingCall(Arc<OutgoingEffects>);
    #[zbus::interface(name = "org.freedesktop.ModemManager1.Call")]
    impl OutgoingCall {
        #[zbus(property)]
        async fn state(
            &self,
            #[zbus(header)] header: Option<zbus::message::Header<'_>>,
        ) -> zbus::fdo::Result<i32> {
            let state = self.0.state.load(Ordering::SeqCst);
            // A fresh zbus proxy populates its Lazy cache through GetAll;
            // either Properties reply carries this bounded State observation.
            // The preceding OM snapshot is not a Properties Get/GetAll read.
            let gate = if header
                .as_ref()
                .and_then(|h| h.member())
                .is_some_and(|m| matches!(m.as_str(), "Get" | "GetAll"))
            {
                self.0.state_gate.lock().unwrap().take()
            } else {
                None
            };
            if let Some((entered, release)) = gate {
                entered.send(()).unwrap();
                let deadline = Instant::now() + Duration::from_secs(3);
                loop {
                    match release.try_recv() {
                        Ok(()) => break,
                        Err(mpsc::TryRecvError::Empty) if Instant::now() < deadline => {
                            async_io::Timer::after(Duration::from_millis(5)).await;
                        }
                        _ => {
                            return Err(zbus::fdo::Error::Failed(
                                "synthetic State gate expired".into(),
                            ))
                        }
                    }
                }
            }
            Ok(state)
        }
        #[zbus(property)]
        fn direction(&self) -> i32 {
            self.0.direction.load(Ordering::SeqCst)
        }
        #[zbus(property)]
        fn number(&self) -> &str {
            "+49123456789"
        }
        #[zbus(property)]
        fn audio_format(&self) -> HashMap<String, zvariant::OwnedValue> {
            if self.0.created.load(Ordering::SeqCst)
                && !self.0.format_seen.swap(true, Ordering::SeqCst)
            {
                self.0.record("format");
            }
            let rate = self.0.rate.load(Ordering::SeqCst);
            if rate == 0 {
                return HashMap::new();
            }
            HashMap::from([
                ("encoding".into(), zvariant::Str::from("pcm").into()),
                ("resolution".into(), zvariant::Str::from("s16le").into()),
                ("rate".into(), rate.into()),
            ])
        }
        #[zbus(property)]
        fn audio_port(&self) -> &str {
            if self.0.empty_port.load(Ordering::SeqCst) {
                ""
            } else {
                "/dev/null"
            }
        }
        async fn start(&self) -> zbus::fdo::Result<()> {
            self.0.record("start");
            self.0.starts.fetch_add(1, Ordering::SeqCst);
            self.0.state.store(1, Ordering::SeqCst);
            wait_native_boundary(&self.0.start_gate).await?;
            if self.0.fail_start.load(Ordering::SeqCst) {
                return Err(zbus::fdo::Error::Failed(
                    "synthetic uncertain Start failure".into(),
                ));
            }
            Ok(())
        }
        async fn accept(&self) -> zbus::fdo::Result<()> {
            self.0.accepts.fetch_add(1, Ordering::SeqCst);
            self.0.state.store(4, Ordering::SeqCst);
            wait_native_boundary(&self.0.accept_gate).await
        }
        fn hangup(&self) -> zbus::fdo::Result<()> {
            self.0.hangups.fetch_add(1, Ordering::SeqCst);
            if self.0.fail_hangup.load(Ordering::SeqCst) {
                return Err(zbus::fdo::Error::Failed(
                    "synthetic uncertain Hangup failure".into(),
                ));
            }
            self.0.state.store(7, Ordering::SeqCst);
            Ok(())
        }
    }
    struct FakePcmEngine(Arc<OutgoingEffects>);
    struct FakePreparedPcm(Option<Arc<OutgoingEffects>>);
    struct FakeActivePcm(Arc<OutgoingEffects>);
    impl crate::gsm_pcm::PcmEngine for FakePcmEngine {
        fn available(&self) -> bool {
            true
        }
        fn prepare(&self, format: &VerifiedPcm) -> Result<Box<dyn PreparedPcm>> {
            assert_eq!(format.sample_rate_hz(), 16000);
            self.0.record("prepare");
            let held = self.0.prepare_gate.lock().unwrap().take();
            if let Some((entered, release)) = held {
                entered.send(()).unwrap();
                release.recv_timeout(Duration::from_secs(3))?;
            }
            anyhow::ensure!(
                !self.0.fail_prepare.load(Ordering::SeqCst),
                "synthetic preparation failure"
            );
            Ok(Box::new(FakePreparedPcm(Some(self.0.clone()))))
        }
    }
    impl PreparedPcm for FakePreparedPcm {
        fn port(&self) -> &std::path::Path {
            std::path::Path::new("/dev/null")
        }
        fn start(mut self: Box<Self>) -> Result<Box<dyn ActivePcm>> {
            let effects = self.0.take().unwrap();
            effects.record("pcm_start");
            Ok(Box::new(FakeActivePcm(effects)))
        }
    }
    impl Drop for FakePreparedPcm {
        fn drop(&mut self) {
            if let Some(effects) = &self.0 {
                effects.record("pcm_join");
            }
        }
    }
    impl ActivePcm for FakeActivePcm {
        fn set_mute(&self, _: bool) {}
        fn healthy(&mut self) -> Result<bool> {
            Ok(true)
        }
    }
    impl Drop for FakeActivePcm {
        fn drop(&mut self) {
            self.0.record("pcm_join");
        }
    }
    struct OutgoingFixture {
        // Keep the daemon and unique owner alive until after the backend.
        backend: ModemManagerVoice,
        owner: Connection,
        effects: Arc<OutgoingEffects>,
        _bus: PrivateBus,
    }
    impl OutgoingFixture {
        fn new_qualified() -> Self {
            let bus = PrivateBus::start();
            let owner = bus.connection();
            let effects = Arc::new(OutgoingEffects::default());
            effects.rate.store(16000, Ordering::SeqCst);
            effects.direction.store(2, Ordering::SeqCst);
            owner
                .object_server()
                .at("/org/freedesktop/ModemManager1", zbus::fdo::ObjectManager)
                .unwrap();
            owner
                .object_server()
                .at(
                    "/org/freedesktop/ModemManager1",
                    ReconnectManager { version: "1.24.0" },
                )
                .unwrap();
            owner
                .object_server()
                .at(TEST_MODEM0, ReconnectModem)
                .unwrap();
            owner
                .object_server()
                .at(TEST_MODEM0, OutgoingVoice(effects.clone()))
                .unwrap();
            owner
                .object_server()
                .at(TEST_OUTGOING_CALL, OutgoingCall(effects.clone()))
                .unwrap();
            allow_replacement(&owner);
            let mut backend = ModemManagerVoice::default();
            backend.configure(9, None).unwrap();
            // Clearly synthetic endpoint: the fake engine never opens it. The
            // real inventory/canonicalization/equality checks still execute.
            backend.provider =
                crate::gsm_provider::ProviderGate::test_fixture_with_audio_port("null");
            backend.pcm = PcmAdapter::with_engine(FakePcmEngine(effects.clone()));
            backend.connection = Some(bus.connection());
            assert!(backend.refresh().unwrap().available);
            Self {
                backend,
                owner,
                effects,
                _bus: bus,
            }
        }
        fn key(&self) -> SessionKey {
            SessionKey {
                transport: yoyopod_protocol::call::CallTransport::Gsm,
                generation: 9,
                call_id: "runtime-outgoing-1".into(),
            }
        }
        fn dial(&mut self, key: &SessionKey, number: &str) -> Result<()> {
            self.backend.dial_session(key, number)
        }
        fn trace(&self) -> Vec<String> {
            self.effects.trace.lock().unwrap().clone()
        }
        fn native_dial_count(&self) -> usize {
            self.effects.starts.load(Ordering::SeqCst)
        }
        fn started_key(&self) -> Option<SessionKey> {
            self.backend
                .outgoing_stage
                .as_ref()
                .and_then(|(key, stage)| {
                    matches!(stage, OutgoingStage::StartDispatched { .. }).then(|| key.clone())
                })
        }
        fn incoming_key(&mut self) -> SessionKey {
            self.effects.direction.store(1, Ordering::SeqCst);
            self.effects.state.store(3, Ordering::SeqCst);
            self.effects
                .paths
                .lock()
                .unwrap()
                .push(OwnedObjectPath::try_from(TEST_OUTGOING_CALL).unwrap());
            self.backend.reconcile_paths().unwrap();
            self.backend.registry().unwrap().tracked()[0].1.clone()
        }
        fn hold_boundary(&self, boundary: ControlBoundary) -> (Receiver<()>, Sender<()>) {
            let gate = match boundary {
                ControlBoundary::Create => &self.effects.create_gate,
                ControlBoundary::Prepare => &self.effects.prepare_gate,
                ControlBoundary::Start => &self.effects.start_gate,
                ControlBoundary::Accept => &self.effects.accept_gate,
            };
            let (entered, held) = mpsc::channel();
            let (release, released) = mpsc::channel();
            *gate.lock().unwrap() = Some((entered, released));
            (held, release)
        }
    }

    fn outgoing_same_path_reset(owner: &Connection, effects: &OutgoingEffects) {
        owner
            .emit_signal(
                None::<&str>,
                TEST_MODEM0,
                MODEM_INTERFACE,
                "StateChanged",
                &(8i32, 4i32, 0u32),
            )
            .unwrap();
        effects.rate.store(0, Ordering::SeqCst);
        lifecycle_properties(
            owner,
            TEST_OUTGOING_CALL,
            CALL_INTERFACE,
            HashMap::new(),
            vec!["AudioFormat"],
        );
        owner
            .emit_signal(
                None::<&str>,
                TEST_MODEM0,
                MODEM_INTERFACE,
                "StateChanged",
                &(4i32, 8i32, 0u32),
            )
            .unwrap();
        effects.rate.store(16000, Ordering::SeqCst);
        // The actual metadata getter remains restored on the exported Call;
        // this signal carries the same qualified typed dictionary explicitly.
        lifecycle_properties(
            owner,
            TEST_OUTGOING_CALL,
            CALL_INTERFACE,
            HashMap::from([(
                "AudioFormat",
                zvariant::OwnedValue::try_from(zvariant::Value::from(HashMap::from([
                    ("encoding", zvariant::Value::from("pcm")),
                    ("resolution", zvariant::Value::from("s16le")),
                    ("rate", zvariant::Value::from(16000u32)),
                ])))
                .unwrap(),
            )]),
            vec![],
        );
    }

    #[test]
    fn gsm_outgoing_orders_created_unknown_format_prepare_start_and_active_pcm() {
        let mut fixture = OutgoingFixture::new_qualified();
        let key = fixture.key();
        assert_eq!(
            fixture.backend.bound_owner().unwrap(),
            fixture.owner.unique_name().unwrap().as_str()
        );
        let collector = fixture
            .backend
            .signals
            .as_ref()
            .unwrap()
            .connection
            .unique_name()
            .unwrap()
            .to_string();
        fixture.dial(&key, "+49123456789").unwrap();
        assert_eq!(fixture.trace(), ["create", "format", "prepare", "start"]);
        assert_eq!(fixture.native_dial_count(), 1);
        assert_eq!(fixture.started_key(), Some(key.clone()));
        assert!(fixture.backend.prepared_audio.is_some());
        assert!(fixture.backend.audio.is_none());
        assert!(fixture.backend.owns_voice(&key));
        assert!(fixture
            .backend
            .drain_call_events()
            .iter()
            .all(|event| !matches!(event, CallManagerWireEvent::Offer(_))));
        fixture.effects.state.store(4, Ordering::SeqCst);
        fixture.backend.observe_path(TEST_OUTGOING_CALL).unwrap();
        assert_eq!(
            fixture.trace().last().map(String::as_str),
            Some("pcm_start")
        );
        assert!(fixture.backend.audio.is_some());
        assert_eq!(
            fixture
                .backend
                .signals
                .as_ref()
                .unwrap()
                .connection
                .unique_name()
                .unwrap()
                .as_str(),
            collector
        );
        fixture.backend.targeted_hangup(&key).unwrap();
        assert_eq!(fixture.trace().last().map(String::as_str), Some("pcm_join"));
        fixture.backend.observe_path(TEST_OUTGOING_CALL).unwrap();
        assert!(!fixture.backend.owns_voice(&key));
        assert_eq!(
            *fixture.effects.deletes.lock().unwrap(),
            [TEST_OUTGOING_CALL]
        );
    }

    #[test]
    fn gsm_outgoing_invalid_format_deletes_only_exact_unstarted_unknown_and_retains_failed_delete()
    {
        for failed_delete in [false, true] {
            let mut fixture = OutgoingFixture::new_qualified();
            let key = fixture.key();
            fixture.effects.rate.store(0, Ordering::SeqCst);
            fixture
                .effects
                .fail_delete
                .store(failed_delete, Ordering::SeqCst);
            assert!(fixture.dial(&key, "+49123456789").is_err());
            assert_eq!(fixture.trace(), ["create", "format", "delete"]);
            assert_eq!(
                *fixture.effects.deletes.lock().unwrap(),
                [TEST_OUTGOING_CALL]
            );
            assert_eq!(fixture.native_dial_count(), 0);
            assert_eq!(fixture.effects.hangups.load(Ordering::SeqCst), 0);
            assert_eq!(fixture.backend.owns_voice(&key), failed_delete);
            let events = fixture.backend.drain_call_events();
            assert!(events
                .iter()
                .all(|e| !matches!(e, CallManagerWireEvent::Offer(_))));
            assert_eq!(events.iter().any(|e| matches!(e,CallManagerWireEvent::Update(u) if u.key==key && u.phase==CallPhase::Ended)), !failed_delete);
            if failed_delete {
                assert!(
                    !fixture
                        .backend
                        .reconciliation()
                        .unwrap()
                        .native_calls_quiescent
                );
                fixture.effects.paths.lock().unwrap().clear();
                fixture.backend.reconcile_paths().unwrap();
                assert!(!fixture.backend.owns_voice(&key));
            }
        }
    }

    #[test]
    fn gsm_outgoing_cleanup_rechecks_identity_after_held_state_reply_and_path_reuse() {
        for case in 0..3 {
            let mut fixture = OutgoingFixture::new_qualified();
            let unstarted = case == 1;
            let key = if case == 2 {
                fixture.incoming_key()
            } else {
                fixture.key()
            };
            if unstarted {
                fixture.effects.rate.store(0, Ordering::SeqCst);
                fixture.effects.fail_delete.store(true, Ordering::SeqCst);
                assert!(fixture.dial(&key, "+49123456789").is_err());
            } else if case == 2 {
                fixture
                    .backend
                    .apply_call(&CallCommand {
                        key: key.clone(),
                        action: yoyopod_protocol::call::CallAction::Answer,
                    })
                    .unwrap();
            } else {
                fixture.dial(&key, "+49123456789").unwrap();
            }
            let before_deletes = fixture.effects.deletes.lock().unwrap().len();
            let collector = fixture
                .backend
                .signals
                .as_ref()
                .unwrap()
                .connection
                .unique_name()
                .unwrap()
                .to_string();
            let (entered, held) = mpsc::channel();
            let (release, released) = mpsc::channel();
            *fixture.effects.state_gate.lock().unwrap() = Some((entered, released));
            let OutgoingFixture {
                mut backend,
                owner,
                effects,
                _bus,
            } = fixture;
            let old_key = key.clone();
            let request = thread::spawn(move || {
                let result = if unstarted {
                    backend.delete_created_unstarted(&old_key)
                } else {
                    backend.targeted_hangup(&old_key)
                };
                (backend, result)
            });
            held.recv_timeout(Duration::from_secs(3)).unwrap();
            // Real same-owner removal/readdition evidence arrives while the
            // old object's explicit State response is still held.
            owner
                .emit_signal(
                    None::<&str>,
                    TEST_MODEM0,
                    VOICE_INTERFACE,
                    "CallDeleted",
                    &(OwnedObjectPath::try_from(TEST_OUTGOING_CALL).unwrap(),),
                )
                .unwrap();
            owner
                .emit_signal(
                    None::<&str>,
                    "/org/freedesktop/ModemManager1",
                    "org.freedesktop.DBus.ObjectManager",
                    "InterfacesRemoved",
                    &(
                        OwnedObjectPath::try_from(TEST_OUTGOING_CALL).unwrap(),
                        vec![CALL_INTERFACE],
                    ),
                )
                .unwrap();
            effects.state.store(0, Ordering::SeqCst);
            owner
                .emit_signal(
                    None::<&str>,
                    TEST_MODEM0,
                    VOICE_INTERFACE,
                    "CallAdded",
                    &(OwnedObjectPath::try_from(TEST_OUTGOING_CALL).unwrap(),),
                )
                .unwrap();
            release.send(()).unwrap();
            let (mut backend, result) = request.join().unwrap();
            assert!(result.is_err());
            assert!(backend.lost_call_paths.contains(TEST_OUTGOING_CALL));
            assert_eq!(effects.hangups.load(Ordering::SeqCst), 0);
            assert_eq!(effects.deletes.lock().unwrap().len(), before_deletes);
            assert!(backend.owns_voice(&key));
            assert!(!backend.reconciliation().unwrap().native_calls_quiescent);
            assert!(backend.drain_call_events().iter().all(|e| !matches!(e, CallManagerWireEvent::Update(u) if u.key==key && u.phase==CallPhase::Ended)));
            assert_eq!(
                backend
                    .signals
                    .as_ref()
                    .unwrap()
                    .connection
                    .unique_name()
                    .unwrap()
                    .as_str(),
                collector
            );
            if case == 2 {
                effects.paths.lock().unwrap().clear();
                backend.reconcile_paths().unwrap();
                assert!(
                    backend.owns_voice(&key),
                    "uncertain Accept released on CallDeleted/absence"
                );
                assert_eq!(backend.accept_dispatched.as_ref(), Some(&key));
                assert!(backend.drain_call_events().iter().all(|e| !matches!(e,CallManagerWireEvent::Update(u) if u.key==key && u.phase==CallPhase::Ended)));
            }
        }
    }

    #[test]
    fn gsm_outgoing_create_error_never_borrows_late_unrelated_unknown_as_exact_creation() {
        let mut fixture = OutgoingFixture::new_qualified();
        let key = fixture.key();
        fixture.effects.fail_create.store(true, Ordering::SeqCst);
        assert!(fixture.dial(&key, "+49123456789").is_err());
        assert_eq!(fixture.backend.uncertain_create.as_ref(), Some(&key));
        assert_eq!(
            fixture.backend.outgoing_stage.as_ref(),
            Some(&(key.clone(), OutgoingStage::Creating))
        );
        // A new native UNKNOWN after the error is observable, but its path was
        // never returned by this Create reply and cannot authorize old-key Delete.
        fixture.effects.created.store(true, Ordering::SeqCst);
        fixture
            .effects
            .paths
            .lock()
            .unwrap()
            .push(OwnedObjectPath::try_from(TEST_OUTGOING_CALL).unwrap());
        fixture.backend.reconcile_paths().unwrap();
        assert_eq!(fixture.backend.registry().unwrap().path_for(&key), None);
        assert!(fixture.backend.delete_created_unstarted(&key).is_err());
        assert!(fixture.backend.targeted_hangup(&key).is_err());
        assert_eq!(fixture.backend.uncertain_create.as_ref(), Some(&key));
        assert!(fixture.backend.owns_voice(&key));
        assert!(fixture.effects.deletes.lock().unwrap().is_empty());
        assert_eq!(fixture.native_dial_count(), 0);
        assert_eq!(fixture.effects.hangups.load(Ordering::SeqCst), 0);
        fixture.effects.paths.lock().unwrap().clear();
        fixture.backend.reconcile_paths().unwrap();
        assert!(fixture.backend.owns_voice(&key));
        assert!(
            !fixture
                .backend
                .reconciliation()
                .unwrap()
                .native_calls_quiescent
        );
        assert!(fixture.backend.drain_call_events().iter().all(|e| !matches!(e,CallManagerWireEvent::Update(u) if u.key==key && u.phase==CallPhase::Ended)));
    }

    #[test]
    fn gsm_outgoing_held_native_boundaries_fence_old_intent_and_retain_actual_worker_data_lease() {
        use crate::protocol::WorkerEnvelope;
        use yoyopod_protocol::call::CallAction;
        for boundary in [
            ControlBoundary::Create,
            ControlBoundary::Prepare,
            ControlBoundary::Start,
            ControlBoundary::Accept,
        ] {
            let mut fixture = OutgoingFixture::new_qualified();
            let key = if boundary == ControlBoundary::Accept {
                fixture.incoming_key()
            } else {
                fixture.key()
            };
            let sessions = fixture
                .backend
                .registry()
                .unwrap()
                .latest(&key)
                .cloned()
                .into_iter()
                .collect();
            let epoch = fixture.backend.selected_modem_epoch();
            let native_owner = fixture.backend.reconciliation().unwrap().native_owner;
            fixture.effects.fail_delete.store(true, Ordering::SeqCst);
            fixture.effects.fail_hangup.store(true, Ordering::SeqCst);
            let (held, release) = fixture.hold_boundary(boundary);
            let OutgoingFixture {
                backend,
                owner,
                effects,
                _bus,
            } = fixture;
            let gsm = GsmWorker::with_modem_backend(backend);
            let envelope = if boundary == ControlBoundary::Accept {
                WorkerEnvelope::command(
                    "call.action",
                    Some("boundary".into()),
                    serde_json::json!({"key":key,"action":"answer","admission_epoch":epoch}),
                )
            } else {
                WorkerEnvelope::command(
                    "call.dial",
                    Some("boundary".into()),
                    serde_json::json!({"key":key,"address":"+49123456789","admission_epoch":epoch}),
                )
            };
            let events = crate::worker::tests::assert_gsm_outgoing_uncertain_lease(
                &gsm,
                &key,
                sessions,
                envelope,
                &["boundary", "queued-old-dial", "queued-old-answer"],
                crate::worker::tests::GsmLeaseOutcome::Uncertain,
                |gsm, _| {
                    held.recv_timeout(Duration::from_secs(3)).unwrap();
                    gsm.send_at_epoch(
                        GsmCommand::DialSession {
                            request_id: "queued-old-dial".into(),
                            key: key.clone(),
                            number: "+49123456789".into(),
                        },
                        epoch,
                    )
                    .unwrap();
                    gsm.send_at_epoch(
                        GsmCommand::Action {
                            request_id: "queued-old-answer".into(),
                            command: CallCommand {
                                key: key.clone(),
                                action: CallAction::Answer,
                            },
                        },
                        epoch,
                    )
                    .unwrap();
                    outgoing_same_path_reset(&owner, &effects);
                    if matches!(boundary, ControlBoundary::Start | ControlBoundary::Accept) {
                        // A pending native operation can later report UNKNOWN;
                        // this cannot turn dispatch uncertainty into deletion.
                        effects.state.store(0, Ordering::SeqCst);
                    }
                    release.send(()).unwrap();
                },
            );
            for request in ["queued-old-dial", "queued-old-answer"] {
                let completed = events
                    .iter()
                    .find(|e| e.request_id.as_deref() == Some(request))
                    .unwrap();
                assert!(
                    completed.payload["error"]
                        .as_str()
                        .unwrap()
                        .contains("command fenced"),
                    "{boundary:?}: {completed:?}"
                );
            }
            assert!(events.iter().all(|e| e.message_type != "call.update"
                || e.payload["key"] != serde_json::json!(key)
                || e.payload["phase"] != "active"));
            assert!(events
                .iter()
                .filter(|e| e.message_type == "call.reconciled")
                .all(|e| e.payload["native_owner"] == serde_json::json!(native_owner)));
            assert_eq!(
                effects.starts.load(Ordering::SeqCst),
                usize::from(boundary == ControlBoundary::Start)
            );
            assert_eq!(
                effects.accepts.load(Ordering::SeqCst),
                usize::from(boundary == ControlBoundary::Accept)
            );
            let trace = effects.trace.lock().unwrap().clone();
            assert!(!trace.iter().any(|entry| entry == "pcm_start"));
            if boundary != ControlBoundary::Create {
                assert!(
                    trace.iter().any(|entry| entry == "pcm_join"),
                    "{boundary:?}: {trace:?}"
                );
            }
            if matches!(boundary, ControlBoundary::Start | ControlBoundary::Accept) {
                assert!(
                    effects.deletes.lock().unwrap().is_empty(),
                    "uncertain dispatch used DeleteCall as native termination"
                );
            }
        }
    }

    #[test]
    fn gsm_outgoing_pending_provider_and_preparation_failure_never_dispatch_native_start_or_accept()
    {
        use yoyopod_protocol::call::CallAction;
        for incoming in [false, true] {
            let mut fixture = OutgoingFixture::new_qualified();
            let key = if incoming {
                fixture.incoming_key()
            } else {
                fixture.key()
            };
            fixture.backend.provider = crate::gsm_provider::ProviderGate::default();
            let result = if incoming {
                fixture.backend.apply_call(&CallCommand {
                    key,
                    action: CallAction::Answer,
                })
            } else {
                fixture.dial(&key, "+49123456789")
            };
            assert!(result.is_err());
            assert_eq!(fixture.native_dial_count(), 0);
            assert_eq!(fixture.effects.accepts.load(Ordering::SeqCst), 0);
            assert!(!fixture
                .trace()
                .iter()
                .any(|e| matches!(e.as_str(), "create" | "prepare" | "pcm_start")));
        }
        let mut fixture = OutgoingFixture::new_qualified();
        let key = fixture.key();
        fixture.effects.fail_prepare.store(true, Ordering::SeqCst);
        assert!(fixture.dial(&key, "+49123456789").is_err());
        assert_eq!(fixture.trace(), ["create", "format", "prepare", "delete"]);
        assert_eq!(fixture.native_dial_count(), 0);
        assert_eq!(fixture.effects.hangups.load(Ordering::SeqCst), 0);
        assert!(!fixture.backend.owns_voice(&key));
    }

    #[test]
    fn gsm_outgoing_active_port_wait_is_bounded_and_prepared_pcm_joins_before_ended() {
        let mut fixture = OutgoingFixture::new_qualified();
        let key = fixture.key();
        fixture.dial(&key, "+49123456789").unwrap();
        fixture.effects.state.store(4, Ordering::SeqCst);
        fixture.effects.empty_port.store(true, Ordering::SeqCst);
        fixture.backend.drain_call_events();
        fixture.backend.observe_path(TEST_OUTGOING_CALL).unwrap();
        assert!(fixture.backend.audio.is_none());
        assert!(fixture.backend.prepared_audio.is_some());
        assert!(fixture
            .backend
            .drain_call_events()
            .iter()
            .all(|e| !matches!(e,CallManagerWireEvent::Update(u) if u.phase==CallPhase::Active)));
        fixture.backend.audio_deadline = Some(Instant::now());
        fixture.backend.observe_path(TEST_OUTGOING_CALL).unwrap();
        assert!(fixture.backend.audio.is_none() && fixture.backend.prepared_audio.is_none());
        assert!(fixture.backend.owns_voice(&key));
        assert_eq!(fixture.effects.hangups.load(Ordering::SeqCst), 1);
        assert_eq!(fixture.trace().last().map(String::as_str), Some("pcm_join"));
        fixture.backend.observe_path(TEST_OUTGOING_CALL).unwrap();
        assert!(fixture.backend.drain_call_events().iter().any(|e| matches!(e,CallManagerWireEvent::Update(u) if u.key==key && u.phase==CallPhase::Ended)));
        assert!(!fixture.backend.owns_voice(&key));
    }

    #[test]
    fn gsm_outgoing_first_ready_port_observation_publishes_active_without_a_duration_tick() {
        let mut fixture = OutgoingFixture::new_qualified();
        let key = fixture.key();
        fixture.dial(&key, "+49123456789").unwrap();
        fixture.effects.state.store(4, Ordering::SeqCst);
        fixture.effects.empty_port.store(true, Ordering::SeqCst);
        fixture.backend.drain_call_events();
        fixture.backend.observe_path(TEST_OUTGOING_CALL).unwrap();
        assert!(fixture.backend.audio.is_none());
        assert_eq!(
            fixture
                .backend
                .registry()
                .unwrap()
                .latest(&key)
                .unwrap()
                .phase,
            CallPhase::Preparing
        );
        assert!(fixture
            .backend
            .drain_call_events()
            .iter()
            .all(|e| !matches!(e,CallManagerWireEvent::Update(u) if u.phase==CallPhase::Active)));
        fixture.effects.empty_port.store(false, Ordering::SeqCst);
        fixture.backend.observe_path(TEST_OUTGOING_CALL).unwrap();
        assert!(fixture.backend.audio.is_some());
        let events = fixture.backend.drain_call_events();
        assert_eq!(events.iter().filter(|e| matches!(e,CallManagerWireEvent::Update(u) if u.key==key && u.phase==CallPhase::Active && u.duration_seconds==0)).count(), 1);
        assert_eq!(
            fixture
                .trace()
                .iter()
                .filter(|e| e.as_str() == "pcm_start")
                .count(),
            1
        );
    }

    #[test]
    fn gsm_outgoing_validated_cancel_during_prepare_fences_dispatch_and_joins_before_keyed_data_release(
    ) {
        use crate::protocol::WorkerEnvelope;
        use crate::worker::tests::GsmLeaseOutcome;
        for incoming in [false, true] {
            let mut fixture = OutgoingFixture::new_qualified();
            let key = if incoming {
                fixture.incoming_key()
            } else {
                fixture.key()
            };
            let sessions = fixture
                .backend
                .registry()
                .unwrap()
                .latest(&key)
                .cloned()
                .into_iter()
                .collect();
            if incoming {
                fixture.effects.fail_hangup.store(true, Ordering::SeqCst);
            }
            let epoch = fixture.backend.selected_modem_epoch();
            let (held, release) = fixture.hold_boundary(ControlBoundary::Prepare);
            let OutgoingFixture {
                backend,
                owner: _owner,
                effects,
                _bus,
            } = fixture;
            let gsm = GsmWorker::with_modem_backend(backend);
            let envelope = if incoming {
                WorkerEnvelope::command(
                    "call.action",
                    Some("cancelled-admission".into()),
                    serde_json::json!({"key":key,"action":"answer","admission_epoch":epoch}),
                )
            } else {
                WorkerEnvelope::command(
                    "call.dial",
                    Some("cancelled-admission".into()),
                    serde_json::json!({"key":key,"address":"+49123456789","admission_epoch":epoch}),
                )
            };
            crate::worker::tests::assert_gsm_outgoing_uncertain_lease(
                &gsm,
                &key,
                sessions,
                envelope,
                &["cancelled-admission", "runtime-cancel"],
                if incoming {
                    GsmLeaseOutcome::Uncertain
                } else {
                    GsmLeaseOutcome::ReleasedCancellation
                },
                |_, send| {
                    held.recv_timeout(Duration::from_secs(3)).unwrap();
                    send(&WorkerEnvelope::command(
                        "call.action",
                        Some("runtime-cancel".into()),
                        serde_json::json!({"key":key,"action":{"reject":"cancelled"}}),
                    ))
                    .unwrap();
                    release.send(()).unwrap();
                },
            );
            assert_eq!(effects.starts.load(Ordering::SeqCst), 0);
            assert_eq!(effects.accepts.load(Ordering::SeqCst), 0);
            let trace = effects.trace.lock().unwrap().clone();
            assert!(trace.iter().any(|e| e == "pcm_join"));
            if !incoming {
                assert_eq!(*effects.deletes.lock().unwrap(), [TEST_OUTGOING_CALL]);
                assert!(
                    trace.iter().position(|e| e == "pcm_join").unwrap()
                        < trace.iter().position(|e| e == "delete").unwrap()
                );
                assert_eq!(effects.hangups.load(Ordering::SeqCst), 0);
                let fresh = SessionKey {
                    call_id: "runtime-outgoing-2".into(),
                    ..key.clone()
                };
                let epoch = gsm.admission_epoch();
                crate::worker::tests::assert_gsm_outgoing_uncertain_lease(
                    &gsm,
                    &fresh,
                    vec![],
                    WorkerEnvelope::command(
                        "call.dial",
                        Some("fresh-after-clean-cancel".into()),
                        serde_json::json!({"key":fresh,"address":"+49123456789","admission_epoch":epoch}),
                    ),
                    &["fresh-after-clean-cancel", "late-old-cancel"],
                    GsmLeaseOutcome::OwnedSuccess,
                    |_, send| {
                        send(&WorkerEnvelope::command(
                            "call.action",
                            Some("late-old-cancel".into()),
                            serde_json::json!({"key":key,"action":"hangup"}),
                        ))
                        .unwrap();
                    },
                );
                assert_eq!(effects.starts.load(Ordering::SeqCst), 1);
                assert_eq!(*effects.deletes.lock().unwrap(), [TEST_OUTGOING_CALL]);
                assert!(gsm
                    .send_at_epoch(
                        GsmCommand::DialSession {
                            request_id: "retired-replay".into(),
                            key: key.clone(),
                            number: "+49123456789".into()
                        },
                        epoch
                    )
                    .is_err());
            }
        }
    }

    #[test]
    fn gsm_outgoing_cancel_before_backend_create_is_sticky_and_wrong_key_cancel_preserves_primary()
    {
        use crate::protocol::WorkerEnvelope;
        use crate::worker::tests::GsmLeaseOutcome;
        for wrong_key in [false, true] {
            let fixture = OutgoingFixture::new_qualified();
            let key = fixture.key();
            let epoch = fixture.backend.selected_modem_epoch();
            let (held, release) = if wrong_key {
                fixture.hold_boundary(ControlBoundary::Prepare)
            } else {
                let (entered, held) = mpsc::channel();
                let (release, released) = mpsc::channel();
                *fixture
                    .backend
                    .signals
                    .as_ref()
                    .unwrap()
                    .pause_before_forward
                    .lock()
                    .unwrap() = Some((entered, released));
                fixture
                    .owner
                    .emit_signal(
                        None::<&str>,
                        TEST_MODEM0,
                        MODEM_INTERFACE,
                        "StateChanged",
                        &(8i32, 8i32, 0u32),
                    )
                    .unwrap();
                (held, release)
            };
            let OutgoingFixture {
                backend,
                owner: _owner,
                effects,
                _bus,
            } = fixture;
            let gsm = GsmWorker::with_modem_backend(backend);
            let cancelled_key = if wrong_key {
                SessionKey {
                    call_id: "runtime-outgoing-2".into(),
                    ..key.clone()
                }
            } else {
                key.clone()
            };
            crate::worker::tests::assert_gsm_outgoing_uncertain_lease(
                &gsm,
                &key,
                vec![],
                WorkerEnvelope::command(
                    "call.dial",
                    Some("admission".into()),
                    serde_json::json!({"key":key,"address":"+49123456789","admission_epoch":epoch}),
                ),
                &["admission", "runtime-cancel"],
                if wrong_key {
                    GsmLeaseOutcome::OwnedSuccess
                } else {
                    GsmLeaseOutcome::ReleasedCancellation
                },
                |_, send| {
                    held.recv_timeout(Duration::from_secs(3)).unwrap();
                    send(&WorkerEnvelope::command(
                        "call.action",
                        Some("runtime-cancel".into()),
                        serde_json::json!({"key":cancelled_key,"action":"hangup"}),
                    ))
                    .unwrap();
                    release.send(()).unwrap();
                },
            );
            assert_eq!(
                effects.starts.load(Ordering::SeqCst),
                usize::from(wrong_key)
            );
            assert_eq!(
                effects
                    .trace
                    .lock()
                    .unwrap()
                    .iter()
                    .filter(|e| e.as_str() == "create")
                    .count(),
                usize::from(wrong_key)
            );
        }
    }

    #[test]
    fn gsm_outgoing_incoming_held_accept_path_reuse_and_absence_retain_exact_uncertain_key() {
        let mut fixture = OutgoingFixture::new_qualified();
        let key = fixture.incoming_key();
        let (held, release) = fixture.hold_boundary(ControlBoundary::Accept);
        let collector = fixture
            .backend
            .signals
            .as_ref()
            .unwrap()
            .connection
            .unique_name()
            .unwrap()
            .to_string();
        let OutgoingFixture {
            mut backend,
            owner,
            effects,
            _bus,
        } = fixture;
        let old_key = key.clone();
        let request = thread::spawn(move || {
            let result = backend.apply_call(&CallCommand {
                key: old_key,
                action: yoyopod_protocol::call::CallAction::Answer,
            });
            (backend, result)
        });
        held.recv_timeout(Duration::from_secs(3)).unwrap();
        owner
            .emit_signal(
                None::<&str>,
                TEST_MODEM0,
                VOICE_INTERFACE,
                "CallDeleted",
                &(OwnedObjectPath::try_from(TEST_OUTGOING_CALL).unwrap(),),
            )
            .unwrap();
        owner
            .emit_signal(
                None::<&str>,
                "/org/freedesktop/ModemManager1",
                "org.freedesktop.DBus.ObjectManager",
                "InterfacesRemoved",
                &(
                    OwnedObjectPath::try_from(TEST_OUTGOING_CALL).unwrap(),
                    vec![CALL_INTERFACE],
                ),
            )
            .unwrap();
        effects.state.store(3, Ordering::SeqCst);
        owner
            .emit_signal(
                None::<&str>,
                TEST_MODEM0,
                VOICE_INTERFACE,
                "CallAdded",
                &(OwnedObjectPath::try_from(TEST_OUTGOING_CALL).unwrap(),),
            )
            .unwrap();
        release.send(()).unwrap();
        let (mut backend, result) = request.join().unwrap();
        assert!(result.is_err());
        assert!(backend.lost_call_paths.contains(TEST_OUTGOING_CALL));
        assert!(backend.targeted_hangup(&key).is_err());
        effects.paths.lock().unwrap().clear();
        backend.reconcile_paths().unwrap();
        assert!(backend.owns_voice(&key));
        assert_eq!(backend.accept_dispatched.as_ref(), Some(&key));
        assert_eq!(effects.hangups.load(Ordering::SeqCst), 0);
        assert!(effects.deletes.lock().unwrap().is_empty());
        assert!(backend.audio.is_none() && backend.prepared_audio.is_none());
        assert!(effects
            .trace
            .lock()
            .unwrap()
            .iter()
            .any(|e| e == "pcm_join"));
        assert!(backend.drain_call_events().iter().all(|e| !matches!(e,CallManagerWireEvent::Update(u) if u.key==key && matches!(u.phase,CallPhase::Active|CallPhase::Ended))));
        assert_eq!(
            backend
                .signals
                .as_ref()
                .unwrap()
                .connection
                .unique_name()
                .unwrap()
                .as_str(),
            collector
        );
    }

    #[test]
    fn gsm_outgoing_successful_hangup_cannot_borrow_readded_primary_or_secondary_terminal_state() {
        const SECONDARY: &str = "/org/freedesktop/ModemManager1/Call/100";
        for secondary_target in [false, true] {
            let mut fixture = OutgoingFixture::new_qualified();
            let primary = fixture.key();
            fixture.dial(&primary, "+49123456789").unwrap();
            let (path, effects, key) = if secondary_target {
                let effects = Arc::new(OutgoingEffects::default());
                effects.state.store(3, Ordering::SeqCst);
                effects.direction.store(1, Ordering::SeqCst);
                effects.rate.store(16000, Ordering::SeqCst);
                fixture
                    .owner
                    .object_server()
                    .at(SECONDARY, OutgoingCall(effects.clone()))
                    .unwrap();
                fixture
                    .effects
                    .paths
                    .lock()
                    .unwrap()
                    .push(OwnedObjectPath::try_from(SECONDARY).unwrap());
                fixture.backend.reconcile_paths().unwrap();
                let key = fixture
                    .backend
                    .registry()
                    .unwrap()
                    .tracked()
                    .into_iter()
                    .find(|(path, _)| path == SECONDARY)
                    .unwrap()
                    .1;
                (SECONDARY, effects, key)
            } else {
                (TEST_OUTGOING_CALL, fixture.effects.clone(), primary.clone())
            };
            let epoch = fixture.backend.selected_modem_epoch();
            fixture.backend.targeted_hangup(&key).unwrap();
            assert_eq!(effects.hangups.load(Ordering::SeqCst), 1);
            fixture.backend.drain_call_events();
            fixture
                .owner
                .emit_signal(
                    None::<&str>,
                    TEST_MODEM0,
                    VOICE_INTERFACE,
                    "CallDeleted",
                    &(OwnedObjectPath::try_from(path).unwrap(),),
                )
                .unwrap();
            fixture
                .owner
                .emit_signal(
                    None::<&str>,
                    "/org/freedesktop/ModemManager1",
                    "org.freedesktop.DBus.ObjectManager",
                    "InterfacesRemoved",
                    &(
                        OwnedObjectPath::try_from(path).unwrap(),
                        vec![CALL_INTERFACE],
                    ),
                )
                .unwrap();
            // The replacement is already terminal. Neither this state nor its
            // reused address is proof about the acknowledged old native ID.
            effects.state.store(7, Ordering::SeqCst);
            fixture
                .owner
                .emit_signal(
                    None::<&str>,
                    TEST_MODEM0,
                    VOICE_INTERFACE,
                    "CallAdded",
                    &(OwnedObjectPath::try_from(path).unwrap(),),
                )
                .unwrap();
            assert!(fixture.backend.targeted_hangup(&key).is_err());
            fixture.backend.reconcile_paths().unwrap();
            assert_eq!(effects.hangups.load(Ordering::SeqCst), 1);
            assert!(fixture.effects.deletes.lock().unwrap().is_empty());
            assert_eq!(
                fixture.backend.registry().unwrap().path_for(&key),
                Some(path)
            );
            assert!(fixture.backend.drain_call_events().iter().all(|event| !matches!(event,CallManagerWireEvent::Update(u) if u.key==key && u.phase==CallPhase::Ended)));
            assert!(fixture.backend.lost_call_paths.contains(path));
            if secondary_target {
                assert_eq!(fixture.backend.selected_modem_epoch(), epoch);
                assert!(fixture.backend.owns_voice(&primary));
                assert!(fixture.backend.prepared_audio.is_some());
            } else {
                assert!(fixture.backend.owns_voice(&key));
            }
            fixture
                .effects
                .paths
                .lock()
                .unwrap()
                .retain(|candidate| candidate.as_str() != path);
            fixture.backend.reconcile_paths().unwrap();
            assert_eq!(fixture.backend.registry().unwrap().path_for(&key), None);
            assert!(!fixture
                .backend
                .confirmed_hangups
                .iter()
                .any(|(candidate, _)| candidate == &key));
            assert!(!fixture.backend.lost_call_paths.contains(path));
            assert!(fixture.backend.drain_call_events().iter().any(|event| matches!(event,CallManagerWireEvent::Update(u) if u.key==key && u.phase==CallPhase::Ended)));
        }
    }

    #[test]
    fn gsm_outgoing_successful_hangup_removed_then_fresh_absence_releases_joined_key() {
        let mut fixture = OutgoingFixture::new_qualified();
        let key = fixture.key();
        fixture.dial(&key, "+49123456789").unwrap();
        fixture.backend.targeted_hangup(&key).unwrap();
        assert_eq!(fixture.trace().last().map(String::as_str), Some("pcm_join"));
        fixture.backend.drain_call_events();
        fixture
            .owner
            .emit_signal(
                None::<&str>,
                TEST_MODEM0,
                VOICE_INTERFACE,
                "CallDeleted",
                &(OwnedObjectPath::try_from(TEST_OUTGOING_CALL).unwrap(),),
            )
            .unwrap();
        fixture.effects.paths.lock().unwrap().clear();
        fixture.backend.reconcile_paths().unwrap();
        assert!(!fixture.backend.owns_voice(&key));
        assert!(fixture.backend.confirmed_hangups.is_empty());
        assert!(fixture
            .backend
            .cancellations
            .0
            .lock()
            .unwrap()
            .entries
            .is_empty());
        assert!(fixture.backend.registry().unwrap().tracked().is_empty());
        assert!(
            fixture
                .backend
                .reconciliation()
                .unwrap()
                .native_calls_quiescent
        );
        assert!(fixture.backend.drain_call_events().iter().any(|event| matches!(event,CallManagerWireEvent::Update(u) if u.key==key && u.phase==CallPhase::Ended)));
    }

    #[test]
    fn gsm_outgoing_secondary_path_reuse_blocks_only_its_cleanup_identity() {
        const SECONDARY: &str = "/org/freedesktop/ModemManager1/Call/100";
        let mut fixture = OutgoingFixture::new_qualified();
        let primary = fixture.key();
        fixture.dial(&primary, "+49123456789").unwrap();
        let secondary = Arc::new(OutgoingEffects::default());
        secondary.state.store(3, Ordering::SeqCst);
        secondary.direction.store(1, Ordering::SeqCst);
        secondary.rate.store(16000, Ordering::SeqCst);
        fixture
            .owner
            .object_server()
            .at(SECONDARY, OutgoingCall(secondary.clone()))
            .unwrap();
        fixture
            .effects
            .paths
            .lock()
            .unwrap()
            .push(OwnedObjectPath::try_from(SECONDARY).unwrap());
        fixture.backend.reconcile_paths().unwrap();
        let key = fixture
            .backend
            .registry()
            .unwrap()
            .tracked()
            .into_iter()
            .find(|(path, _)| path == SECONDARY)
            .unwrap()
            .1;
        let epoch = fixture.backend.selected_modem_epoch();
        let proof = fixture.backend.format_admission.clone();
        let (entered, held) = mpsc::channel();
        let (release, released) = mpsc::channel();
        *secondary.state_gate.lock().unwrap() = Some((entered, released));
        let OutgoingFixture {
            mut backend,
            owner,
            effects,
            _bus,
        } = fixture;
        let request = thread::spawn(move || {
            let result = backend.targeted_hangup(&key);
            (backend, result)
        });
        held.recv_timeout(Duration::from_secs(3)).unwrap();
        owner
            .emit_signal(
                None::<&str>,
                TEST_MODEM0,
                VOICE_INTERFACE,
                "CallDeleted",
                &(OwnedObjectPath::try_from(SECONDARY).unwrap(),),
            )
            .unwrap();
        owner
            .emit_signal(
                None::<&str>,
                TEST_MODEM0,
                VOICE_INTERFACE,
                "CallAdded",
                &(OwnedObjectPath::try_from(SECONDARY).unwrap(),),
            )
            .unwrap();
        release.send(()).unwrap();
        let (backend, result) = request.join().unwrap();
        assert!(result.is_err());
        assert_eq!(secondary.hangups.load(Ordering::SeqCst), 0);
        assert!(backend.lost_call_paths.contains(SECONDARY));
        assert_eq!(backend.selected_modem_epoch(), epoch);
        assert_eq!(backend.format_admission, proof);
        assert!(backend.owns_voice(&primary));
        assert!(backend.prepared_audio.is_some());
        assert!(!effects
            .trace
            .lock()
            .unwrap()
            .iter()
            .any(|e| e == "pcm_join"));
    }

    #[test]
    fn gsm_outgoing_dispatched_start_failure_unknown_and_absence_never_authorize_unstarted_delete()
    {
        let mut fixture = OutgoingFixture::new_qualified();
        let key = fixture.key();
        fixture.effects.fail_start.store(true, Ordering::SeqCst);
        assert!(fixture.dial(&key, "+49123456789").is_err());
        assert_eq!(fixture.started_key(), Some(key.clone()));
        fixture.effects.state.store(0, Ordering::SeqCst);
        assert!(fixture.backend.targeted_hangup(&key).is_err());
        assert!(fixture.backend.delete_created_unstarted(&key).is_err());
        fixture
            .owner
            .emit_signal(
                None::<&str>,
                TEST_MODEM0,
                VOICE_INTERFACE,
                "CallDeleted",
                &(OwnedObjectPath::try_from(TEST_OUTGOING_CALL).unwrap(),),
            )
            .unwrap();
        fixture.effects.paths.lock().unwrap().clear();
        fixture.backend.reconcile_paths().unwrap();
        assert!(fixture.effects.deletes.lock().unwrap().is_empty());
        assert_eq!(fixture.effects.hangups.load(Ordering::SeqCst), 0);
        assert!(fixture.backend.owns_voice(&key));
        assert_eq!(fixture.started_key(), Some(key.clone()));
        assert_eq!(
            fixture.backend.registry().unwrap().path_for(&key),
            Some(TEST_OUTGOING_CALL)
        );
        assert!(fixture.backend.audio.is_none() && fixture.backend.prepared_audio.is_none());
        assert!(
            !fixture
                .backend
                .reconciliation()
                .unwrap()
                .native_calls_quiescent
        );
        assert!(fixture.backend.drain_call_events().iter().all(|e| !matches!(e,CallManagerWireEvent::Update(u) if u.key==key && u.phase==CallPhase::Ended)));
    }

    #[test]
    fn gsm_outgoing_actual_worker_retains_keyed_data_for_create_start_and_delete_errors() {
        use crate::protocol::WorkerEnvelope;
        for failure in ["create", "start", "delete"] {
            let fixture = OutgoingFixture::new_qualified();
            let key = fixture.key();
            fixture.effects.fail_hangup.store(true, Ordering::SeqCst);
            match failure {
                "create" => fixture.effects.fail_create.store(true, Ordering::SeqCst),
                "start" => fixture.effects.fail_start.store(true, Ordering::SeqCst),
                "delete" => {
                    fixture.effects.rate.store(0, Ordering::SeqCst);
                    fixture.effects.fail_delete.store(true, Ordering::SeqCst);
                }
                _ => unreachable!(),
            }
            let epoch = fixture.backend.selected_modem_epoch();
            let OutgoingFixture {
                backend,
                owner: _owner,
                effects,
                _bus,
            } = fixture;
            let gsm = GsmWorker::with_modem_backend(backend);
            crate::worker::tests::assert_gsm_outgoing_uncertain_lease(
                &gsm,
                &key,
                vec![],
                WorkerEnvelope::command(
                    "call.dial",
                    Some("uncertain".into()),
                    serde_json::json!({"key":key,"address":"+49123456789","admission_epoch":epoch}),
                ),
                &["uncertain"],
                crate::worker::tests::GsmLeaseOutcome::Uncertain,
                |_, _| {},
            );
            assert_eq!(
                effects.starts.load(Ordering::SeqCst),
                usize::from(failure == "start")
            );
            if failure != "delete" {
                assert!(effects.deletes.lock().unwrap().is_empty());
            }
        }
    }

    #[test]
    fn gsm_provider_normal_account_reader_checks_actual_bus_and_injected_protected_reads() {
        let bus = PrivateBus::start();
        let (owner, backend, _) = reconnect_fixture(&bus);
        crate::gsm_provider::gsm_provider_tests::normal_account_identity_fixture(
            backend.connection.as_ref().unwrap(),
            owner.unique_name().unwrap().as_str(),
            TEST_MODEM0,
        );
    }

    struct LifecycleCall {
        rate: Arc<std::sync::atomic::AtomicU32>,
        controls: Arc<std::sync::atomic::AtomicUsize>,
        hangup_gate: PropertyGate,
    }
    #[zbus::interface(name = "org.freedesktop.ModemManager1.Call")]
    impl LifecycleCall {
        #[zbus(property)]
        fn state(&self) -> i32 {
            3
        }
        #[zbus(property)]
        fn direction(&self) -> i32 {
            1
        }
        #[zbus(property)]
        fn number(&self) -> &str {
            "+49123456789"
        }
        #[zbus(property)]
        fn audio_format(&self) -> HashMap<String, zvariant::OwnedValue> {
            let rate = self.rate.load(Ordering::SeqCst);
            if rate == 0 {
                return HashMap::new();
            }
            HashMap::from([
                (
                    "encoding".into(),
                    zvariant::OwnedValue::from(zvariant::Str::from("pcm")),
                ),
                (
                    "resolution".into(),
                    zvariant::OwnedValue::from(zvariant::Str::from("s16le")),
                ),
                ("rate".into(), zvariant::OwnedValue::from(rate)),
            ])
        }
        #[zbus(property)]
        fn audio_port(&self) -> &str {
            ""
        }
        fn accept(&self) {
            self.controls.fetch_add(1, Ordering::SeqCst);
        }
        fn start(&self) {
            self.controls.fetch_add(1, Ordering::SeqCst);
        }
        async fn hangup(&self) -> zbus::fdo::Result<()> {
            let gate = self.hangup_gate.lock().unwrap().take();
            if let Some((entered, release)) = gate {
                entered.send(()).unwrap();
                let deadline = Instant::now() + Duration::from_secs(3);
                loop {
                    match release.try_recv() {
                        Ok(()) => break,
                        Err(mpsc::TryRecvError::Empty) if Instant::now() < deadline => {
                            async_io::Timer::after(Duration::from_millis(5)).await;
                        }
                        _ => {
                            return Err(zbus::fdo::Error::Failed(
                                "fixture Hangup gate expired".into(),
                            ))
                        }
                    }
                }
            }
            Ok(())
        }
    }
    struct LifecycleFixture {
        owner: Connection,
        backend: ModemManagerVoice,
        rate: Arc<std::sync::atomic::AtomicU32>,
        controls: Arc<std::sync::atomic::AtomicUsize>,
        hangup_gate: PropertyGate,
        _bus: PrivateBus,
    }
    impl LifecycleFixture {
        fn new_qualified() -> Self {
            let bus = PrivateBus::start();
            let (owner, mut backend, _) = reconnect_fixture(&bus);
            let rate = Arc::new(std::sync::atomic::AtomicU32::new(16000));
            let controls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
            let hangup_gate = Arc::new(Mutex::new(None));
            owner
                .object_server()
                .at(
                    TEST_RINGING_CALL,
                    LifecycleCall {
                        rate: rate.clone(),
                        controls: controls.clone(),
                        hangup_gate: hangup_gate.clone(),
                    },
                )
                .unwrap();
            owner
                .object_server()
                .interface::<_, ReconnectVoice>(TEST_MODEM0)
                .unwrap()
                .get()
                .paths
                .lock()
                .unwrap()
                .push(OwnedObjectPath::try_from(TEST_RINGING_CALL).unwrap());
            backend.reconcile_paths().unwrap();
            backend.drain_call_events();
            Self {
                owner,
                backend,
                rate,
                controls,
                hangup_gate,
                _bus: bus,
            }
        }
        fn epoch(&self) -> u64 {
            self.backend.selected_modem_epoch()
        }
        fn emit_modem_state(&self, state: i32) {
            self.owner
                .emit_signal(
                    None::<&str>,
                    TEST_MODEM0,
                    MODEM_INTERFACE,
                    "StateChanged",
                    &(8i32, state, 0u32),
                )
                .unwrap();
            self.owner
                .emit_signal(
                    None::<&str>,
                    TEST_MODEM0,
                    "org.freedesktop.DBus.Properties",
                    "PropertiesChanged",
                    &(
                        MODEM_INTERFACE,
                        HashMap::from([("State", zvariant::OwnedValue::from(state))]),
                        Vec::<String>::new(),
                    ),
                )
                .unwrap();
        }
        fn emit_call_format(&self, rate: Option<u32>) {
            self.rate.store(rate.unwrap_or(0), Ordering::SeqCst);
            let format = LifecycleCall {
                rate: self.rate.clone(),
                controls: self.controls.clone(),
                hangup_gate: self.hangup_gate.clone(),
            }
            .audio_format();
            self.owner
                .emit_signal(
                    None::<&str>,
                    TEST_RINGING_CALL,
                    "org.freedesktop.DBus.Properties",
                    "PropertiesChanged",
                    &(
                        CALL_INTERFACE,
                        HashMap::from([("AudioFormat", zvariant::Value::from(format))]),
                        Vec::<String>::new(),
                    ),
                )
                .unwrap();
        }
        fn flush_through_reply(&mut self) -> Result<()> {
            self.backend.check_selected_modem()
        }
        fn refresh(&mut self) -> Result<()> {
            self.backend.refresh().map(|_| ())
        }
        fn old_epoch_can_control(&mut self, epoch: u64) -> bool {
            self.backend.ensure_control().is_ok()
                && self.backend.provider_baseline().is_ok()
                && self.backend.selected_modem_epoch() == epoch
        }
        fn add_call(&mut self, path: &str, rate: u32) -> SessionKey {
            self.owner
                .object_server()
                .at(
                    path,
                    LifecycleCall {
                        rate: Arc::new(std::sync::atomic::AtomicU32::new(rate)),
                        controls: self.controls.clone(),
                        hangup_gate: Arc::new(Mutex::new(None)),
                    },
                )
                .unwrap();
            self.owner
                .object_server()
                .interface::<_, ReconnectVoice>(TEST_MODEM0)
                .unwrap()
                .get()
                .paths
                .lock()
                .unwrap()
                .push(OwnedObjectPath::try_from(path).unwrap());
            self.backend.reconcile_paths().unwrap();
            self.backend
                .registry()
                .unwrap()
                .tracked()
                .into_iter()
                .find(|(p, _)| p == path)
                .unwrap()
                .1
        }
        fn remove_call(&mut self, path: &str) {
            self.owner
                .object_server()
                .interface::<_, ReconnectVoice>(TEST_MODEM0)
                .unwrap()
                .get()
                .paths
                .lock()
                .unwrap()
                .retain(|p| p.as_str() != path);
            self.backend.reconcile_paths().unwrap();
        }
    }
    #[test]
    fn gsm_provider_same_owner_path_reenable_does_not_restore_old_admission() {
        let mut fixture = LifecycleFixture::new_qualified();
        let old = fixture.epoch();
        assert!(fixture.old_epoch_can_control(old));
        fixture.emit_modem_state(4);
        fixture.emit_call_format(None);
        fixture.emit_modem_state(8);
        fixture.emit_call_format(Some(16000));
        // A production loss may make this control barrier itself return an error;
        // it must nevertheless consume ordered evidence and retain dirty ownership.
        let _ = fixture.flush_through_reply();
        fixture.refresh().unwrap();
        assert!(fixture.epoch() > old);
        assert!(!fixture.old_epoch_can_control(old));
        assert!(
            !fixture
                .backend
                .reconciliation()
                .unwrap()
                .native_calls_quiescent
        );
    }

    fn lifecycle_properties(
        owner: &Connection,
        path: &str,
        interface: &str,
        changed: HashMap<&str, zvariant::OwnedValue>,
        invalidated: Vec<&str>,
    ) {
        owner
            .emit_signal(
                None::<&str>,
                path,
                "org.freedesktop.DBus.Properties",
                "PropertiesChanged",
                &(interface, changed, invalidated),
            )
            .unwrap();
    }

    #[test]
    fn gsm_provider_each_observable_lifecycle_payload_invalidates_once_and_retains_dirty_key() {
        use yoyopod_protocol::call::CallAction;
        for case in 0..11 {
            let mut f = LifecycleFixture::new_qualified();
            let old = f.epoch();
            assert_eq!(f.backend.sample_rate(TEST_RINGING_CALL).unwrap(), 16000);
            let key = f.backend.registry().unwrap().tracked()[0].1.clone();
            if case >= 4 {
                f.backend.owner = Some(key.clone());
                f.backend.format_admission = Some((key.clone(), old, 16000));
                f.backend.owned_audio_port = Some("/dev/ttyUSB9".into());
            }
            match case {
                0 => f
                    .owner
                    .emit_signal(
                        None::<&str>,
                        TEST_MODEM0,
                        MODEM_INTERFACE,
                        "StateChanged",
                        &(8i32, 4i32, 0u32),
                    )
                    .unwrap(),
                1 => lifecycle_properties(
                    &f.owner,
                    TEST_MODEM0,
                    MODEM_INTERFACE,
                    HashMap::new(),
                    vec!["State"],
                ),
                2 => lifecycle_properties(
                    &f.owner,
                    TEST_MODEM0,
                    VOICE_INTERFACE,
                    HashMap::from([("EmergencyOnly", true.into())]),
                    vec![],
                ),
                3 => lifecycle_properties(
                    &f.owner,
                    TEST_MODEM0,
                    VOICE_INTERFACE,
                    HashMap::new(),
                    vec!["EmergencyOnly"],
                ),
                4 => lifecycle_properties(
                    &f.owner,
                    TEST_RINGING_CALL,
                    CALL_INTERFACE,
                    HashMap::new(),
                    vec!["AudioFormat"],
                ),
                5 => {
                    f.emit_call_format(Some(8000));
                    f.emit_call_format(Some(16000));
                }
                6 => lifecycle_properties(
                    &f.owner,
                    TEST_RINGING_CALL,
                    CALL_INTERFACE,
                    HashMap::from([("AudioFormat", zvariant::Str::from("wrong-type").into())]),
                    vec![],
                ),
                7 => lifecycle_properties(
                    &f.owner,
                    TEST_RINGING_CALL,
                    CALL_INTERFACE,
                    HashMap::new(),
                    vec!["AudioPort"],
                ),
                8 => lifecycle_properties(
                    &f.owner,
                    TEST_RINGING_CALL,
                    CALL_INTERFACE,
                    HashMap::from([("AudioPort", zvariant::Str::from("/dev/ttyUSB17").into())]),
                    vec![],
                ),
                9 => lifecycle_properties(
                    &f.owner,
                    TEST_MODEM0,
                    MODEM_INTERFACE,
                    HashMap::new(),
                    vec!["Ports"],
                ),
                10 => lifecycle_properties(
                    &f.owner,
                    TEST_MODEM0,
                    MODEM_INTERFACE,
                    HashMap::from([(
                        "Ports",
                        zvariant::OwnedValue::try_from(zvariant::Value::from(vec![(
                            "cdc-wdm0", 6u32,
                        )]))
                        .unwrap(),
                    )]),
                    vec![],
                ),
                _ => unreachable!(),
            }
            f.flush_through_reply().unwrap();
            assert_eq!(f.epoch(), old + 1, "case {case}");
            assert!(f.backend.format_admission.is_none());
            assert!(!f.old_epoch_can_control(old));
            f.emit_call_format(None);
            f.emit_call_format(Some(16000));
            f.flush_through_reply().unwrap();
            assert_eq!(f.epoch(), old + 1, "repeated invalidation case {case}");
            assert_eq!(
                f.backend.registry().unwrap().path_for(&key),
                Some(TEST_RINGING_CALL)
            );
            assert_eq!(
                f.backend.registry().unwrap().latest(&key).unwrap().phase,
                CallPhase::Ending
            );
            assert!(!f.backend.reconciliation().unwrap().native_calls_quiescent);
            f.backend
                .apply_call(&CallCommand {
                    key: key.clone(),
                    action: CallAction::Reject(yoyopod_protocol::call::RejectReason::Cancelled),
                })
                .unwrap();
            if case >= 4 {
                assert!(f.backend.owns_voice(&key));
            }
            assert_eq!(f.controls.load(Ordering::SeqCst), 0);
        }
    }

    #[test]
    fn gsm_provider_empty_port_and_normal_cleanup_preserve_idle_baseline_and_clean_reset_recovers()
    {
        let mut f = LifecycleFixture::new_qualified();
        let old = f.epoch();
        lifecycle_properties(
            &f.owner,
            TEST_RINGING_CALL,
            CALL_INTERFACE,
            HashMap::from([("AudioPort", zvariant::Str::from("").into())]),
            vec![],
        );
        f.flush_through_reply().unwrap();
        assert_eq!(f.epoch(), old);
        assert!(f.old_epoch_can_control(old));
        f.owner
            .object_server()
            .interface::<_, ReconnectVoice>(TEST_MODEM0)
            .unwrap()
            .get()
            .paths
            .lock()
            .unwrap()
            .clear();
        f.backend.reconcile_paths().unwrap();
        f.backend.refresh_availability().unwrap();
        assert!(f.backend.cached.available);
        assert!(f.backend.registry().unwrap().tracked().is_empty());
        assert!(f.backend.reconciliation().unwrap().native_calls_quiescent);
        assert!(f
            .backend
            .pending_events
            .iter()
            .any(|e| matches!(e,CallManagerWireEvent::Update(u) if u.phase==CallPhase::Ended)));
        f.emit_modem_state(4);
        f.emit_modem_state(8);
        f.flush_through_reply().unwrap();
        assert_eq!(f.epoch(), old + 1);
        assert!(
            f.backend
                .pending_events
                .iter()
                .any(|e| matches!(e,CallManagerWireEvent::Update(u) if u.phase==CallPhase::Ended)),
            "real terminal proof was discarded"
        );
        f.backend.next_recovery = None;
        f.refresh().unwrap();
        assert!(f.backend.cached.available);
        assert!(f.backend.provider_baseline().is_ok());
        assert!(f.backend.reconciliation().unwrap().native_calls_quiescent);
    }

    #[test]
    fn gsm_provider_pending_baseline_and_call_metadata_never_dispatch_control() {
        let mut f = LifecycleFixture::new_qualified();
        f.backend.provider = crate::gsm_provider::ProviderGate::default();
        f.backend.provider_identity = None;
        f.backend.refresh_availability().unwrap();
        assert!(!f.backend.cached.available);
        assert_eq!(f.backend.cached.unavailable_reason, "Audio unavailable");
        let key = f.backend.registry().unwrap().tracked()[0].1.clone();
        assert!(f
            .backend
            .apply_call(&CallCommand {
                key,
                action: yoyopod_protocol::call::CallAction::Answer
            })
            .is_err());
        assert_eq!(f.controls.load(Ordering::SeqCst), 0);
        let bus = PrivateBus::start();
        let (_owner, mut backend, _) = reconnect_fixture(&bus);
        backend.provider = crate::gsm_provider::ProviderGate::default();
        backend.provider_identity = None;
        let key = SessionKey {
            transport: yoyopod_protocol::call::CallTransport::Gsm,
            generation: 7,
            call_id: "runtime-outgoing-99".into(),
        };
        assert!(backend.dial_session(&key, "+49123456789").is_err());
        assert!(backend.owner.is_none());
        assert!(backend.registry().unwrap().tracked().is_empty());
    }

    #[test]
    fn gsm_provider_buffered_active_is_removed_but_terminal_facts_survive_invalidation() {
        let mut f = LifecycleFixture::new_qualified();
        let key = f.backend.registry().unwrap().tracked()[0].1.clone();
        let updates = f.backend.registry.as_mut().unwrap().observe(
            TEST_RINGING_CALL,
            yoyopod_protocol::call::CallDirection::Incoming,
            CallPhase::Active,
            "+49123456789",
        );
        f.backend.pending_events.extend(updates);
        f.emit_modem_state(4);
        f.emit_modem_state(8);
        f.flush_through_reply().unwrap();
        assert!(!f.backend.pending_events.iter().any(|e|matches!(e,CallManagerWireEvent::Update(u) if matches!(u.phase,CallPhase::Active|CallPhase::Held|CallPhase::Outgoing))));
        assert_eq!(
            f.backend.registry().unwrap().latest(&key).unwrap().phase,
            CallPhase::Ending
        );
    }

    #[test]
    fn gsm_provider_secondary_signal_and_fresh_read_never_invalidate_primary_proof() {
        const SECONDARY: &str = "/org/freedesktop/ModemManager1/Call/43";
        for signal in [false, true] {
            let mut f = LifecycleFixture::new_qualified();
            let old = f.epoch();
            let primary = f.backend.registry().unwrap().tracked()[0].1.clone();
            f.backend.owner = Some(primary.clone());
            f.backend.format_admission = Some((primary.clone(), old, 16000));
            let secondary = f.add_call(SECONDARY, 8000);
            // The primary is authoritative; merely reading availability must not
            // read/reject the secondary dictionary or replace its PCM proof.
            f.backend.refresh_availability().unwrap();
            assert!(f.backend.cached.available);
            if signal {
                lifecycle_properties(
                    &f.owner,
                    SECONDARY,
                    CALL_INTERFACE,
                    HashMap::new(),
                    vec!["AudioFormat"],
                );
                f.flush_through_reply().unwrap();
            } else {
                assert!(f.backend.sample_rate(SECONDARY).is_err());
            }
            assert_eq!(f.epoch(), old);
            assert_eq!(
                f.backend.format_admission,
                Some((primary.clone(), old, 16000))
            );
            assert!(f.backend.owns_voice(&primary));
            assert_eq!(
                f.backend
                    .registry()
                    .unwrap()
                    .latest(&primary)
                    .unwrap()
                    .phase,
                CallPhase::Ringing
            );
            assert_eq!(
                f.backend
                    .registry()
                    .unwrap()
                    .latest(&secondary)
                    .unwrap()
                    .phase,
                CallPhase::Ending
            );
            f.backend
                .apply_call(&CallCommand {
                    key: secondary,
                    action: yoyopod_protocol::call::CallAction::Reject(
                        yoyopod_protocol::call::RejectReason::Busy,
                    ),
                })
                .unwrap();
            assert_eq!(
                f.backend.format_admission,
                Some((primary.clone(), old, 16000))
            );
            f.remove_call(SECONDARY);
            f.backend.refresh_availability().unwrap();
            assert!(f.backend.cached.available);
            assert_eq!(f.backend.sample_rate(TEST_RINGING_CALL).unwrap(), 16000);
            assert_eq!(f.epoch(), old);
        }
    }

    #[test]
    fn gsm_provider_unowned_invalid_key_stays_ending_after_format_restore() {
        const SECONDARY: &str = "/org/freedesktop/ModemManager1/Call/43";
        let mut f = LifecycleFixture::new_qualified();
        let old = f.epoch();
        let primary = f.backend.registry().unwrap().tracked()[0].1.clone();
        let secondary = f.add_call(SECONDARY, 16000);
        lifecycle_properties(
            &f.owner,
            SECONDARY,
            CALL_INTERFACE,
            HashMap::new(),
            vec!["AudioFormat"],
        );
        f.flush_through_reply().unwrap();
        f.backend.observe_path(SECONDARY).unwrap();
        assert_eq!(f.epoch(), old);
        assert_eq!(
            f.backend
                .registry()
                .unwrap()
                .latest(&secondary)
                .unwrap()
                .phase,
            CallPhase::Ending
        );
        assert_eq!(
            f.backend
                .registry()
                .unwrap()
                .latest(&primary)
                .unwrap()
                .phase,
            CallPhase::Ringing
        );
        assert_eq!(f.backend.sample_rate(TEST_RINGING_CALL).unwrap(), 16000);
        assert!(f
            .backend
            .apply_call(&CallCommand {
                key: secondary.clone(),
                action: yoyopod_protocol::call::CallAction::Answer
            })
            .is_err());
        assert_eq!(f.controls.load(Ordering::SeqCst), 0);
        assert!(f.backend.registry().unwrap().path_for(&secondary).is_some());
        f.remove_call(SECONDARY);
        f.backend.refresh_availability().unwrap();
        assert!(f.backend.cached.available);
        assert_eq!(
            f.backend
                .registry()
                .unwrap()
                .latest(&primary)
                .unwrap()
                .phase,
            CallPhase::Ringing
        );
        assert_eq!(f.epoch(), old);
    }

    #[test]
    fn gsm_provider_real_hangup_reset_fences_preflight_buffer_before_publication() {
        const SECONDARY: &str = "/org/freedesktop/ModemManager1/Call/43";
        let mut f = LifecycleFixture::new_qualified();
        let old = f.epoch();
        let key = f.backend.registry().unwrap().tracked()[0].1.clone();
        let terminal_key = f.add_call(SECONDARY, 16000);
        f.remove_call(SECONDARY); // real Calls scan produces trusted Ended proof
        let mut buffered = f.backend.registry().unwrap().latest(&key).unwrap().clone();
        buffered.phase = CallPhase::Active;
        // Seed an earlier audio observation only; PCM startup belongs to Task 5.
        f.backend
            .pending_events
            .push(CallManagerWireEvent::Update(buffered));
        let (entered, entering) = mpsc::channel();
        let (release, releasing) = mpsc::channel();
        *f.hangup_gate.lock().unwrap() = Some((entered, releasing));
        let worker = GsmWorker::with_backend(f.backend);
        worker
            .send_at_epoch(
                GsmCommand::Action {
                    request_id: "hangup-reset".into(),
                    command: CallCommand {
                        key: key.clone(),
                        action: yoyopod_protocol::call::CallAction::Hangup,
                    },
                },
                old,
            )
            .unwrap();
        entering.recv_timeout(Duration::from_secs(3)).unwrap();
        for state in [4i32, 8i32] {
            f.owner
                .emit_signal(
                    None::<&str>,
                    TEST_MODEM0,
                    MODEM_INTERFACE,
                    "StateChanged",
                    &(8i32, state, 0u32),
                )
                .unwrap();
        }
        release.send(()).unwrap();
        let mut events = Vec::new();
        loop {
            let event = worker.events.recv_timeout(Duration::from_secs(5)).unwrap();
            let done =
                matches!(&event,GsmEvent::Completed {request_id,..} if request_id=="hangup-reset");
            events.push(event);
            if done {
                break;
            }
        }
        assert!(!events.iter().any(|e|matches!(e,GsmEvent::Call(CallManagerWireEvent::Update(u)) if matches!(u.phase,CallPhase::Active|CallPhase::Held|CallPhase::Outgoing))));
        assert!(events.iter().any(|e|matches!(e,GsmEvent::Call(CallManagerWireEvent::Update(u)) if u.key==terminal_key && u.phase==CallPhase::Ended)));
        assert!(events.iter().any(
            |e| matches!(e,GsmEvent::Call(CallManagerWireEvent::Offer(o)) if o.key==terminal_key)
        ));
        let lost = events
            .iter()
            .position(|e| matches!(e, GsmEvent::ModemLost { .. }))
            .unwrap();
        let reconciled = events
            .iter()
            .position(|e| matches!(e,GsmEvent::Reconciled(r) if r.admission_epoch>old))
            .unwrap();
        let ending=events.iter().position(|e|matches!(e,GsmEvent::Call(CallManagerWireEvent::Update(u)) if u.key==key && u.phase==CallPhase::Ending)).unwrap();
        assert!(lost < reconciled && reconciled < ending && ending < events.len() - 1);
        drop(worker);
    }

    #[test]
    fn gsm_provider_held_real_collector_fences_queued_old_dial_and_answer() {
        let f = LifecycleFixture::new_qualified();
        let old = f.epoch();
        let key = f.backend.registry().unwrap().tracked()[0].1.clone();
        let (entered, entering) = mpsc::channel();
        let (release, releasing) = mpsc::channel();
        *f.backend
            .signals
            .as_ref()
            .unwrap()
            .pause_before_forward
            .lock()
            .unwrap() = Some((entered, releasing));
        f.emit_modem_state(4);
        entering.recv_timeout(Duration::from_secs(3)).unwrap();
        f.emit_call_format(None);
        f.emit_modem_state(8);
        f.emit_call_format(Some(16000));
        let controls = f.controls.clone();
        let worker = GsmWorker::with_backend(f.backend);
        worker
            .send_at_epoch(
                GsmCommand::Action {
                    request_id: "old-answer".into(),
                    command: CallCommand {
                        key: key.clone(),
                        action: yoyopod_protocol::call::CallAction::Answer,
                    },
                },
                old,
            )
            .unwrap();
        worker
            .send_at_epoch(
                GsmCommand::DialSession {
                    request_id: "old-dial".into(),
                    key: key.clone(),
                    number: "+49123456789".into(),
                },
                old,
            )
            .unwrap();
        release.send(()).unwrap();
        let deadline = Instant::now() + Duration::from_secs(5);
        let mut completed = std::collections::HashSet::new();
        while completed.len() < 2 && Instant::now() < deadline {
            if let GsmEvent::Completed {
                request_id, error, ..
            } = worker.events.recv_timeout(Duration::from_secs(3)).unwrap()
            {
                assert!(error.unwrap().contains("command fenced"));
                completed.insert(request_id);
            }
        }
        assert_eq!(completed.len(), 2);
        assert!(worker.selected_epoch.load(Ordering::SeqCst) > old);
        assert_eq!(controls.load(Ordering::SeqCst), 0);
        drop(worker);
    }
    fn add_reconnect_modem(owner: &Connection, path: &str) {
        owner.object_server().at(path, ReconnectModem).unwrap();
        owner
            .object_server()
            .at(
                path,
                ReconnectVoice {
                    reads: Arc::new(std::sync::atomic::AtomicUsize::new(0)),
                    creates: Arc::new(std::sync::atomic::AtomicUsize::new(0)),
                    gate: Arc::new(Mutex::new(None)),
                    fail: Arc::new(std::sync::atomic::AtomicBool::new(false)),
                    paths: Arc::new(Mutex::new(Vec::new())),
                },
            )
            .unwrap();
    }
    #[test]
    fn gsm_reconnect_clean_same_owner_retains_connection_and_registry() {
        let bus = PrivateBus::start();
        let (owner, mut backend, old_reads) = reconnect_fixture(&bus);
        let token = backend.reconciliation().unwrap().native_owner;
        let connection_name = backend
            .connection
            .as_ref()
            .unwrap()
            .unique_name()
            .unwrap()
            .to_string();
        let outgoing_key = SessionKey {
            transport: yoyopod_protocol::call::CallTransport::Gsm,
            generation: 7,
            call_id: "runtime-outgoing-11".into(),
        };
        backend
            .registry
            .as_mut()
            .unwrap()
            .register_outgoing(&outgoing_key, "/call/outgoing")
            .unwrap();
        backend.registry.as_mut().unwrap().remove(&outgoing_key);
        let events = backend.registry.as_mut().unwrap().observe(
            "/call/reused",
            yoyopod_protocol::call::CallDirection::Incoming,
            CallPhase::Ringing,
            "+49123456789",
        );
        let CallManagerWireEvent::Offer(first) = &events[0] else {
            panic!("offer")
        };
        backend.registry.as_mut().unwrap().remove(&first.key);
        remove_reconnect_modem(&owner);
        let _ = backend.refresh();
        assert!(
            !backend.cached.available,
            "removed selected modem must immediately become unavailable"
        );
        add_reconnect_modem(&owner, TEST_MODEM2);
        let before = old_reads.load(std::sync::atomic::Ordering::SeqCst);
        backend.next_discovery = None;
        backend.refresh().unwrap();
        assert_eq!(
            backend.modem.as_ref().map(|path| path.as_str()),
            Some(TEST_MODEM2),
            "idle same-owner modem never rediscovered"
        );
        assert!(backend.cached.available);
        assert_eq!(old_reads.load(std::sync::atomic::Ordering::SeqCst), before);
        assert_eq!(backend.reconciliation().unwrap().native_owner, token);
        assert_eq!(backend.generation, Some(7));
        assert_eq!(
            backend
                .connection
                .as_ref()
                .unwrap()
                .unique_name()
                .unwrap()
                .as_str(),
            connection_name
        );
        let next = backend.registry.as_mut().unwrap().observe(
            "/call/reused",
            yoyopod_protocol::call::CallDirection::Incoming,
            CallPhase::Ringing,
            "+49123456789",
        );
        let CallManagerWireEvent::Offer(next) = &next[0] else {
            panic!("offer")
        };
        assert_ne!(first.key, next.key);
        assert!(
            !backend.registry().unwrap().is_fresh_key(&outgoing_key),
            "rediscovery reset the outgoing watermark"
        );
        let hits = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        owner
            .object_server()
            .at("/call/reused", ReplacementCall(hits.clone()))
            .unwrap();
        assert!(backend
            .apply_call(&CallCommand {
                key: first.key.clone(),
                action: yoyopod_protocol::call::CallAction::Hangup
            })
            .is_err());
        backend
            .apply_call(&CallCommand {
                key: next.key.clone(),
                action: yoyopod_protocol::call::CallAction::Hangup,
            })
            .unwrap();
        assert_eq!(
            hits.load(Ordering::SeqCst),
            1,
            "fresh logical key did not address the replacement native path exactly once"
        );
    }
    #[test]
    fn gsm_reconnect_missing_signal_confirms_absence_but_keeps_dirty_identity() {
        let bus = PrivateBus::start();
        let (owner, mut backend, _) = reconnect_fixture(&bus);
        let events = backend.registry.as_mut().unwrap().observe(
            "/call/old",
            yoyopod_protocol::call::CallDirection::Incoming,
            CallPhase::Ringing,
            "+49123456789",
        );
        let CallManagerWireEvent::Offer(offer) = &events[0] else {
            panic!("offer")
        };
        let key = offer.key.clone();
        backend.owner = Some(key.clone());
        remove_reconnect_modem(&owner);
        // Deliberately consume the real signal: property failure must confirm absence.
        let _ = backend
            .signals
            .as_ref()
            .unwrap()
            .messages
            .recv_timeout(Duration::from_secs(2));
        backend
            .signals
            .as_ref()
            .unwrap()
            .messages
            .try_iter()
            .for_each(drop);
        backend.next_recovery = None;
        let _ = backend.refresh();
        assert!(!backend.cached.available);
        assert_eq!(
            backend.registry().unwrap().latest(&key).unwrap().phase,
            CallPhase::Ending,
            "loss did not retain uncertain old lifetime as Ending"
        );
        add_reconnect_modem(&owner, TEST_MODEM2);
        backend.next_discovery = None;
        let _ = backend.refresh();
        assert_eq!(
            backend.registry().unwrap().path_for(&key),
            Some("/call/old")
        );
        assert!(backend.owns_voice(&key));
        assert!(!backend.reconciliation().unwrap().native_calls_quiescent);
        assert!(!backend.drain_call_events().iter().any(|event| matches!(event, CallManagerWireEvent::Update(update) if update.phase == CallPhase::Ended)));
        assert_ne!(
            backend.modem.as_ref().map(|path| path.as_str()),
            Some(TEST_MODEM2)
        );
    }

    #[test]
    fn gsm_reconnect_blocked_old_calls_removal_never_manufactures_release() {
        let bus = PrivateBus::start();
        let (owner, mut backend, _) = reconnect_fixture(&bus);
        let events = backend.registry.as_mut().unwrap().observe(
            "/call/old",
            yoyopod_protocol::call::CallDirection::Incoming,
            CallPhase::Ringing,
            "+49123456789",
        );
        let CallManagerWireEvent::Offer(offer) = &events[0] else {
            panic!("offer")
        };
        let key = offer.key.clone();
        backend.owner = Some(key.clone());
        let (entered, entering) = mpsc::channel();
        let (release, releasing) = mpsc::channel();
        *owner
            .object_server()
            .interface::<_, ReconnectVoice>(TEST_MODEM0)
            .unwrap()
            .get()
            .gate
            .lock()
            .unwrap() = Some((entered, releasing));
        let scan = thread::spawn(move || {
            let result = backend.reconcile_paths();
            (backend, result)
        });
        entering.recv_timeout(Duration::from_secs(3)).unwrap();
        // Voice getter is outstanding; remove only Modem to avoid its read lock.
        owner
            .emit_signal(
                None::<&str>,
                "/org/freedesktop/ModemManager1",
                "org.freedesktop.DBus.ObjectManager",
                "InterfacesRemoved",
                &(
                    OwnedObjectPath::try_from(TEST_MODEM0).unwrap(),
                    vec![MODEM_INTERFACE],
                ),
            )
            .unwrap();
        // Let the subscribed signal reach the independent collector before
        // releasing the deliberately outstanding old Calls response.
        thread::sleep(Duration::from_millis(20));
        release.send(()).unwrap();
        let (mut backend, result) = scan.join().unwrap();
        assert!(result.is_err());
        assert!(backend.modem_lost);
        assert!(backend.owns_voice(&key));
        assert_eq!(
            backend.registry().unwrap().latest(&key).unwrap().phase,
            CallPhase::Ending
        );
        assert_eq!(
            backend.registry().unwrap().path_for(&key),
            Some("/call/old")
        );
        assert!(!backend.reconciliation().unwrap().native_calls_quiescent);
        assert!(!backend.drain_call_events().iter().any(|event| matches!(event, CallManagerWireEvent::Update(update) if update.phase == CallPhase::Ended)));
    }

    #[test]
    fn gsm_reconnect_old_object_present_error_or_timeout_is_not_disappearance() {
        for timeout in [false, true] {
            let bus = PrivateBus::start();
            let (owner, mut backend, _) = reconnect_fixture_timeout(
                &bus,
                if timeout {
                    Duration::from_millis(100)
                } else {
                    Duration::from_secs(3)
                },
            );
            let interface = owner
                .object_server()
                .interface::<_, ReconnectVoice>(TEST_MODEM0)
                .unwrap();
            let (release, releasing) = mpsc::channel();
            let (entered, entering) = mpsc::channel();
            if timeout {
                // Preserve the signal connection; only shorten this fixture's method deadline.
                *interface.get().gate.lock().unwrap() = Some((entered, releasing));
            } else {
                interface.get().fail.store(true, Ordering::SeqCst);
            }
            backend.next_recovery = None;
            let scan = thread::spawn(move || {
                let result = backend.refresh();
                (backend, result)
            });
            if timeout {
                entering.recv_timeout(Duration::from_secs(3)).unwrap();
            }
            let (backend, result) = scan.join().unwrap();
            if timeout {
                release.send(()).unwrap();
            }
            assert!(result.is_err());
            assert!(
                !backend.modem_lost,
                "general native read failure invented a modem-loss transition"
            );
            assert_eq!(backend.selected_epoch, 0);
            assert_eq!(
                backend.modem.as_ref().map(|path| path.as_str()),
                Some(TEST_MODEM0)
            );
        }
    }

    #[test]
    fn gsm_reconnect_uncertain_create_cleanup_deadline_and_pending_fact_fail_closed() {
        for blocker in 0..7 {
            let bus = PrivateBus::start();
            let (owner, mut backend, _) = reconnect_fixture(&bus);
            let key = SessionKey {
                transport: yoyopod_protocol::call::CallTransport::Gsm,
                generation: 7,
                call_id: "runtime-outgoing-9".into(),
            };
            match blocker {
                0 => {
                    backend.uncertain_create = Some(key.clone());
                    backend.owner = Some(key.clone());
                }
                1 => backend.cleanup.failed("/call/uncertain"),
                2 => backend.audio_deadline = Some(Instant::now() + Duration::from_secs(8)),
                3 => {
                    backend.pending_events = backend.registry.as_mut().unwrap().observe(
                        "/call/pending",
                        yoyopod_protocol::call::CallDirection::Incoming,
                        CallPhase::Ringing,
                        "+49123456789",
                    );
                }
                4 => {
                    backend
                        .registry
                        .as_mut()
                        .unwrap()
                        .register_outgoing(&key, "/call/active")
                        .unwrap();
                    backend.registry.as_mut().unwrap().observe(
                        "/call/active",
                        yoyopod_protocol::call::CallDirection::Outgoing,
                        CallPhase::Active,
                        "+49123456789",
                    );
                    backend.owner = Some(key.clone());
                }
                5 => {
                    backend.terminating.insert("/call/terminating".into());
                }
                _ => {
                    backend.registry.as_mut().unwrap().observe(
                        "/call/unowned",
                        yoyopod_protocol::call::CallDirection::Incoming,
                        CallPhase::Ringing,
                        "+49123456789",
                    );
                }
            }
            remove_reconnect_modem(&owner);
            backend.next_recovery = None;
            let _ = backend.refresh();
            assert!(backend.modem_lost);
            assert!(!backend.clean_rediscovery);
            add_reconnect_modem(&owner, TEST_MODEM2);
            backend.next_discovery = None;
            let _ = backend.refresh();
            assert!(!backend.cached.available);
            assert_ne!(
                backend.modem.as_ref().map(|path| path.as_str()),
                Some(TEST_MODEM2)
            );
            assert!(!backend.reconciliation().unwrap().native_calls_quiescent);
            if blocker == 0 {
                assert!(backend.owns_voice(&key));
                assert_eq!(backend.uncertain_create.as_ref(), Some(&key));
            }
            if blocker == 1 {
                assert!(backend.cleanup.uncertain.contains("/call/uncertain"));
            }
            if blocker == 4 {
                assert!(backend.owns_voice(&key));
                assert_eq!(
                    backend.registry().unwrap().latest(&key).unwrap().phase,
                    CallPhase::Ending
                );
                assert_eq!(
                    backend.registry().unwrap().path_for(&key),
                    Some("/call/active")
                );
            }
            if blocker == 5 {
                assert!(backend.terminating.contains("/call/terminating"));
            }
        }
    }

    #[test]
    fn gsm_reconnect_native_queue_fences_old_answer_hangup_and_dial() {
        struct QueuedBackend {
            epoch: Arc<AtomicU64>,
            gate: Option<(Sender<()>, Receiver<()>)>,
            invoked: Arc<Mutex<Vec<String>>>,
        }
        impl GsmBackend for QueuedBackend {
            fn selected_modem_epoch(&self) -> u64 {
                self.epoch.load(Ordering::SeqCst)
            }
            fn refresh(&mut self) -> Result<GsmCallState> {
                if let Some((entered, release)) = self.gate.take() {
                    entered.send(())?;
                    release.recv_timeout(Duration::from_secs(3))?;
                }
                Ok(GsmCallState::default())
            }
            fn apply_call(&mut self, command: &CallCommand) -> Result<()> {
                self.invoked
                    .lock()
                    .unwrap()
                    .push(format!("{:?}", command.action));
                Ok(())
            }
            fn dial_session(&mut self, _: &SessionKey, _: &str) -> Result<()> {
                self.invoked.lock().unwrap().push("dial".into());
                Ok(())
            }
            fn dial(&mut self, _: &str) -> Result<()> {
                Ok(())
            }
            fn hangup(&mut self) -> Result<()> {
                Ok(())
            }
            fn mute(&mut self, _: bool) -> Result<()> {
                Ok(())
            }
        }
        let epoch = Arc::new(AtomicU64::new(0));
        let invoked = Arc::new(Mutex::new(Vec::new()));
        let (entered, entering) = mpsc::channel();
        let (release, releasing) = mpsc::channel();
        let worker = GsmWorker::with_backend(QueuedBackend {
            epoch: epoch.clone(),
            invoked: invoked.clone(),
            gate: Some((entered, releasing)),
        });
        let key = SessionKey {
            transport: yoyopod_protocol::call::CallTransport::Gsm,
            generation: 7,
            call_id: "runtime-outgoing-1".into(),
        };
        worker
            .send(GsmCommand::Action {
                request_id: "answer-old".into(),
                command: CallCommand {
                    key: key.clone(),
                    action: yoyopod_protocol::call::CallAction::Answer,
                },
            })
            .unwrap();
        entering.recv_timeout(Duration::from_secs(3)).unwrap();
        worker
            .send(GsmCommand::Action {
                request_id: "hangup-old".into(),
                command: CallCommand {
                    key: key.clone(),
                    action: yoyopod_protocol::call::CallAction::Hangup,
                },
            })
            .unwrap();
        worker
            .send(GsmCommand::DialSession {
                request_id: "dial-old".into(),
                key: key.clone(),
                number: "+49123456789".into(),
            })
            .unwrap();
        epoch.store(1, Ordering::SeqCst);
        release.send(()).unwrap();
        for _ in 0..3 {
            let GsmEvent::Completed {
                key: reported,
                error,
                ..
            } = worker.events.recv_timeout(Duration::from_secs(3)).unwrap()
            else {
                panic!("keyed result")
            };
            assert_eq!(reported, key);
            assert!(error.is_some());
        }
        assert!(invoked.lock().unwrap().is_empty());
        worker
            .send_at_epoch(
                GsmCommand::DialSession {
                    request_id: "dial-fresh".into(),
                    key,
                    number: "+49123456789".into(),
                },
                1,
            )
            .unwrap();
        let GsmEvent::Completed { error, .. } =
            worker.events.recv_timeout(Duration::from_secs(3)).unwrap()
        else {
            panic!("fresh result")
        };
        assert!(error.is_none());
        assert_eq!(invoked.lock().unwrap().as_slice(), ["dial"]);
    }

    #[test]
    fn gsm_reconnect_replacement_profile_gate_and_pending_native_addition_remain_closed() {
        let bus = PrivateBus::start();
        let (owner, mut backend, _) = reconnect_fixture(&bus);
        remove_reconnect_modem(&owner);
        backend.next_recovery = None;
        let _ = backend.refresh();
        assert!(backend.clean_rediscovery);
        owner
            .object_server()
            .interface::<_, ReconnectManager>("/org/freedesktop/ModemManager1")
            .unwrap()
            .get_mut()
            .version = "1.25.0";
        add_reconnect_modem(&owner, TEST_MODEM2);
        backend.next_discovery = None;
        backend.refresh().unwrap();
        assert!(!backend.cached.available);
        assert!(!backend.isolated);
        assert!(!backend.reconciliation().unwrap().native_calls_quiescent);

        let bus = PrivateBus::start();
        let (owner, mut backend, _) = reconnect_fixture(&bus);
        owner
            .emit_signal(
                None::<&str>,
                TEST_MODEM0,
                VOICE_INTERFACE,
                "CallAdded",
                &(OwnedObjectPath::try_from("/org/freedesktop/ModemManager1/Call/9").unwrap(),),
            )
            .unwrap();
        let added = backend
            .signals
            .as_ref()
            .unwrap()
            .messages
            .recv_timeout(Duration::from_secs(3))
            .unwrap();
        backend.removal_signal(&added);
        assert!(
            !backend.idle_calls_proven,
            "unreconciled CallAdded retained stale idle proof"
        );
        remove_reconnect_modem(&owner);
        backend.next_recovery = None;
        let _ = backend.refresh();
        assert!(backend.modem_lost);
        assert!(!backend.clean_rediscovery);
    }

    #[test]
    fn gsm_reconnect_signal_overflow_keeps_subscription_and_invalidates_native_evidence() {
        let bus = PrivateBus::start();
        let (owner, mut backend, _) = reconnect_fixture_capacity(&bus, Duration::from_secs(3), 1);
        let events = backend.registry.as_mut().unwrap().observe(
            "/call/owned",
            yoyopod_protocol::call::CallDirection::Incoming,
            CallPhase::Active,
            "+49123456789",
        );
        let CallManagerWireEvent::Update(update) = &events[0] else {
            panic!("active update")
        };
        let key = update.key.clone();
        backend.owner = Some(key.clone());
        let token = backend.reconciliation().unwrap().native_owner;
        // The actor deliberately does not drain while its subscribed private
        // bus receives more messages than the internal native queue can hold.
        for _ in 0..3 {
            owner
                .emit_signal(
                    None::<&str>,
                    TEST_MODEM0,
                    MODEM_INTERFACE,
                    "StateChanged",
                    &(8i32, 8i32, 0u32),
                )
                .unwrap();
        }
        let deadline = Instant::now() + Duration::from_secs(1);
        while !backend
            .signals
            .as_ref()
            .unwrap()
            .thread
            .as_ref()
            .unwrap()
            .is_finished()
            && Instant::now() < deadline
        {
            thread::sleep(Duration::from_millis(5));
        }
        assert!(
            !backend
                .signals
                .as_ref()
                .unwrap()
                .thread
                .as_ref()
                .unwrap()
                .is_finished(),
            "native queue overflow silently killed retained signal subscription"
        );
        let _ = backend.refresh();
        assert!(!backend.cached.available);
        assert!(backend.service_invalidated);
        assert_eq!(backend.selected_epoch, 1);
        assert_eq!(backend.take_modem_loss(), Some(7));
        assert_eq!(backend.reconciliation().unwrap().native_owner, token);
        assert!(!backend.reconciliation().unwrap().native_calls_quiescent);
        assert!(backend.owns_voice(&key));
        assert_eq!(
            backend.registry().unwrap().path_for(&key),
            Some("/call/owned")
        );
        assert_eq!(
            backend.registry().unwrap().latest(&key).unwrap().phase,
            CallPhase::Ending
        );
        add_reconnect_modem(&owner, TEST_MODEM2);
        backend.next_discovery = None;
        let _ = backend.refresh();
        assert_ne!(
            backend.modem.as_ref().map(|p| p.as_str()),
            Some(TEST_MODEM2)
        );
    }

    #[test]
    fn gsm_reconnect_new_call_added_during_old_empty_calls_scan_blocks_clean_loss() {
        let bus = PrivateBus::start();
        let (owner, mut backend, _) = reconnect_fixture(&bus);
        let token = backend.reconciliation().unwrap().native_owner;
        let connection_name = backend
            .connection
            .as_ref()
            .unwrap()
            .unique_name()
            .unwrap()
            .to_owned();
        assert!(backend.idle_calls_proven);
        let (entered, entering) = mpsc::channel();
        let (release, releasing) = mpsc::channel();
        let interface = owner
            .object_server()
            .interface::<_, ReconnectVoice>(TEST_MODEM0)
            .unwrap();
        *interface.get().gate.lock().unwrap() = Some((entered, releasing));
        let paths = interface.get().paths.clone();

        // Forward the actual retained subscription messages while acknowledging
        // that CallAdded has entered the actor's receiver before its old property
        // response is released. This fixes the ordering without a timing sleep.
        let (forward, forwarded) = mpsc::channel();
        let source = std::mem::replace(&mut backend.signals.as_mut().unwrap().messages, forwarded);
        let (delivered, delivery) = mpsc::channel();
        let relay = thread::spawn(move || {
            while let Ok(message) = source.recv_timeout(Duration::from_secs(3)) {
                let added = message.header().member().map(|m| m.as_str()) == Some("CallAdded");
                if forward.send(message).is_err() {
                    break;
                }
                if added {
                    let _ = delivered.send(());
                }
            }
        });
        let scan = thread::spawn(move || {
            let result = backend.reconcile_paths();
            (backend, result)
        });
        entering.recv_timeout(Duration::from_secs(3)).unwrap();
        let added_path =
            OwnedObjectPath::try_from("/org/freedesktop/ModemManager1/Call/9").unwrap();
        paths.lock().unwrap().push(added_path.clone());
        owner
            .emit_signal(
                None::<&str>,
                TEST_MODEM0,
                VOICE_INTERFACE,
                "CallAdded",
                &(added_path,),
            )
            .unwrap();
        delivery.recv_timeout(Duration::from_secs(3)).unwrap();
        release.send(()).unwrap();
        let (mut backend, result) = scan.join().unwrap();
        assert!(result.is_ok());
        assert!(
            !backend.idle_calls_proven,
            "older Calls=[] overwrote newer native addition evidence"
        );
        assert!(!backend.reconciliation().unwrap().native_calls_quiescent);
        assert!(backend.registry().unwrap().tracked().is_empty());
        assert!(!backend.drain_call_events().iter().any(|event| matches!(event, CallManagerWireEvent::Update(update) if update.phase == CallPhase::Ended)));

        // Loss occurs before another successful Calls scan, so a replacement's
        // empty property cannot certify the unresolved old addition as released.
        remove_reconnect_modem(&owner);
        backend.next_recovery = None;
        let _ = backend.refresh();
        assert!(backend.modem_lost);
        assert!(!backend.clean_rediscovery);
        assert!(!backend.cached.available);
        assert_eq!(backend.selected_epoch, 1);
        assert_eq!(backend.take_modem_loss(), Some(7));
        add_reconnect_modem(&owner, TEST_MODEM2);
        backend.next_discovery = None;
        let _ = backend.refresh();
        assert!(!backend.cached.available);
        assert_ne!(
            backend.modem.as_ref().map(|p| p.as_str()),
            Some(TEST_MODEM2)
        );
        assert!(!backend.reconciliation().unwrap().native_calls_quiescent);
        assert_eq!(backend.reconciliation().unwrap().native_owner, token);
        assert_eq!(backend.generation, Some(7));
        assert_eq!(
            backend.connection.as_ref().unwrap().unique_name().unwrap(),
            &connection_name
        );
        drop(backend);
        relay.join().unwrap();
    }
    #[test]
    fn gsm_reconnect_paused_collector_fences_same_path_replacement_before_old_cleanup() {
        let bus = PrivateBus::start();
        let (owner, mut backend, _) = reconnect_fixture(&bus);
        let token = backend.reconciliation().unwrap().native_owner;
        let events = backend.registry.as_mut().unwrap().observe(
            "/call/old",
            yoyopod_protocol::call::CallDirection::Incoming,
            CallPhase::Ringing,
            "+49123456789",
        );
        let CallManagerWireEvent::Offer(offer) = &events[0] else {
            panic!("offer")
        };
        let key = offer.key.clone();
        backend.owner = Some(key.clone());
        let (entered, entering) = mpsc::channel();
        let (release, releasing) = mpsc::channel();
        *backend
            .signals
            .as_ref()
            .unwrap()
            .pause_before_forward
            .lock()
            .unwrap() = Some((entered, releasing));
        remove_reconnect_modem(&owner);
        entering.recv_timeout(Duration::from_secs(3)).unwrap();
        add_reconnect_modem(&owner, TEST_MODEM0);
        let (finished, finish) = mpsc::channel();
        let scan = thread::spawn(move || {
            let result = backend.reconcile_paths();
            let _ = finished.send(());
            (backend, result)
        });
        let completed_while_paused = finish.recv_timeout(Duration::from_millis(100)).is_ok();
        // Always release and join before assertions, including the RED case.
        release.send(()).unwrap();
        let (mut backend, result) = scan.join().unwrap();
        assert!(
            !completed_while_paused,
            "native cleanup accepted replacement facts before collector forwarded earlier removal"
        );
        assert!(result.is_err());
        assert!(backend.modem_lost);
        assert!(!backend.clean_rediscovery);
        assert_eq!(backend.selected_epoch, 1);
        assert_eq!(backend.take_modem_loss(), Some(7));
        assert_eq!(
            backend.registry().unwrap().path_for(&key),
            Some("/call/old")
        );
        assert!(backend.owns_voice(&key));
        assert!(!backend.reconciliation().unwrap().native_calls_quiescent);
        assert_eq!(backend.reconciliation().unwrap().native_owner, token);
        assert_eq!(backend.generation, Some(7));
        assert!(!backend.drain_call_events().iter().any(|event| matches!(event, CallManagerWireEvent::Update(update) if update.phase == CallPhase::Ended)));
        add_reconnect_modem(&owner, TEST_MODEM2);
        backend.next_recovery = None;
        let _ = backend.refresh();
        assert!(!backend.cached.available);
        assert_eq!(
            backend.modem.as_ref().map(|p| p.as_str()),
            Some(TEST_MODEM0)
        );
        drop(backend);
    }

    #[test]
    fn gsm_reconnect_collector_progress_timeout_permanently_quarantines_old_identity() {
        let bus = PrivateBus::start();
        let (owner, mut backend, _) = reconnect_fixture(&bus);
        let token = backend.reconciliation().unwrap().native_owner;
        let (entered, entering) = mpsc::channel();
        let (release, releasing) = mpsc::channel();
        *backend
            .signals
            .as_ref()
            .unwrap()
            .pause_before_forward
            .lock()
            .unwrap() = Some((entered, releasing));
        remove_reconnect_modem(&owner);
        entering.recv_timeout(Duration::from_secs(3)).unwrap();
        add_reconnect_modem(&owner, TEST_MODEM0);
        let reply = backend
            .connection
            .as_ref()
            .unwrap()
            .call_method(
                Some(backend.bound_owner().unwrap()),
                "/org/freedesktop/ModemManager1",
                Some("org.freedesktop.DBus.ObjectManager"),
                "GetManagedObjects",
                &(),
            )
            .unwrap();
        let result = backend
            .signals
            .as_ref()
            .unwrap()
            .wait_through(reply.recv_position(), Duration::from_millis(100));
        release.send(()).unwrap();
        assert!(
            result.is_err(),
            "paused collector supplied no ordered native evidence"
        );
        assert!(backend.verify_service_owner().is_err());
        assert!(backend.service_invalidated);
        assert!(backend.modem_lost);
        assert!(!backend.clean_rediscovery);
        assert_eq!(backend.selected_epoch, 1);
        assert_eq!(backend.take_modem_loss(), Some(7));
        add_reconnect_modem(&owner, TEST_MODEM2);
        backend.next_recovery = None;
        backend.next_discovery = None;
        let _ = backend.refresh();
        assert!(backend.signals.is_some());
        assert!(!backend.cached.available);
        assert!(!backend.reconciliation().unwrap().native_calls_quiescent);
        assert_eq!(backend.reconciliation().unwrap().native_owner, token);
        assert_eq!(backend.generation, Some(7));
        assert_eq!(
            backend.modem.as_ref().map(|p| p.as_str()),
            Some(TEST_MODEM0)
        );
        drop(backend);
    }

    fn emit_selected_membership(owner: &Connection, member: &str) {
        owner
            .emit_signal(
                None::<&str>,
                TEST_MODEM0,
                VOICE_INTERFACE,
                member,
                &(OwnedObjectPath::try_from(TEST_RINGING_CALL).unwrap(),),
            )
            .unwrap();
    }

    #[test]
    fn gsm_reconnect_membership_added_is_offered_on_first_refresh_before_fallback() {
        let bus = PrivateBus::start();
        let (owner, mut backend, _) = reconnect_fixture(&bus);
        backend.next_recovery = Some(Instant::now() + Duration::from_secs(3600));
        owner
            .object_server()
            .at(TEST_RINGING_CALL, ReconnectRingingCall)
            .unwrap();
        let interface = owner
            .object_server()
            .interface::<_, ReconnectVoice>(TEST_MODEM0)
            .unwrap();
        interface
            .get()
            .paths
            .lock()
            .unwrap()
            .push(OwnedObjectPath::try_from(TEST_RINGING_CALL).unwrap());
        emit_selected_membership(&owner, "CallAdded");
        backend.refresh().unwrap();
        let events = backend.drain_call_events();
        assert!(events.iter().any(|event| matches!(event, CallManagerWireEvent::Offer(offer) if offer.address == "+49123456789")), "first refresh lost selected CallAdded before its fallback deadline");
        assert_eq!(backend.registry().unwrap().tracked().len(), 1);
        assert!(!backend.reconciliation().unwrap().native_calls_quiescent);
        assert_eq!(backend.selected_epoch, 0);
        assert!(!backend.membership_reconcile_pending);
    }

    #[test]
    fn gsm_reconnect_membership_deleted_reconciles_on_first_refresh_before_fallback() {
        let bus = PrivateBus::start();
        let (owner, mut backend, _) = reconnect_fixture(&bus);
        owner
            .object_server()
            .at(TEST_RINGING_CALL, ReconnectRingingCall)
            .unwrap();
        let interface = owner
            .object_server()
            .interface::<_, ReconnectVoice>(TEST_MODEM0)
            .unwrap();
        let paths = interface.get().paths.clone();
        paths
            .lock()
            .unwrap()
            .push(OwnedObjectPath::try_from(TEST_RINGING_CALL).unwrap());
        backend.reconcile_paths().unwrap();
        let key = backend.registry().unwrap().tracked()[0].1.clone();
        backend.drain_call_events();
        backend.next_recovery = Some(Instant::now() + Duration::from_secs(3600));
        paths.lock().unwrap().clear();
        owner
            .object_server()
            .remove::<ReconnectRingingCall, _>(TEST_RINGING_CALL)
            .unwrap();
        emit_selected_membership(&owner, "CallDeleted");
        let result = backend.refresh();
        assert!(
            result.is_ok(),
            "CallDeleted was lost and refresh polled an already deleted native object: {result:?}"
        );
        assert!(backend.registry().unwrap().tracked().is_empty());
        assert!(backend.drain_call_events().iter().any(|event| matches!(event, CallManagerWireEvent::Update(update) if update.key == key && update.phase == CallPhase::Ended)));
        assert!(backend.reconciliation().unwrap().native_calls_quiescent);
        assert_eq!(backend.selected_epoch, 0);
        assert!(!backend.membership_reconcile_pending);
    }

    #[test]
    fn gsm_reconnect_membership_work_survives_stale_snapshot_and_failed_fresh_scan() {
        let bus = PrivateBus::start();
        let (owner, mut backend, _) = reconnect_fixture(&bus);
        backend.next_recovery = Some(Instant::now() + Duration::from_secs(3600));
        owner
            .object_server()
            .at(TEST_RINGING_CALL, ReconnectRingingCall)
            .unwrap();
        let interface = owner
            .object_server()
            .interface::<_, ReconnectVoice>(TEST_MODEM0)
            .unwrap();
        let paths = interface.get().paths.clone();
        let fail = interface.get().fail.clone();
        let (entered, entering) = mpsc::channel();
        let (release, releasing) = mpsc::channel();
        *interface.get().gate.lock().unwrap() = Some((entered, releasing));
        let scan = thread::spawn(move || {
            let result = backend.reconcile_paths();
            (backend, result)
        });
        entering.recv_timeout(Duration::from_secs(3)).unwrap();
        paths
            .lock()
            .unwrap()
            .push(OwnedObjectPath::try_from(TEST_RINGING_CALL).unwrap());
        emit_selected_membership(&owner, "CallAdded");
        release.send(()).unwrap();
        let (mut backend, result) = scan.join().unwrap();
        assert!(result.is_ok());
        assert!(!backend.idle_calls_proven);
        assert!(backend.drain_call_events().is_empty());
        assert!(backend.membership_reconcile_pending);
        fail.store(true, Ordering::SeqCst);
        assert!(
            backend.refresh().is_err(),
            "stale snapshot discarded membership work instead of attempting a fresh scan"
        );
        assert!(!backend.modem_lost);
        assert!(backend.membership_reconcile_pending);
        fail.store(false, Ordering::SeqCst);
        backend.refresh().unwrap();
        assert!(backend.drain_call_events().iter().any(|event| matches!(event, CallManagerWireEvent::Offer(offer) if offer.address == "+49123456789")), "failed fresh observation discarded pending membership work");
        assert_eq!(backend.registry().unwrap().tracked().len(), 1);
        assert_eq!(backend.selected_epoch, 0);
        assert!(!backend.membership_reconcile_pending);
    }

    fn replace_owner(connection: &Connection) {
        use zbus::fdo::RequestNameFlags;
        connection
            .request_name_with_flags(
                DESTINATION,
                RequestNameFlags::ReplaceExisting | RequestNameFlags::DoNotQueue,
            )
            .unwrap();
    }

    #[test]
    fn gsm_owner_replacement_cannot_retarget_queued_old_key_or_captured_call_proxy() {
        let bus = PrivateBus::start();
        let old = bus.connection();
        let replacement = bus.connection();
        let old_calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        let replacement_calls = Arc::new(std::sync::atomic::AtomicUsize::new(0));
        old.object_server()
            .at("/call/0", ReplacementCall(old_calls.clone()))
            .unwrap();
        replacement
            .object_server()
            .at("/call/0", ReplacementCall(replacement_calls.clone()))
            .unwrap();
        allow_replacement(&old);
        let (mut backend, key) = old_native_backend(&bus, &old);
        backend.ensure_control().unwrap();
        let captured = backend.proxy_for("/call/0").unwrap();
        replace_owner(&replacement);
        // The real proxy builder must remain bound even if replacement occurs
        // after validation, not merely reject when a pre-action poll sees it.
        captured.call::<_, _, ()>("Hangup", &()).unwrap();
        drop(captured);
        assert_eq!(
            replacement_calls.load(std::sync::atomic::Ordering::SeqCst),
            0,
            "captured proxy followed the well-known name to a replacement call"
        );
        assert!(backend
            .apply_call(&CallCommand {
                key: key.clone(),
                action: yoyopod_protocol::call::CallAction::Hangup
            })
            .is_err());
        assert!(backend.owns_voice(&key));
        assert!(!backend.reconciliation().unwrap().native_calls_quiescent);
        assert_eq!(
            replacement_calls.load(std::sync::atomic::Ordering::SeqCst),
            0
        );
    }

    #[test]
    fn gsm_owner_replacement_during_empty_calls_scan_is_not_old_cleanup_evidence() {
        let bus = PrivateBus::start();
        let old = bus.connection();
        let replacement = bus.connection();
        let (entered_tx, entered_rx) = mpsc::channel();
        let (release_tx, release_rx) = mpsc::channel();
        old.object_server()
            .at(
                "/modem/0",
                EmptyCalls {
                    gate: Mutex::new(Some((entered_tx, release_rx))),
                },
            )
            .unwrap();
        replacement
            .object_server()
            .at(
                "/modem/0",
                EmptyCalls {
                    gate: Mutex::new(None),
                },
            )
            .unwrap();
        allow_replacement(&old);
        let (mut backend, key) = old_native_backend(&bus, &old);
        backend.ensure_control().unwrap();
        let scan = thread::spawn(move || {
            let result = backend.reconcile_paths();
            (backend, result)
        });
        entered_rx
            .recv_timeout(Duration::from_secs(3))
            .expect("scan reached old owner's Calls getter");
        replace_owner(&replacement);
        release_tx.send(()).unwrap();
        let (mut backend, result) = scan.join().unwrap();
        assert!(
            result.is_err(),
            "owner changed during scan but empty Calls was treated as old cleanup proof"
        );
        assert!(backend.owns_voice(&key));
        assert_eq!(backend.registry().unwrap().path_for(&key), Some("/call/0"));
        assert!(!backend.reconciliation().unwrap().native_calls_quiescent);
        assert!(!backend.drain_call_events().iter().any(|event| matches!(event, CallManagerWireEvent::Update(update) if update.phase == CallPhase::Ended)));
    }

    #[test]
    fn gsm_native_owner_fact_precedes_session_events_and_survives_invalidation() {
        let bus = PrivateBus::start();
        let owner = bus.connection();
        let (mut backend, _) = old_native_backend(&bus, &owner);
        let second_bus = PrivateBus::start();
        let second_owner = second_bus.connection();
        let (second_backend, _) = old_native_backend(&second_bus, &second_owner);
        assert_eq!(owner.unique_name(), second_owner.unique_name());
        assert_ne!(
            serde_json::to_value(backend.reconciliation().unwrap()).unwrap()["native_owner"],
            serde_json::to_value(second_backend.reconciliation().unwrap()).unwrap()["native_owner"],
            "unique names reused across bus lifetimes must not share cleanup identity"
        );
        let expected = serde_json::to_value(backend.reconciliation().unwrap()).unwrap()
            ["native_owner"]
            .clone();
        assert!(expected
            .as_str()
            .is_some_and(|token| token.contains(owner.unique_name().unwrap().as_str())));
        let fact = serde_json::to_value(backend.reconciliation().unwrap()).unwrap();
        assert_eq!(
            fact["native_owner"], expected,
            "cleanup proof lacks native owner"
        );
        backend.invalidate_service_owner();
        let invalid = serde_json::to_value(backend.reconciliation().unwrap()).unwrap();
        assert_eq!(invalid["native_owner"], expected);
        assert_eq!(invalid["native_calls_quiescent"], false);
        struct SnapshotBackend(ModemManagerVoice);
        impl GsmBackend for SnapshotBackend {
            fn refresh(&mut self) -> Result<GsmCallState> {
                Ok(GsmCallState::default())
            }
            fn reconciliation(&self) -> Option<GsmReconciliation> {
                self.0.reconciliation()
            }
            fn drain_call_events(&mut self) -> Vec<CallManagerWireEvent> {
                self.0.drain_call_events()
            }
            fn dial(&mut self, _: &str) -> Result<()> {
                Ok(())
            }
            fn hangup(&mut self) -> Result<()> {
                Ok(())
            }
            fn mute(&mut self, _: bool) -> Result<()> {
                Ok(())
            }
        }
        let worker = GsmWorker::with_backend(SnapshotBackend(backend));
        assert!(
            matches!(
                worker.events.recv_timeout(Duration::from_secs(3)).unwrap(),
                GsmEvent::Reconciled(_)
            ),
            "session event preceded native owner fact"
        );
        assert!(matches!(
            worker.events.recv_timeout(Duration::from_secs(3)).unwrap(),
            GsmEvent::Call(_)
        ));
    }

    #[test]
    fn gsm_terminal_cleanup_keeps_release_fact_when_object_deletion_fails() {
        use yoyopod_protocol::call::{CallDirection, CallTransport};
        let key = SessionKey {
            transport: CallTransport::Gsm,
            generation: 7,
            call_id: "runtime-outgoing-1".into(),
        };
        let mut backend = ModemManagerVoice::default();
        backend.configure(7, None).unwrap();
        backend
            .registry
            .as_mut()
            .unwrap()
            .register_outgoing(&key, "/call/A")
            .unwrap();
        backend.owner = Some(key.clone());
        let events = backend.registry.as_mut().unwrap().observe(
            "/call/A",
            CallDirection::Outgoing,
            CallPhase::Ended,
            "+49123456789",
        );
        assert!(backend
            .finish_terminal(&key, events, || anyhow::bail!("D-Bus DeleteCall failed"))
            .is_err());
        assert!(!backend.owns_voice(&key));
        assert!(backend.pending_events.iter().any(|event| matches!(event, CallManagerWireEvent::Update(update) if update.phase == CallPhase::Ended && update.key == key)), "terminal fact was lost before data lease could release");
        assert_eq!(backend.registry().unwrap().path_for(&key), Some("/call/A"));
    }

    #[test]
    fn gsm_synthetic_terminal_after_failed_hangup_and_restart_is_not_cleanup_proof() {
        let mut evidence = CleanupEvidence::default();
        evidence.failed("/call/A");
        assert!(!evidence.terminal_is_trusted("/call/A"));
        let mut restarted = CleanupEvidence::default();
        restarted.observe_initial("/call/A", &CallPhase::Ended);
        assert!(
            !restarted.terminal_is_trusted("/call/A"),
            "restart forgot that native termination was unproven"
        );
        restarted.confirmed("/call/A");
        assert!(restarted.terminal_is_trusted("/call/A"));
    }

    #[test]
    fn gsm_targeted_result_waits_for_backend_execution_and_busy_preserves_owner_audio() {
        use crate::gsm_calls::GsmCallRegistry;
        use yoyopod_protocol::call::{CallAction, CallDirection, RejectReason};
        struct SessionBackend {
            registry: GsmCallRegistry,
            release: Receiver<()>,
            started: Sender<()>,
            targeted: Arc<Mutex<Vec<String>>>,
            owner_path: String,
        }
        impl GsmBackend for SessionBackend {
            fn refresh(&mut self) -> Result<GsmCallState> {
                Ok(GsmCallState {
                    state: "active".into(),
                    available: true,
                    ..Default::default()
                })
            }
            fn dial(&mut self, _: &str) -> Result<()> {
                bail!("unused")
            }
            fn hangup(&mut self) -> Result<()> {
                Ok(())
            }
            fn mute(&mut self, _: bool) -> Result<()> {
                Ok(())
            }
            fn apply_call(&mut self, command: &CallCommand) -> Result<()> {
                let path = self
                    .registry
                    .path_for(&command.key)
                    .context("Unknown session")?
                    .to_string();
                self.started.send(())?;
                self.release.recv_timeout(Duration::from_secs(3))?;
                self.targeted.lock().unwrap().push(path.clone());
                // The modem boundary rejects B, leaving A's PCM ownership intact.
                anyhow::ensure!(path != self.owner_path, "owner audio would be stopped");
                Ok(())
            }
        }
        let mut registry = GsmCallRegistry::new(7);
        registry.observe(
            "/call/A",
            CallDirection::Outgoing,
            CallPhase::Active,
            "+49123456789",
        );
        let b = registry.observe(
            "/call/B",
            CallDirection::Incoming,
            CallPhase::Ringing,
            "+49123456789",
        );
        let CallManagerWireEvent::Offer(b) = &b[0] else {
            panic!("offer")
        };
        let key = b.key.clone();
        let (release_tx, release) = mpsc::channel();
        let (started, started_rx) = mpsc::channel();
        let targeted = Arc::new(Mutex::new(Vec::new()));
        let worker = GsmWorker::with_backend(SessionBackend {
            registry,
            release,
            started,
            targeted: targeted.clone(),
            owner_path: "/call/A".into(),
        });
        worker
            .send(GsmCommand::Action {
                request_id: "reject-B".into(),
                command: CallCommand {
                    key: key.clone(),
                    action: CallAction::Reject(RejectReason::Busy),
                },
            })
            .unwrap();
        started_rx
            .recv_timeout(Duration::from_secs(2))
            .expect("backend executes typed action");
        assert!(
            worker.drain_events().is_empty(),
            "enqueue is not completion"
        );
        release_tx.send(()).unwrap();
        match worker.events.recv_timeout(Duration::from_secs(2)).unwrap() {
            GsmEvent::Completed {
                request_id,
                key: completed_key,
                error,
                ..
            } => {
                assert_eq!(request_id, "reject-B");
                assert_eq!(completed_key, key);
                assert!(error.is_none());
            }
            other => panic!("unexpected event {other:?}"),
        }
        assert_eq!(*targeted.lock().unwrap(), ["/call/B"]);
    }

    #[test]
    fn gsm_isolation_requires_pinned_qmi_control_port_and_simtech_backend() {
        let ports = vec![("cdc-wdm0".into(), 6), ("ttyUSB2".into(), 3)];
        assert!(isolated_voice_backend(
            "1.24.0", "SIM7600", "simtech", "cdc-wdm0", &ports
        ));
        for (version, model, plugin, primary) in [
            ("1.24.0", "SIM7600", "simtech", "ttyUSB2"),
            ("1.24.0", "SIM7600", "generic", "cdc-wdm0"),
            ("1.24.0", "Unknown", "simtech", "cdc-wdm0"),
            ("1.22.0", "SIM7600", "simtech", "cdc-wdm0"),
        ] {
            assert!(!isolated_voice_backend(
                version, model, plugin, primary, &ports
            ));
        }
        assert!(!isolated_voice_backend(
            "1.24.0",
            "SIM7600",
            "simtech",
            "cdc-wdm0",
            &[]
        ));
    }

    #[test]
    fn gsm_waiting_and_held_are_not_active_audio_states() {
        assert_eq!(modem_call_phase(3), CallPhase::Ringing);
        assert_eq!(modem_call_phase(4), CallPhase::Active);
        assert_eq!(modem_call_phase(5), CallPhase::Held);
        assert_eq!(modem_call_phase(6), CallPhase::Waiting);
        assert_eq!(modem_call_phase(7), CallPhase::Ended);
    }

    #[test]
    fn registered_voice_remains_usable_after_primary_pin_unlock_with_pin2_restrictions() {
        // The SIM7600 on the Pi reports REGISTERED (8), SIM_PIN2 (3),
        // and EmergencyOnly=false immediately after a successful SendPin.
        assert_eq!(voice_service_unavailable_reason(8, 3, true, false), None);
        // A blocked secondary PIN still leaves ordinary voice operational.
        assert_eq!(voice_service_unavailable_reason(8, 5, true, false), None);
        assert_eq!(voice_service_unavailable_reason(8, 1, true, false), None);
    }

    #[test]
    fn secondary_pin_restrictions_do_not_bypass_voice_registration_requirements() {
        assert_eq!(
            voice_service_unavailable_reason(7, 3, true, false),
            Some("No mobile service")
        );
        assert_eq!(
            voice_service_unavailable_reason(8, 3, true, true),
            Some("No mobile service")
        );
        assert_eq!(
            voice_service_unavailable_reason(8, 5, false, false),
            Some("No voice service")
        );
    }

    #[test]
    fn primary_pin_puk_and_carrier_locks_still_block_voice() {
        for lock in [0, 2, 4, 6, 8, 16] {
            assert_eq!(
                voice_service_unavailable_reason(8, lock, true, false),
                Some("SIM locked"),
                "MMModemLock {lock}"
            );
        }
    }

    struct FakeBackend {
        state: GsmCallState,
        calls: Arc<Mutex<Vec<String>>>,
        fail_dial: bool,
    }

    impl GsmBackend for FakeBackend {
        fn refresh(&mut self) -> Result<GsmCallState> {
            Ok(self.state.clone())
        }
        fn dial(&mut self, number: &str) -> Result<()> {
            self.calls.lock().unwrap().push(format!("dial:{number}"));
            if self.fail_dial {
                bail!("modem rejected call");
            }
            self.state.state = "active".into();
            self.state.peer_number = number.into();
            Ok(())
        }
        fn hangup(&mut self) -> Result<()> {
            self.calls.lock().unwrap().push("hangup".into());
            self.state.state = "idle".into();
            Ok(())
        }
        fn mute(&mut self, muted: bool) -> Result<()> {
            self.calls.lock().unwrap().push(format!("mute:{muted}"));
            self.state.muted = muted;
            Ok(())
        }
    }

    fn next_state(worker: &GsmWorker) -> GsmCallState {
        worker.states.recv_timeout(Duration::from_secs(2)).unwrap()
    }

    #[test]
    fn worker_routes_normalized_calls_mute_hangup_and_shutdown_cleanup() {
        let calls = Arc::new(Mutex::new(Vec::new()));
        let worker = GsmWorker::with_backend(FakeBackend {
            calls: calls.clone(),
            fail_dial: false,
            state: GsmCallState {
                available: true,
                unavailable_reason: String::new(),
                ..GsmCallState::default()
            },
        });
        worker
            .send(GsmCommand::Dial("+49 (123) 456-789".into()))
            .unwrap();
        assert_eq!(next_state(&worker).state, "outgoing");
        assert_eq!(next_state(&worker).peer_number, "+49123456789");
        worker.send(GsmCommand::Mute(true)).unwrap();
        assert!(next_state(&worker).muted);
        worker.send(GsmCommand::Hangup).unwrap();
        assert_eq!(next_state(&worker).state, "idle");
        drop(worker);
        assert_eq!(
            *calls.lock().unwrap(),
            ["dial:+49123456789", "mute:true", "hangup", "hangup"]
        );
    }

    #[test]
    fn failed_or_invalid_dial_reports_error_and_releases_the_call() {
        for number in ["+49123456789", "+49123456789;ATH"] {
            let calls = Arc::new(Mutex::new(Vec::new()));
            let worker = GsmWorker::with_backend(FakeBackend {
                calls: calls.clone(),
                fail_dial: true,
                state: GsmCallState::default(),
            });
            worker.send(GsmCommand::Dial(number.into())).unwrap();
            assert_eq!(next_state(&worker).state, "error");
            // A retry with the same failure must still acknowledge the dial,
            // allowing the data runtime to release its pending voice pause.
            worker.send(GsmCommand::Dial(number.into())).unwrap();
            assert_eq!(next_state(&worker).state, "error");
            drop(worker);
            let calls = calls.lock().unwrap();
            assert!(calls.iter().any(|call| call == "hangup"));
            assert_eq!(
                calls
                    .iter()
                    .filter(|call| call.starts_with("dial:"))
                    .count(),
                2 * usize::from(!number.contains(';'))
            );
        }
    }

    #[test]
    fn numbers_are_normalized_without_allowing_dial_control_or_service_codes() {
        assert_eq!(
            normalize_phone_number("+49 (123) 456-789").unwrap(),
            "+49123456789"
        );
        for number in [
            "+491234567;ATH",
            "112",
            "*123#",
            "+49\rAT",
            "++491234567",
            "1234567890123456",
        ] {
            assert!(normalize_phone_number(number).is_err(), "{number}");
        }
    }
}
