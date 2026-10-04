use std::collections::HashMap;
use std::sync::mpsc::{self, Receiver, Sender};
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

// Test-first capability scaffold: unknown backends are never trusted.
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

/// ModemManager owns modem discovery and call control; the network worker never
/// competes with its QMI control channel or hard-codes a transient modem index.
pub trait GsmBackend: Send + 'static {
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
    commands: Sender<GsmCommand>,
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
        let thread = thread::spawn(move || {
            let mut previous = None;
            loop {
                let command = receive_commands.recv_timeout(Duration::from_millis(500));
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
                        let _ = send_events.send(GsmEvent::Completed {
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
                        let _ = send_events.send(GsmEvent::Completed {
                            request_id,
                            key,
                            error,
                            voice_held,
                        });
                        Ok(())
                    }
                    Err(mpsc::RecvTimeoutError::Timeout) => Ok(()),
                };
                let mut state = match backend.refresh() {
                    Ok(state) => state,
                    Err(error) => {
                        eprintln!("GSM state refresh failed: {error:#}");
                        GsmCallState {
                            state: "error".into(),
                            ..GsmCallState::default()
                        }
                    }
                };
                for event in backend.drain_call_events() {
                    let _ = send_events.send(GsmEvent::Call(event));
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
            states,
            events,
            thread: Some(thread),
        }
    }

    pub fn send(&self, command: GsmCommand) -> Result<()> {
        self.commands
            .send(command)
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
        let _ = self.commands.send(GsmCommand::Stop);
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
    fn observe_initial(&mut self, _path: &str, _phase: &CallPhase) {}
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

struct ModemSignals {
    connection: Connection,
    messages: Receiver<zbus::Message>,
    thread: Option<JoinHandle<()>>,
}
impl ModemSignals {
    fn start() -> Result<Self> {
        let connection = Builder::system()?
            .method_timeout(Duration::from_secs(5))
            .build()?;
        let rule = zbus::MatchRule::builder()
            .msg_type(zbus::message::Type::Signal)
            .sender(DESTINATION)?
            .path_namespace("/org/freedesktop/ModemManager1")?
            .build();
        let mut stream =
            zbus::blocking::MessageIterator::for_match_rule(rule, &connection, Some(128))?;
        let (sender, messages) = mpsc::sync_channel(128);
        let thread = thread::spawn(move || {
            for message in &mut stream {
                let Ok(message) = message else { break };
                // Property storms cannot block shutdown. Tracked-object polling recovers
                // lost property changes; additions/deletions use the cached Calls property.
                if sender.try_send(message).is_err() {
                    break;
                }
            }
        });
        Ok(Self {
            connection,
            messages,
            thread: Some(thread),
        })
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
        if self.signals.is_none() {
            self.signals = Some(ModemSignals::start()?);
        }
        let manager = Proxy::new(
            &connection,
            DESTINATION,
            "/org/freedesktop/ModemManager1",
            "org.freedesktop.DBus.ObjectManager",
        )?;
        let objects: ManagedObjects = manager.call("GetManagedObjects", &())?;
        let version: String = Proxy::new(
            &connection,
            DESTINATION,
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
            let proxy = Proxy::new(&connection, DESTINATION, path.as_str(), MODEM_INTERFACE)?;
            let ports: Vec<(String, u32)> = proxy.get_property("Ports")?;
            drop(proxy);
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
            // Discovery enumerates once. The Voice Calls property and signals are
            // used afterwards; no repeated global managed-object enumeration.
            self.reconcile_paths()?;
            break;
        }
        self.next_discovery = Some(Instant::now() + Duration::from_secs(3));
        Ok(())
    }

    fn proxy_for(&self, path: &str) -> Result<Proxy<'_>> {
        Ok(Proxy::new(
            self.connection.as_ref().context("No modem connection")?,
            DESTINATION,
            path.to_owned(),
            CALL_INTERFACE,
        )?)
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
    fn ensure_control(&self) -> Result<()> {
        anyhow::ensure!(
            self.isolated,
            "Isolated GSM control unsupported; refusing unsafe modem fallback"
        );
        Ok(())
    }

    fn reconcile_paths(&mut self) -> Result<()> {
        let Some(modem) = self.modem.as_ref() else {
            return Ok(());
        };
        let voice = Proxy::new(
            self.connection.as_ref().context("No modem connection")?,
            DESTINATION,
            modem.as_str(),
            VOICE_INTERFACE,
        )?;
        let paths: Vec<OwnedObjectPath> = voice.get_property("Calls")?;
        drop(voice);
        let old = self.registry()?.tracked();
        for path in &paths {
            self.observe_path(path.as_str())?;
        }
        for (path, key) in old {
            if !paths.iter().any(|candidate| candidate.as_str() == path) {
                self.object_deleted(&path, &key);
            }
        }
        Ok(())
    }

    fn object_deleted(&mut self, path: &str, key: &SessionKey) {
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

    fn targeted_hangup(&mut self, key: &SessionKey) -> Result<()> {
        self.ensure_control()?;
        let path = self.path_for(key)?;
        let result = self.proxy_for(&path)?.call::<_, _, ()>("Hangup", &());
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
        let proxy = self.proxy_for(path)?;
        let state: i32 = proxy.get_property("State")?;
        let native_direction: i32 = proxy.get_property("Direction")?;
        let number: String = proxy.get_property("Number")?;
        drop(proxy);
        let direction = match native_direction {
            1 => CallDirection::Incoming,
            2 => CallDirection::Outgoing,
            _ => bail!("Unknown GSM call direction"),
        };
        let mut phase = modem_call_phase(state);
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
                CallPhase::Ended => {
                    self.release_audio(&key);
                    let modem = self.modem.as_ref().context("No modem")?;
                    let voice = Proxy::new(
                        self.connection.as_ref().context("No connection")?,
                        DESTINATION,
                        modem.as_str(),
                        VOICE_INTERFACE,
                    )?;
                    let object = OwnedObjectPath::try_from(path.to_owned())?;
                    let _: () = voice.call("DeleteCall", &(object,))?;
                    self.registry.as_mut().expect("configured").remove(&key);
                }
                _ => {}
            }
        } else if phase == CallPhase::Ended && self.cleanup.terminal_is_trusted(path) {
            let modem = self.modem.as_ref().context("No modem")?;
            let voice = Proxy::new(
                self.connection.as_ref().context("No connection")?,
                DESTINATION,
                modem.as_str(),
                VOICE_INTERFACE,
            )?;
            let object = OwnedObjectPath::try_from(path.to_owned())?;
            let _: () = voice.call("DeleteCall", &(object,))?;
            self.registry.as_mut().expect("configured").remove(&key);
        }
        self.pending_events.extend(events);
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
            self.prepared_audio = Some(UsbPcmAudio::prepare(self.sample_rate(Some(path))?)?);
        }
        let audio_port: String = self.proxy_for(path)?.get_property("AudioPort")?;
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

impl GsmBackend for ModemManagerVoice {
    fn configure(&mut self, generation: u64, pcm_sample_rate_hz: Option<u32>) -> Result<()> {
        anyhow::ensure!(
            pcm_sample_rate_hz.is_none_or(|rate| matches!(rate, 8000 | 16000)),
            "Invalid GSM PCM sample rate"
        );
        if let Some(current) = self.generation {
            anyhow::ensure!(
                generation > current
                    && self.registry()?.tracked().is_empty()
                    && self.owner.is_none(),
                "GSM generation change requires resolved sessions"
            );
        }
        self.generation = Some(generation);
        self.pcm_sample_rate_hz = pcm_sample_rate_hz;
        self.registry = Some(crate::gsm_calls::GsmCallRegistry::new(generation));
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
        let messages: Vec<_> = self
            .signals
            .as_ref()
            .map(|signals| signals.messages.try_iter().collect())
            .unwrap_or_default();
        let mut reconcile = false;
        for message in messages {
            let header = message.header();
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
            self.next_recovery = Some(Instant::now() + Duration::from_secs(3));
        } else {
            for (path, _) in self.registry()?.tracked() {
                self.observe_path(&path)?;
            }
        }
        Ok(self.cached.clone())
    }

    fn dial_session(&mut self, key: &SessionKey, number: &str) -> Result<()> {
        use yoyopod_protocol::call::CallTransport;
        anyhow::ensure!(
            key.transport == CallTransport::Gsm && Some(key.generation) == self.generation,
            "Unknown or stale GSM generation"
        );
        anyhow::ensure!(self.owner.is_none(), "GSM voice already owned");
        self.ensure_control()?;
        anyhow::ensure!(self.cached.available, "{}", self.cached.unavailable_reason);
        // Reserve PCM without microphone/playback before starting the native call.
        let prepared = UsbPcmAudio::prepare(self.sample_rate(None)?)?;
        let connection = self.connection.as_ref().context("No modem")?.clone();
        let modem = self.modem.as_ref().context("No modem")?.clone();
        let voice = Proxy::new(&connection, DESTINATION, modem.as_str(), VOICE_INTERFACE)?;
        self.owner = Some(key.clone());
        self.prepared_audio = Some(prepared);
        let properties = HashMap::from([("number", Value::from(number))]);
        let path: OwnedObjectPath = match voice.call("CreateCall", &(properties,)) {
            Ok(path) => path,
            Err(error) => {
                self.uncertain_create = Some(key.clone());
                return Err(error.into());
            }
        };
        self.registry
            .as_mut()
            .context("Not configured")?
            .register_outgoing(key, path.as_str())?;
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
                let update = self
                    .registry()?
                    .latest(&command.key)
                    .context("Unobserved call")?;
                anyhow::ensure!(
                    update.phase == CallPhase::Ringing,
                    "GSM call is not ringing"
                );
                self.owner = Some(command.key.clone());
                let preparation = self.sample_rate(Some(&path)).and_then(UsbPcmAudio::prepare);
                match preparation {
                    Ok(prepared) => self.prepared_audio = Some(prepared),
                    Err(error) => {
                        let _ = self.targeted_hangup(&command.key);
                        return Err(error);
                    }
                }
                self.audio_deadline = Some(Instant::now() + Duration::from_secs(8));
                let accept_result = self.proxy_for(&path)?.call::<_, _, ()>("Accept", &());
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
        let key = SessionKey {
            transport: yoyopod_protocol::call::CallTransport::Gsm,
            generation: self.generation.context("Not configured")?,
            call_id: uuid::Uuid::new_v4().to_string(),
        };
        self.dial_session(&key, number)
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
    fn gsm_synthetic_terminal_after_failed_hangup_and_restart_is_not_cleanup_proof() {
        let mut evidence = CleanupEvidence::default();
        evidence.failed("/call/A");
        assert!(!evidence.terminal_is_trusted("/call/A"));
        let mut restarted = CleanupEvidence::default();
        restarted.observe_initial("/call/A", &CallPhase::Ended);
        assert!(!restarted.terminal_is_trusted("/call/A"), "restart forgot that native termination was unproven");
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
