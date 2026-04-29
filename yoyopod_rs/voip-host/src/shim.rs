use crate::config::VoipConfig;
use crate::host::{BackendEvent, CallBackend, MessageRecord};
use libloading::Library;
use std::env;
use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int};
use std::path::{Path, PathBuf};
use thiserror::Error;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct NativeEvent {
    pub event_type: i32,
    pub registration_state: i32,
    pub call_state: i32,
    pub message_kind: i32,
    pub message_direction: i32,
    pub message_delivery_state: i32,
    pub duration_ms: i32,
    pub unread: i32,
    pub message_id: [c_char; 128],
    pub peer_sip_address: [c_char; 256],
    pub sender_sip_address: [c_char; 256],
    pub recipient_sip_address: [c_char; 256],
    pub local_file_path: [c_char; 512],
    pub mime_type: [c_char; 128],
    pub text: [c_char; 1024],
    pub reason: [c_char; 256],
}

impl Default for NativeEvent {
    fn default() -> Self {
        unsafe { std::mem::zeroed() }
    }
}

#[derive(Debug, Error)]
pub enum ShimError {
    #[error("liblinphone shim path could not be resolved")]
    NotFound,
    #[error("liblinphone shim load failed: {0}")]
    Load(String),
    #[error("liblinphone shim call failed: {0}")]
    Call(String),
    #[error("string contains interior NUL: {0}")]
    InvalidCString(#[from] std::ffi::NulError),
}

type InitFn = unsafe extern "C" fn() -> c_int;
type ShutdownFn = unsafe extern "C" fn();
type StopFn = unsafe extern "C" fn();
type IterateFn = unsafe extern "C" fn();
type PollEventFn = unsafe extern "C" fn(*mut NativeEvent) -> c_int;
type StartFn = unsafe extern "C" fn(
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    i32,
    *const c_char,
    *const c_char,
    *const c_char,
    *const c_char,
    i32,
    i32,
    i32,
    *const c_char,
) -> c_int;
type SimpleCallFn = unsafe extern "C" fn() -> c_int;
type MakeCallFn = unsafe extern "C" fn(*const c_char) -> c_int;
type SetMutedFn = unsafe extern "C" fn(i32) -> c_int;
type SendTextMessageFn =
    unsafe extern "C" fn(*const c_char, *const c_char, *mut c_char, u32) -> c_int;
type StartVoiceRecordingFn = unsafe extern "C" fn(*const c_char) -> c_int;
type StopVoiceRecordingFn = unsafe extern "C" fn(*mut i32) -> c_int;
type SendVoiceNoteFn = unsafe extern "C" fn(
    *const c_char,
    *const c_char,
    i32,
    *const c_char,
    *mut c_char,
    u32,
) -> c_int;
type LastErrorFn = unsafe extern "C" fn() -> *const c_char;

pub struct LiblinphoneShim {
    _library: Library,
    init: InitFn,
    shutdown: ShutdownFn,
    start: StartFn,
    stop: StopFn,
    iterate: IterateFn,
    poll_event: PollEventFn,
    make_call: MakeCallFn,
    answer_call: SimpleCallFn,
    reject_call: SimpleCallFn,
    hangup: SimpleCallFn,
    set_muted: SetMutedFn,
    send_text_message: SendTextMessageFn,
    start_voice_recording: StartVoiceRecordingFn,
    stop_voice_recording: StopVoiceRecordingFn,
    cancel_voice_recording: SimpleCallFn,
    send_voice_note: SendVoiceNoteFn,
    last_error: LastErrorFn,
}

pub struct ShimBackend {
    shim: LiblinphoneShim,
    next_outgoing_call_id: u64,
}

pub struct StartAudioSettings {
    pub audio_enabled: c_int,
    pub mic_gain: c_int,
    pub output_volume: c_int,
}

impl StartAudioSettings {
    pub fn from_config(config: &VoipConfig) -> Self {
        Self {
            audio_enabled: 1,
            mic_gain: config.mic_gain,
            output_volume: config.output_volume,
        }
    }
}

pub fn resolve_shim_path(explicit_path: Option<&str>) -> Result<PathBuf, ShimError> {
    if let Some(path) = explicit_path.filter(|value| !value.trim().is_empty()) {
        return Ok(PathBuf::from(path));
    }
    if let Ok(path) = env::var("YOYOPOD_LIBLINPHONE_SHIM_PATH") {
        if !path.trim().is_empty() {
            return Ok(PathBuf::from(path));
        }
    }
    let repo_candidate = Path::new("yoyopod")
        .join("backends")
        .join("voip")
        .join("shim_native")
        .join("build")
        .join(shim_file_name());
    if repo_candidate.exists() {
        return Ok(repo_candidate);
    }
    Err(ShimError::NotFound)
}

fn shim_file_name() -> &'static str {
    if cfg!(target_os = "windows") {
        "yoyopod_liblinphone_shim.dll"
    } else if cfg!(target_os = "macos") {
        "libyoyopod_liblinphone_shim.dylib"
    } else {
        "libyoyopod_liblinphone_shim.so"
    }
}

