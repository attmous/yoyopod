use std::collections::HashMap;
use std::sync::mpsc::{self, Receiver, Sender};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

use anyhow::{bail, Context, Result};
use serde::Serialize;
use zbus::blocking::{connection::Builder, Connection, Proxy};
use zbus::fdo::ManagedObjects;
use zvariant::{OwnedObjectPath, Value};

use crate::gsm_audio::UsbPcmAudio;

const DESTINATION: &str = "org.freedesktop.ModemManager1";
const MODEM_INTERFACE: &str = "org.freedesktop.ModemManager1.Modem";
const VOICE_INTERFACE: &str = "org.freedesktop.ModemManager1.Modem.Voice";
const CALL_INTERFACE: &str = "org.freedesktop.ModemManager1.Call";

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
    Dial(String),
    Hangup,
    Mute(bool),
    Stop,
}

/// ModemManager owns modem discovery and call control; the network worker never
/// competes with its QMI control channel or hard-codes a transient modem index.
pub trait GsmBackend: Send + 'static {
    fn refresh(&mut self) -> Result<GsmCallState>;
    fn dial(&mut self, number: &str) -> Result<()>;
    fn hangup(&mut self) -> Result<()>;
    fn mute(&mut self, muted: bool) -> Result<()>;
}

pub struct GsmWorker {
    commands: Sender<GsmCommand>,
    states: Receiver<GsmCallState>,
    thread: Option<JoinHandle<()>>,
}

impl GsmWorker {
    pub fn start() -> Self {
        Self::with_backend(ModemManagerVoice::default())
    }

    pub fn with_backend(mut backend: impl GsmBackend) -> Self {
        let (commands, receive_commands) = mpsc::channel();
        let (send_states, states) = mpsc::channel();
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
                    Err(mpsc::RecvTimeoutError::Timeout) => Ok(()),
                };
                let mut state = match backend.refresh() {
                    Ok(state) => state,
                    Err(error) => {
                        eprintln!("GSM state refresh failed: {error:#}");
                        let _ = backend.hangup();
                        GsmCallState {
                            state: "error".into(),
                            ..GsmCallState::default()
                        }
                    }
                };
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

#[derive(Default)]
struct ModemManagerVoice {
    connection: Option<Connection>,
    modem: Option<OwnedObjectPath>,
    call: Option<OwnedObjectPath>,
    peer_number: String,
    active_since: Option<Instant>,
    audio: Option<UsbPcmAudio>,
    cached: GsmCallState,
    next_discovery: Option<Instant>,
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
        let manager = Proxy::new(
            &connection,
            DESTINATION,
            "/org/freedesktop/ModemManager1",
            "org.freedesktop.DBus.ObjectManager",
        )?;
        let objects: ManagedObjects = manager.call("GetManagedObjects", &())?;
        self.modem = None;
        self.cached.available = false;
        self.cached.unavailable_reason = "No modem".into();
        let mut objects: Vec<_> = objects.into_iter().collect();
        objects.sort_by(|a, b| a.0.cmp(&b.0));
        for (path, interfaces) in objects {
            let Some(modem) = interfaces.get(MODEM_INTERFACE) else {
                continue;
            };
            let model = modem
                .get("Model")
                .and_then(|v| <&str>::try_from(v).ok())
                .unwrap_or_default();
            if !model.contains("SIM7600") {
                continue;
            }
            let state = modem
                .get("State")
                .and_then(|v| i32::try_from(v).ok())
                .unwrap_or(0);
            let unlock_required = modem
                .get("UnlockRequired")
                .and_then(|v| u32::try_from(v).ok())
                .unwrap_or(0);
            let voice = interfaces.get(VOICE_INTERFACE);
            let emergency_only = voice
                .and_then(|v| v.get("EmergencyOnly"))
                .and_then(|v| bool::try_from(v).ok())
                .unwrap_or(true);
            if matches!(unlock_required, 1 | 3 | 5) && matches!(state, 3 | 4) {
                let modem_proxy =
                    Proxy::new(&connection, DESTINATION, path.as_str(), MODEM_INTERFACE)?;
                let _: () = modem_proxy.call("Enable", &(true,))?;
            }
            let reason = voice_service_unavailable_reason(
                state,
                unlock_required,
                voice.is_some(),
                emergency_only,
            )
            .unwrap_or_else(|| {
                if UsbPcmAudio::available() {
                    ""
                } else {
                    "Audio unavailable"
                }
            });
            self.cached.available = reason.is_empty();
            self.cached.unavailable_reason = reason.into();
            self.modem = Some(path);
            break;
        }
        self.next_discovery = Some(Instant::now() + Duration::from_secs(3));
        Ok(())
    }

