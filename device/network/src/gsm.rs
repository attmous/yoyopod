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
use zvariant::{OwnedObjectPath, Value};

use crate::gsm_audio::UsbPcmAudio;

const DESTINATION: &str = "org.freedesktop.ModemManager1";
const MODEM_INTERFACE: &str = "org.freedesktop.ModemManager1.Modem";
const VOICE_INTERFACE: &str = "org.freedesktop.ModemManager1.Modem.Voice";
const CALL_INTERFACE: &str = "org.freedesktop.ModemManager1.Call";

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
    fn dial_session(&mut self, _key: &SessionKey, _number: &str) -> Result<()> {
        bail!("Session dialing unavailable")
    }
    fn drain_call_events(&mut self) -> Vec<CallManagerWireEvent> {
        Vec::new()
    }
}

pub struct GsmWorker {
    commands: Sender<(u64, GsmCommand)>,
    selected_epoch: Arc<AtomicU64>,
    states: Receiver<GsmCallState>,
    events: Receiver<GsmEvent>,
    thread: Option<JoinHandle<()>>,
}

impl GsmWorker {
    pub fn start() -> Self {
        Self::with_backend(ModemManagerVoice::default())
    }

    pub fn with_backend(mut backend: impl GsmBackend) -> Self {
        let (commands, receive_commands) = mpsc::channel();
        let (send_states, states) = mpsc::channel();
        let (send_events, events) = mpsc::channel();
        let selected_epoch = Arc::new(AtomicU64::new(backend.selected_modem_epoch()));
        let thread_epoch = selected_epoch.clone();
        let thread = thread::spawn(move || {
            let mut previous = None;
            let mut previous_reconciliation = None;
            loop {
                let queued = receive_commands.recv_timeout(Duration::from_millis(500));
                // Observe removal before dispatch, including commands accepted while a
                // previous bounded native request was waiting for its response.
                let preflight = backend.refresh_observation();
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
                        let error = backend
                            .apply_call(&command)
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
                let mut call_events = Vec::new();
                if let Ok(observation) = preflight {
                    call_events.extend(observation.calls);
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
                    let _ = send_events.send(GsmEvent::Call(event));
                }
                // Loss and native facts must close the outer data barrier before
                // a keyed completion can decide whether its reservation releases.
                if let Some(completion) = completion {
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
        }
    }

    pub fn send(&self, command: GsmCommand) -> Result<()> {
        self.send_at_epoch(command, self.selected_epoch.load(Ordering::SeqCst))
    }
    pub(crate) fn admission_epoch(&self) -> u64 {
        self.selected_epoch.load(Ordering::SeqCst)
    }
    pub(crate) fn send_at_epoch(&self, command: GsmCommand, epoch: u64) -> Result<()> {
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
                    && message.header().member().map(|m| m.as_str()) == Some("InterfacesRemoved")
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

#[derive(Default)]
struct ModemManagerVoice {
    selected_epoch: u64,
    modem_lost: bool,
    loss_pending: bool,
    clean_rediscovery: bool,
    idle_calls_proven: bool,
    native_addition_revision: u64,
    initial_scan: bool,
    service_owner: Option<String>,
    service_bus_id: Option<String>,
    service_invalidated: bool,
    terminating: std::collections::HashSet<String>,
    connection: Option<Connection>,
    modem: Option<OwnedObjectPath>,
    signals: Option<ModemSignals>,
    registry: Option<crate::gsm_calls::GsmCallRegistry>,
    generation: Option<u64>,
    pcm_sample_rate_hz: Option<u32>,
    isolated: bool,
    pending_events: Vec<CallManagerWireEvent>,
    owner: Option<SessionKey>,
    prepared_audio: Option<crate::gsm_audio::PreparedUsbPcm>,
    audio: Option<UsbPcmAudio>,
    audio_deadline: Option<Instant>,
    active_since: Option<Instant>,
    cleanup: CleanupEvidence,
    cached: GsmCallState,
    next_discovery: Option<Instant>,
    next_recovery: Option<Instant>,
    // CreateCall timeout may create an object later. Retain the data lease and
    // associate the next previously unknown outgoing object only for cleanup.
    uncertain_create: Option<SessionKey>,
}

impl ModemManagerVoice {
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
        self.selected_epoch = self
            .selected_epoch
            .checked_add(1)
            .expect("modem epoch exhausted");
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
        if header.sender().map(|s| s.as_str()) == self.service_owner.as_deref()
            && header.path().map(|p| p.as_str()) == self.modem.as_ref().map(|p| p.as_str())
            && header.interface().map(|s| s.as_str()) == Some(VOICE_INTERFACE)
            && header.member().map(|s| s.as_str()) == Some("CallAdded")
        {
            // A new native object invalidates the previous idle proof even if
            // removal follows before the next Calls scan can observe its key.
            self.native_addition_revision = self
                .native_addition_revision
                .checked_add(1)
                .expect("native addition revision exhausted");
            self.idle_calls_proven = false;
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
        self.service_invalidated = true;
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
            self.selected_epoch = self
                .selected_epoch
                .checked_add(1)
                .expect("modem epoch exhausted");
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
        let addition_revision = self.native_addition_revision;
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
        // A newer addition consumed by the post-response checks makes this
        // Calls snapshot stale. Preserve its unresolved ownership evidence
        // until a fresh scan instead of certifying idle or deleting old keys.
        if self.native_addition_revision != addition_revision {
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
        if self.native_addition_revision != addition_revision {
            self.idle_calls_proven = false;
            return Ok(());
        }
        for (path, key) in old {
            if !paths.iter().any(|candidate| candidate.as_str() == path) {
                self.object_deleted(&path, &key);
            }
        }
        Ok(())
    }

    fn object_deleted(&mut self, path: &str, key: &SessionKey) {
        self.terminating.remove(path);
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
            self.audio_deadline = None;
            self.active_since = None;
            self.owner = None;
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
        self.cached.available = reason.is_none();
        self.cached.unavailable_reason = reason.unwrap_or_default().into();
        if !self.cleanup.uncertain.is_empty() || self.uncertain_create.is_some() {
            self.cached.available = false;
            self.cached.unavailable_reason = "GSM native call reconciliation required".into();
        }
        Ok(())
    }

    fn targeted_hangup(&mut self, key: &SessionKey) -> Result<()> {
        self.ensure_control()?;
        let path = self.path_for(key)?;
        self.terminating.insert(path.clone());
        if self.owner.as_ref() == Some(key) {
            self.audio.take();
            self.prepared_audio.take();
            self.audio_deadline = None;
        }
        let result = self.proxy_for(&path)?.call::<_, _, ()>("Hangup", &());
        self.ensure_control()?;
        match result {
            Ok(()) => {
                self.cleanup.confirmed(&path);
                Ok(())
            }
            Err(error) => {
                self.cleanup.failed(&path);
                Err(error.into())
            }
        }
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
        if self.initial_scan {
            self.cleanup.observe_initial(path, &phase);
        }
        if phase == CallPhase::Ended && !self.cleanup.terminal_is_trusted(path) {
            phase = CallPhase::Ending;
        }
        if direction == CallDirection::Outgoing {
            if let Some(key) = self.uncertain_create.clone() {
                if !self.registry()?.tracked().iter().any(|(p, _)| p == path) {
                    self.registry
                        .as_mut()
                        .expect("configured")
                        .register_outgoing(&key, path)?;
                    self.cleanup.failed(path);
                    self.uncertain_create = None;
                }
            }
        }
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

    fn sample_rate(&self, path: Option<&str>) -> Result<u32> {
        if let Some(rate) = self.pcm_sample_rate_hz {
            return Ok(rate);
        }
        if let Some(path) = path {
            let format: HashMap<String, zvariant::OwnedValue> =
                self.proxy_for(path)?.get_property("AudioFormat")?;
            let rate = format
                .get("rate")
                .and_then(|value| u32::try_from(value).ok());
            let encoding = format
                .get("encoding")
                .and_then(|v| <&str>::try_from(v).ok());
            let resolution = format
                .get("resolution")
                .and_then(|v| <&str>::try_from(v).ok());
            if encoding == Some("pcm") && resolution == Some("s16le") {
                if let Some(rate @ (8000 | 16000)) = rate {
                    return Ok(rate);
                }
            }
        }
        bail!("GSM audio format unavailable: configure verified gsm_pcm_sample_rate_hz")
    }

    fn start_owned_audio(&mut self, _key: &SessionKey, path: &str) -> Result<()> {
        if let Some(audio) = self.audio.as_mut() {
            anyhow::ensure!(audio.healthy()?, "GSM audio bridge stopped");
            return Ok(());
        }
        if self.prepared_audio.is_none() {
            let rate = self.sample_rate(Some(path))?;
            self.ensure_control()?;
            self.prepared_audio = Some(UsbPcmAudio::prepare(rate)?);
        }
        let audio_port: String = self.proxy_for(path)?.get_property("AudioPort")?;
        self.ensure_control()?;
        if audio_port.is_empty() {
            anyhow::ensure!(
                self.audio_deadline
                    .is_some_and(|deadline| Instant::now() < deadline),
                "Modem USB audio readiness timed out"
            );
            return Ok(());
        }
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
            std::fs::canonicalize(port)? == prepared.port,
            "Modem audio endpoint differs from prepared USB endpoint"
        );
        self.audio = Some(UsbPcmAudio::start(
            self.prepared_audio.take().expect("prepared"),
        )?);
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
        let mut reconcile = false;
        for message in messages {
            self.removal_signal(&message);
            if self.modem_lost {
                return Ok(self.cached.clone());
            }
            let header = message.header();
            if header.sender().map(|sender| sender.as_str()) != self.service_owner.as_deref() {
                continue;
            }
            match header.member().map(|member| member.as_str()) {
                Some("CallAdded" | "CallDeleted") => {
                    reconcile = true;
                }
                Some("PropertiesChanged" | "StateChanged") => {
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
                _ => {}
            }
        }
        // Bounded Calls-property recovery handles missed signals and bus bursts;
        // this is not global D-Bus enumeration. Tracked properties poll at 500ms.
        if reconcile || self.next_recovery.is_none_or(|next| Instant::now() >= next) {
            self.reconcile_paths()?;
            self.refresh_availability()?;
            self.next_recovery = Some(Instant::now() + Duration::from_secs(3));
        } else {
            for (path, _) in self.registry()?.tracked() {
                self.observe_path(&path)?;
            }
        }
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
            pcm_sample_rate_hz.is_none_or(|rate| matches!(rate, 8000 | 16000)),
            "Invalid GSM PCM sample rate"
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
        self.generation = Some(generation);
        self.pcm_sample_rate_hz = pcm_sample_rate_hz;
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
        self.ensure_control()?;
        anyhow::ensure!(self.cached.available, "{}", self.cached.unavailable_reason);
        // Reserve PCM without microphone/playback before starting the native call.
        let prepared = UsbPcmAudio::prepare(self.sample_rate(None)?)?;
        let connection = self.connection.as_ref().context("No modem")?.clone();
        let modem = self.modem.as_ref().context("No modem")?.clone();
        let native_owner = self.bound_owner()?.to_owned();
        let voice = Proxy::new(
            &connection,
            native_owner.as_str(),
            modem.as_str(),
            VOICE_INTERFACE,
        )?;
        self.owner = Some(key.clone());
        self.prepared_audio = Some(prepared);
        self.ensure_control()?;
        let properties = HashMap::from([("number", Value::from(number))]);
        let path: OwnedObjectPath = match voice.call("CreateCall", &(properties,)) {
            Ok(path) => path,
            Err(error) => {
                self.uncertain_create = Some(key.clone());
                self.ensure_control()?;
                return Err(error.into());
            }
        };
        self.registry
            .as_mut()
            .context("Not configured")?
            .register_outgoing(key, path.as_str())?;
        self.ensure_control()?;
        let events = self.registry.as_mut().expect("configured").observe(
            path.as_str(),
            yoyopod_protocol::call::CallDirection::Outgoing,
            CallPhase::Outgoing,
            number,
        );
        self.pending_events.extend(events);
        self.audio_deadline = Some(Instant::now() + Duration::from_secs(8));
        let start_result = self
            .proxy_for(path.as_str())?
            .call::<_, _, ()>("Start", &());
        self.ensure_control()?;
        if let Err(error) = start_result {
            self.cleanup.failed(path.as_str());
            return Err(error.into());
        }
        self.cached.state = "outgoing".into();
        self.cached.peer_number = number.into();
        Ok(())
    }

    fn apply_call(&mut self, command: &CallCommand) -> Result<()> {
        use yoyopod_protocol::call::CallAction;
        let path = self.path_for(&command.key)?;
        self.ensure_control()?;
        match command.action {
            CallAction::Answer => {
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
                let preparation = self.sample_rate(Some(&path)).and_then(|rate| {
                    self.ensure_control()?;
                    UsbPcmAudio::prepare(rate)
                });
                match preparation {
                    Ok(prepared) => self.prepared_audio = Some(prepared),
                    Err(error) => {
                        let _ = self.targeted_hangup(&command.key);
                        return Err(error);
                    }
                }
                self.audio_deadline = Some(Instant::now() + Duration::from_secs(8));
                self.ensure_control()?;
                let accept_result = self.proxy_for(&path)?.call::<_, _, ()>("Accept", &());
                self.ensure_control()?;
                if let Err(error) = accept_result {
                    self.cleanup.failed(&path);
                    return Err(error.into());
                }
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
        fn model(&self) -> &str {
            "SIM7600"
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
        gate: PropertyGate,
        fail: Arc<std::sync::atomic::AtomicBool>,
        paths: Arc<Mutex<Vec<OwnedObjectPath>>>,
    }
    #[zbus::interface(name = "org.freedesktop.ModemManager1.Modem.Voice")]
    impl ReconnectVoice {
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
                    gate: Arc::new(Mutex::new(None)),
                    fail: Arc::new(std::sync::atomic::AtomicBool::new(false)),
                    paths: Arc::new(Mutex::new(Vec::new())),
                },
            )
            .unwrap();
        allow_replacement(&owner);
        let mut backend = ModemManagerVoice::default();
        backend.configure(7, None).unwrap();
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
    fn add_reconnect_modem(owner: &Connection, path: &str) {
        owner.object_server().at(path, ReconnectModem).unwrap();
        owner
            .object_server()
            .at(
                path,
                ReconnectVoice {
                    reads: Arc::new(std::sync::atomic::AtomicUsize::new(0)),
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
        fail.store(true, Ordering::SeqCst);
        assert!(
            backend.refresh().is_err(),
            "stale snapshot discarded membership work instead of attempting a fresh scan"
        );
        assert!(!backend.modem_lost);
        fail.store(false, Ordering::SeqCst);
        backend.refresh().unwrap();
        assert!(backend.drain_call_events().iter().any(|event| matches!(event, CallManagerWireEvent::Offer(offer) if offer.address == "+49123456789")), "failed fresh observation discarded pending membership work");
        assert_eq!(backend.registry().unwrap().tracked().len(), 1);
        assert_eq!(backend.selected_epoch, 0);
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