impl LiblinphoneShim {
    pub unsafe fn load(path: &Path) -> Result<Self, ShimError> {
        let library =
            unsafe { Library::new(path) }.map_err(|error| ShimError::Load(error.to_string()))?;
        unsafe fn symbol<T: Copy>(library: &Library, name: &[u8]) -> Result<T, ShimError> {
            let symbol = unsafe { library.get::<T>(name) }
                .map_err(|error| ShimError::Load(error.to_string()))?;
            Ok(*symbol)
        }
        Ok(Self {
            init: unsafe { symbol(&library, b"yoyopod_liblinphone_init\0") }?,
            shutdown: unsafe { symbol(&library, b"yoyopod_liblinphone_shutdown\0") }?,
            start: unsafe { symbol(&library, b"yoyopod_liblinphone_start\0") }?,
            stop: unsafe { symbol(&library, b"yoyopod_liblinphone_stop\0") }?,
            iterate: unsafe { symbol(&library, b"yoyopod_liblinphone_iterate\0") }?,
            poll_event: unsafe { symbol(&library, b"yoyopod_liblinphone_poll_event\0") }?,
            make_call: unsafe { symbol(&library, b"yoyopod_liblinphone_make_call\0") }?,
            answer_call: unsafe { symbol(&library, b"yoyopod_liblinphone_answer_call\0") }?,
            reject_call: unsafe { symbol(&library, b"yoyopod_liblinphone_reject_call\0") }?,
            hangup: unsafe { symbol(&library, b"yoyopod_liblinphone_hangup\0") }?,
            set_muted: unsafe { symbol(&library, b"yoyopod_liblinphone_set_muted\0") }?,
            send_text_message: unsafe {
                symbol(&library, b"yoyopod_liblinphone_send_text_message\0")
            }?,
            start_voice_recording: unsafe {
                symbol(&library, b"yoyopod_liblinphone_start_voice_recording\0")
            }?,
            stop_voice_recording: unsafe {
                symbol(&library, b"yoyopod_liblinphone_stop_voice_recording\0")
            }?,
            cancel_voice_recording: unsafe {
                symbol(&library, b"yoyopod_liblinphone_cancel_voice_recording\0")
            }?,
            send_voice_note: unsafe { symbol(&library, b"yoyopod_liblinphone_send_voice_note\0") }?,
            last_error: unsafe { symbol(&library, b"yoyopod_liblinphone_last_error\0") }?,
            _library: library,
        })
    }

    pub fn init(&self) -> Result<(), ShimError> {
        self.check(unsafe { (self.init)() })
    }

    pub fn start(&self, config: &VoipConfig) -> Result<(), ShimError> {
        let sip_server = CString::new(config.sip_server.as_str())?;
        let sip_username = CString::new(config.sip_username.as_str())?;
        let sip_password = CString::new(config.sip_password.as_str())?;
        let sip_password_ha1 = CString::new(config.sip_password_ha1.as_str())?;
        let sip_identity = CString::new(config.sip_identity.as_str())?;
        let factory_config_path = CString::new(config.factory_config_path.as_str())?;
        let transport = CString::new(config.transport.as_str())?;
        let stun_server = CString::new(config.stun_server.as_str())?;
        let conference_factory_uri = CString::new(config.conference_factory_uri.as_str())?;
        let file_transfer_server_url = CString::new(config.file_transfer_server_url.as_str())?;
        let lime_server_url = CString::new(config.lime_server_url.as_str())?;
        let playback_dev_id = CString::new(config.playback_dev_id.as_str())?;
        let ringer_dev_id = CString::new(config.ringer_dev_id.as_str())?;
        let capture_dev_id = CString::new(config.capture_dev_id.as_str())?;
        let media_dev_id = CString::new(config.media_dev_id.as_str())?;
        let voice_note_store_dir = CString::new(config.voice_note_store_dir.as_str())?;
        let audio_settings = StartAudioSettings::from_config(config);

        self.check(unsafe {
            (self.start)(
                sip_server.as_ptr(),
                sip_username.as_ptr(),
                sip_password.as_ptr(),
                sip_password_ha1.as_ptr(),
                sip_identity.as_ptr(),
                factory_config_path.as_ptr(),
                transport.as_ptr(),
                stun_server.as_ptr(),
                conference_factory_uri.as_ptr(),
                file_transfer_server_url.as_ptr(),
                lime_server_url.as_ptr(),
                if config.auto_download_incoming_voice_recordings {
                    1
                } else {
                    0
                },
                playback_dev_id.as_ptr(),
                ringer_dev_id.as_ptr(),
                capture_dev_id.as_ptr(),
                media_dev_id.as_ptr(),
                audio_settings.audio_enabled,
                audio_settings.mic_gain,
                audio_settings.output_volume,
                voice_note_store_dir.as_ptr(),
            )
        })
    }