    fn call_proxy(&self) -> Result<Proxy<'_>> {
        let connection = self.connection.as_ref().context("No modem connection")?;
        let call = self.call.as_ref().context("No GSM call")?;
        Ok(Proxy::new(
            connection,
            DESTINATION,
            call.as_str(),
            CALL_INTERFACE,
        )?)
    }

    fn delete_call(&mut self) -> Result<()> {
        if let (Some(connection), Some(modem), Some(call)) =
            (&self.connection, &self.modem, self.call.as_ref())
        {
            let voice = Proxy::new(connection, DESTINATION, modem.as_str(), VOICE_INTERFACE)?;
            let _: () = voice.call("DeleteCall", &(call,))?;
        }
        self.call = None;
        self.audio.take();
        self.active_since = None;
        self.peer_number.clear();
        self.cached.state = "idle".into();
        self.cached.peer_number.clear();
        self.cached.duration_seconds = 0;
        self.cached.muted = false;
        Ok(())
    }
}

impl GsmBackend for ModemManagerVoice {
    fn refresh(&mut self) -> Result<GsmCallState> {
        if self
            .next_discovery
            .is_none_or(|next| Instant::now() >= next)
            && self.call.is_none()
        {
            if let Err(error) = self.discover() {
                self.connection = None;
                self.cached.available = false;
                self.cached.unavailable_reason = "Unavailable".into();
                self.next_discovery = Some(Instant::now() + Duration::from_secs(3));
                return Err(error);
            }
        }
        if self.call.is_some() {
            let state: i32 = self.call_proxy()?.get_property("State")?;
            match state {
                1 | 2 => self.cached.state = "outgoing".into(),
                4 | 5 => {
                    if self.audio.is_none() {
                        self.audio = Some(UsbPcmAudio::start()?);
                    }
                    if !self.audio.as_mut().expect("audio started").healthy()? {
                        bail!("GSM call audio stopped");
                    }
                    let since = self.active_since.get_or_insert_with(Instant::now);
                    self.cached.duration_seconds = since.elapsed().as_secs();
                    self.cached.state = "active".into();
                }
                7 => {
                    self.audio.take();
                    self.delete_call()?;
                }
                _ => {}
            }
        }
        Ok(self.cached.clone())
    }

    fn dial(&mut self, number: &str) -> Result<()> {
        if self.call.is_some() {
            bail!("A GSM call is already in progress");
        }
        self.discover()?;
        if !self.cached.available {
            bail!("{}", self.cached.unavailable_reason);
        }
        let connection = self.connection.as_ref().context("No modem")?.clone();
        let modem = self.modem.as_ref().context("No modem")?.clone();
        let voice = Proxy::new(&connection, DESTINATION, modem.as_str(), VOICE_INTERFACE)?;
        let properties = HashMap::from([("number", Value::from(number))]);
        let path: OwnedObjectPath = voice.call("CreateCall", &(properties,))?;
        drop(voice);
        self.call = Some(path);
        let result = (|| -> Result<()> {
            self.call_proxy()?.call::<_, _, ()>("Start", &())?;
            Ok(())
        })();
        if let Err(error) = result {
            let _ = self.delete_call();
            return Err(error);
        }
        self.peer_number = number.to_string();
        self.cached.peer_number = number.to_string();
        self.cached.state = "outgoing".into();
        self.cached.muted = false;
        self.cached.duration_seconds = 0;
        Ok(())
    }

    fn hangup(&mut self) -> Result<()> {
        if self.call.is_some() {
            let result = self.call_proxy()?.call::<_, _, ()>("Hangup", &());
            // A remotely ended call may already reject Hangup. Keep the call
            // tracked on other failures so the next poll can retry cleanup.
            if let Err(error) = result {
                let state: i32 = self.call_proxy()?.get_property("State")?;
                if state != 7 {
                    return Err(error.into());
                }
            }
            self.audio.take();
            self.delete_call()?;
        }
        Ok(())
    }

    fn mute(&mut self, muted: bool) -> Result<()> {
        self.audio
            .as_ref()
            .context("No GSM call audio")?
            .set_mute(muted);
        self.cached.muted = muted;
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::{Arc, Mutex};

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
