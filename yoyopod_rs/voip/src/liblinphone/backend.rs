use std::ffi::{CStr, CString};
use std::os::raw::{c_char, c_int};

use crate::config::VoipConfig;
use crate::host::{BackendEvent, MessageRecord, VoipRuntimeBackend};

use super::abi_event::{self, YoyopodLiblinphoneEvent};
use super::error::LiblinphoneError;
use super::runtime;

pub struct LiblinphoneBackend {
    next_outgoing_call_id: u64,
}

pub struct StartAudioSettings {
    pub audio_enabled: c_int,
    pub mic_gain: c_int,
    pub output_volume: c_int,
}

impl Default for LiblinphoneBackend {
    fn default() -> Self {
        Self::new()
    }
}

impl LiblinphoneBackend {
    pub fn new() -> Self {
        Self {
            next_outgoing_call_id: 1,
        }
    }

    fn init(&self) -> Result<(), LiblinphoneError> {
        check(unsafe { runtime::yoyopod_liblinphone_init() })
    }

    fn start_runtime(&self, config: &VoipConfig) -> Result<(), LiblinphoneError> {
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

        check(unsafe {
            runtime::yoyopod_liblinphone_start(
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

    fn drain_events(&self) -> Result<Vec<BackendEvent>, LiblinphoneError> {
        let mut events = Vec::new();
        loop {
            let mut event = YoyopodLiblinphoneEvent::default();
            let has_event =
                unsafe { runtime::yoyopod_liblinphone_poll_event(&mut event as *mut _) };
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

impl StartAudioSettings {
    pub fn from_config(config: &VoipConfig) -> Self {
        Self {
            audio_enabled: 1,
            mic_gain: config.mic_gain,
            output_volume: config.output_volume,
        }
    }
}

impl VoipRuntimeBackend for LiblinphoneBackend {
    fn start(&mut self, config: &VoipConfig) -> Result<(), String> {
        self.init().map_err(|error| error.to_string())?;
        self.start_runtime(config)
            .map_err(|error| error.to_string())
    }

    fn stop(&mut self) {
        unsafe {
            runtime::yoyopod_liblinphone_stop();
            runtime::yoyopod_liblinphone_shutdown();
        }
    }

    fn iterate(&mut self) -> Result<Vec<BackendEvent>, String> {
        unsafe { runtime::yoyopod_liblinphone_iterate() };
        self.drain_events().map_err(|error| error.to_string())
    }

    fn make_call(&mut self, sip_address: &str) -> Result<String, String> {
        let sip_address = CString::new(sip_address).map_err(|error| error.to_string())?;
        check(unsafe { runtime::yoyopod_liblinphone_make_call(sip_address.as_ptr()) })
            .map_err(|error| error.to_string())?;
        let call_id = format!("outgoing-{}", self.next_outgoing_call_id);
        self.next_outgoing_call_id += 1;
        Ok(call_id)
    }

    fn answer_call(&mut self) -> Result<(), String> {
        check(unsafe { runtime::yoyopod_liblinphone_answer_call() })
            .map_err(|error| error.to_string())
    }

    fn reject_call(&mut self) -> Result<(), String> {
        check(unsafe { runtime::yoyopod_liblinphone_reject_call() })
            .map_err(|error| error.to_string())
    }

    fn hangup(&mut self) -> Result<(), String> {
        check(unsafe { runtime::yoyopod_liblinphone_hangup() }).map_err(|error| error.to_string())
    }

    fn set_muted(&mut self, muted: bool) -> Result<(), String> {
        check(unsafe { runtime::yoyopod_liblinphone_set_muted(if muted { 1 } else { 0 }) })
            .map_err(|error| error.to_string())
    }

    fn send_text_message(&mut self, sip_address: &str, text: &str) -> Result<String, String> {
        let sip_address = CString::new(sip_address).map_err(|error| error.to_string())?;
        let text = CString::new(text).map_err(|error| error.to_string())?;
        let mut message_id = [0 as c_char; 128];
        check(unsafe {
            runtime::yoyopod_liblinphone_send_text_message(
                sip_address.as_ptr(),
                text.as_ptr(),
                message_id.as_mut_ptr(),
                message_id.len() as u32,
            )
        })
        .map_err(|error| error.to_string())?;
        Ok(c_string(&message_id))
    }

    fn start_voice_recording(&mut self, file_path: &str) -> Result<(), String> {
        let file_path = CString::new(file_path).map_err(|error| error.to_string())?;
        check(unsafe { runtime::yoyopod_liblinphone_start_voice_recording(file_path.as_ptr()) })
            .map_err(|error| error.to_string())
    }

    fn stop_voice_recording(&mut self) -> Result<i32, String> {
        let mut duration_ms = 0;
        check(unsafe { runtime::yoyopod_liblinphone_stop_voice_recording(&mut duration_ms) })
            .map_err(|error| error.to_string())?;
        Ok(duration_ms)
    }

    fn cancel_voice_recording(&mut self) -> Result<(), String> {
        check(unsafe { runtime::yoyopod_liblinphone_cancel_voice_recording() })
            .map_err(|error| error.to_string())
    }

    fn send_voice_note(
        &mut self,
        sip_address: &str,
        file_path: &str,
        duration_ms: i32,
        mime_type: &str,
    ) -> Result<String, String> {
        let sip_address = CString::new(sip_address).map_err(|error| error.to_string())?;
        let file_path = CString::new(file_path).map_err(|error| error.to_string())?;
        let mime_type = CString::new(mime_type).map_err(|error| error.to_string())?;
        let mut message_id = [0 as c_char; 128];
        check(unsafe {
            runtime::yoyopod_liblinphone_send_voice_note(
                sip_address.as_ptr(),
                file_path.as_ptr(),
                duration_ms,
                mime_type.as_ptr(),
                message_id.as_mut_ptr(),
                message_id.len() as u32,
            )
        })
        .map_err(|error| error.to_string())?;
        Ok(c_string(&message_id))
    }
}

pub fn native_event_to_backend_event(event: &YoyopodLiblinphoneEvent) -> Option<BackendEvent> {
    match event.event_type {
        abi_event::EVENT_REGISTRATION => Some(BackendEvent::RegistrationChanged {
            state: crate::events::RegistrationState::from_native(event.registration_state)
                .as_protocol()
                .to_string(),
            reason: c_string(&event.reason),
        }),
        abi_event::EVENT_CALL_STATE => Some(BackendEvent::CallStateChanged {
            call_id: c_string(&event.peer_sip_address),
            state: crate::events::CallState::from_native(event.call_state)
                .as_protocol()
                .to_string(),
        }),
        abi_event::EVENT_INCOMING_CALL => Some(BackendEvent::IncomingCall {
            call_id: c_string(&event.peer_sip_address),
            from_uri: c_string(&event.peer_sip_address),
        }),
        abi_event::EVENT_BACKEND_STOPPED => Some(BackendEvent::BackendStopped {
            reason: c_string(&event.reason),
        }),
        abi_event::EVENT_MESSAGE_RECEIVED => Some(BackendEvent::MessageReceived {
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
        abi_event::EVENT_MESSAGE_DELIVERY_CHANGED => Some(BackendEvent::MessageDeliveryChanged {
            message_id: c_string(&event.message_id),
            delivery_state: crate::events::MessageDeliveryState::from_native(
                event.message_delivery_state,
            )
            .as_protocol()
            .to_string(),
            local_file_path: c_string(&event.local_file_path),
            error: c_string(&event.reason),
        }),
        abi_event::EVENT_MESSAGE_DOWNLOAD_COMPLETED => {
            Some(BackendEvent::MessageDownloadCompleted {
                message_id: c_string(&event.message_id),
                local_file_path: c_string(&event.local_file_path),
                mime_type: c_string(&event.mime_type),
            })
        }
        abi_event::EVENT_MESSAGE_FAILED => Some(BackendEvent::MessageFailed {
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

fn check(code: c_int) -> Result<(), LiblinphoneError> {
    if code == 0 {
        Ok(())
    } else {
        Err(LiblinphoneError::Call(last_error()))
    }
}

fn last_error() -> String {
    unsafe {
        let raw = runtime::yoyopod_liblinphone_last_error();
        if raw.is_null() {
            return "unknown liblinphone error".to_string();
        }
        CStr::from_ptr(raw).to_string_lossy().into_owned()
    }
}