    pub fn shutdown(&self) {
        unsafe { (self.shutdown)() }
    }

    pub fn stop(&self) {
        unsafe { (self.stop)() }
    }

    pub fn iterate(&self) {
        unsafe { (self.iterate)() }
    }

    pub fn make_call(&self, sip_address: &str) -> Result<(), ShimError> {
        let sip_address = CString::new(sip_address)?;
        self.check(unsafe { (self.make_call)(sip_address.as_ptr()) })
    }

    pub fn answer_call(&self) -> Result<(), ShimError> {
        self.check(unsafe { (self.answer_call)() })
    }

    pub fn reject_call(&self) -> Result<(), ShimError> {
        self.check(unsafe { (self.reject_call)() })
    }

    pub fn hangup(&self) -> Result<(), ShimError> {
        self.check(unsafe { (self.hangup)() })
    }

    pub fn set_muted(&self, muted: bool) -> Result<(), ShimError> {
        self.check(unsafe { (self.set_muted)(if muted { 1 } else { 0 }) })
    }

    pub fn send_text_message(&self, sip_address: &str, text: &str) -> Result<String, ShimError> {
        let sip_address = CString::new(sip_address)?;
        let text = CString::new(text)?;
        let mut message_id = [0 as c_char; 128];
        self.check(unsafe {
            (self.send_text_message)(
                sip_address.as_ptr(),
                text.as_ptr(),
                message_id.as_mut_ptr(),
                message_id.len() as u32,
            )
        })?;
        Ok(c_string(&message_id))
    }

    pub fn start_voice_recording(&self, file_path: &str) -> Result<(), ShimError> {
        let file_path = CString::new(file_path)?;
        self.check(unsafe { (self.start_voice_recording)(file_path.as_ptr()) })
    }

    pub fn stop_voice_recording(&self) -> Result<i32, ShimError> {
        let mut duration_ms = 0;
        self.check(unsafe { (self.stop_voice_recording)(&mut duration_ms) })?;
        Ok(duration_ms)
    }

    pub fn cancel_voice_recording(&self) -> Result<(), ShimError> {
        self.check(unsafe { (self.cancel_voice_recording)() })
    }

    pub fn send_voice_note(
        &self,
        sip_address: &str,
        file_path: &str,
        duration_ms: i32,
        mime_type: &str,
    ) -> Result<String, ShimError> {
        let sip_address = CString::new(sip_address)?;
        let file_path = CString::new(file_path)?;
        let mime_type = CString::new(mime_type)?;
        let mut message_id = [0 as c_char; 128];
        self.check(unsafe {
            (self.send_voice_note)(
                sip_address.as_ptr(),
                file_path.as_ptr(),
                duration_ms,
                mime_type.as_ptr(),
                message_id.as_mut_ptr(),
                message_id.len() as u32,
            )
        })?;
        Ok(c_string(&message_id))
    }

    fn last_error(&self) -> String {
        unsafe {
            let raw = (self.last_error)();
            if raw.is_null() {
                return "unknown liblinphone shim error".to_string();
            }
            CStr::from_ptr(raw).to_string_lossy().into_owned()
        }
    }

    fn check(&self, code: c_int) -> Result<(), ShimError> {
        if code == 0 {
            Ok(())
        } else {
            Err(ShimError::Call(self.last_error()))
        }
    }

    pub fn drain_events(&self) -> Result<Vec<BackendEvent>, ShimError> {
        let mut events = Vec::new();
        loop {
            let mut event = NativeEvent::default();
            let has_event = unsafe { (self.poll_event)(&mut event as *mut NativeEvent) };
            if has_event == 0 {
                break;
            }
            if let Some(backend_event) = native_event_to_backend_event(&event) {
                events.push(backend_event);
            }
        }
        Ok(events)
    }
}

impl ShimBackend {
    pub unsafe fn load(path: &Path) -> Result<Self, ShimError> {
        Ok(Self {
            shim: unsafe { LiblinphoneShim::load(path) }?,
            next_outgoing_call_id: 1,
        })
    }
}

impl CallBackend for ShimBackend {
    fn start(&mut self, config: &VoipConfig) -> Result<(), String> {
        self.shim.init().map_err(|error| error.to_string())?;
        self.shim.start(config).map_err(|error| error.to_string())
    }

    fn stop(&mut self) {
        self.shim.stop();
        self.shim.shutdown();
    }

    fn iterate(&mut self) -> Result<Vec<BackendEvent>, String> {
        self.shim.iterate();
        self.shim.drain_events().map_err(|error| error.to_string())
    }

    fn make_call(&mut self, sip_address: &str) -> Result<String, String> {
        self.shim
            .make_call(sip_address)
            .map_err(|error| error.to_string())?;
        let call_id = format!("outgoing-{}", self.next_outgoing_call_id);
        self.next_outgoing_call_id += 1;
        Ok(call_id)
    }

    fn answer_call(&mut self) -> Result<(), String> {
        self.shim.answer_call().map_err(|error| error.to_string())
    }

    fn reject_call(&mut self) -> Result<(), String> {
        self.shim.reject_call().map_err(|error| error.to_string())
    }

    fn hangup(&mut self) -> Result<(), String> {
        self.shim.hangup().map_err(|error| error.to_string())
    }

    fn set_muted(&mut self, muted: bool) -> Result<(), String> {
        self.shim
            .set_muted(muted)
            .map_err(|error| error.to_string())
    }

    fn send_text_message(&mut self, sip_address: &str, text: &str) -> Result<String, String> {
        self.shim
            .send_text_message(sip_address, text)
            .map_err(|error| error.to_string())
    }

    fn start_voice_recording(&mut self, file_path: &str) -> Result<(), String> {
        self.shim
            .start_voice_recording(file_path)
            .map_err(|error| error.to_string())
    }

    fn stop_voice_recording(&mut self) -> Result<i32, String> {
        self.shim
            .stop_voice_recording()
            .map_err(|error| error.to_string())
    }

    fn cancel_voice_recording(&mut self) -> Result<(), String> {
        self.shim
            .cancel_voice_recording()
            .map_err(|error| error.to_string())
    }

    fn send_voice_note(
        &mut self,
        sip_address: &str,
        file_path: &str,
        duration_ms: i32,
        mime_type: &str,
    ) -> Result<String, String> {
        self.shim
            .send_voice_note(sip_address, file_path, duration_ms, mime_type)
            .map_err(|error| error.to_string())
    }
}

pub fn native_event_to_backend_event(event: &NativeEvent) -> Option<BackendEvent> {
    match event.event_type {
        1 => Some(BackendEvent::RegistrationChanged {
            state: crate::events::RegistrationState::from_native(event.registration_state)
                .as_protocol()
                .to_string(),
            reason: c_string(&event.reason),
        }),
        2 => Some(BackendEvent::CallStateChanged {
            call_id: c_string(&event.peer_sip_address),
            state: crate::events::CallState::from_native(event.call_state)
                .as_protocol()
                .to_string(),
        }),
        3 => Some(BackendEvent::IncomingCall {
            call_id: c_string(&event.peer_sip_address),
            from_uri: c_string(&event.peer_sip_address),
        }),
        4 => Some(BackendEvent::BackendStopped {
            reason: c_string(&event.reason),
        }),
        5 => Some(BackendEvent::MessageReceived {
            message: MessageRecord {
                message_id: c_string(&event.message_id),
                peer_sip_address: c_string(&event.peer_sip_address),
                sender_sip_address: c_string(&event.sender_sip_address),
                recipient_sip_address: c_string(&event.recipient_sip_address),
                kind: crate::events::MessageKind::from_native(event.message_kind)
                    .as_protocol()
                    .to_string(),
                direction: crate::events::MessageDirection::from_native(event.message_direction)
                    .as_protocol()
                    .to_string(),
                delivery_state: crate::events::MessageDeliveryState::from_native(
                    event.message_delivery_state,
                )
                .as_protocol()
                .to_string(),
                text: c_string(&event.text),
                local_file_path: c_string(&event.local_file_path),
                mime_type: c_string(&event.mime_type),
                duration_ms: event.duration_ms,
                unread: event.unread != 0,
            },
        }),
        6 => Some(BackendEvent::MessageDeliveryChanged {
            message_id: c_string(&event.message_id),
            delivery_state: crate::events::MessageDeliveryState::from_native(
                event.message_delivery_state,
            )
            .as_protocol()
            .to_string(),
            local_file_path: c_string(&event.local_file_path),
            error: c_string(&event.reason),
        }),
        7 => Some(BackendEvent::MessageDownloadCompleted {
            message_id: c_string(&event.message_id),
            local_file_path: c_string(&event.local_file_path),
            mime_type: c_string(&event.mime_type),
        }),
        8 => Some(BackendEvent::MessageFailed {
            message_id: c_string(&event.message_id),
            reason: c_string(&event.reason),
        }),
        _ => None,
    }
}

pub fn c_string<const N: usize>(buffer: &[c_char; N]) -> String {
    unsafe { CStr::from_ptr(buffer.as_ptr()) }
        .to_string_lossy()
        .into_owned()
}
