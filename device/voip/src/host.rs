use crate::calls::CallSession;
use crate::config::VoipConfig;
use crate::history::CallHistoryStore;
use crate::lifecycle::LifecycleState;
use crate::message_store::MessageStore;
use crate::messages::{
    is_terminal_delivery_state, normalize_message_record, MessageSessionState, OutboundMessageIds,
};
use crate::playback::VoiceNotePlayback;
use crate::runtime_snapshot::RuntimeSnapshot;
use crate::voice_notes::VoiceNoteSession;
use serde_json::json;

pub use crate::lifecycle::LifecycleEvent;
pub use crate::messages::MessageRecord;

pub trait VoipRuntimeBackend {
    fn start(&mut self, config: &VoipConfig) -> Result<(), String>;
    fn stop(&mut self);
    fn iterate(&mut self) -> Result<Vec<BackendEvent>, String>;
    fn make_call(&mut self, sip_address: &str) -> Result<String, String>;
    fn answer_call(&mut self) -> Result<(), String>;
    fn reject_call(&mut self) -> Result<(), String>;
    fn hangup(&mut self) -> Result<(), String>;
    fn set_muted(&mut self, muted: bool) -> Result<(), String>;
    fn send_text_message(&mut self, sip_address: &str, text: &str) -> Result<String, String>;
    fn start_voice_recording(&mut self, file_path: &str) -> Result<(), String>;
    fn voice_recording_metrics(&mut self) -> Result<VoiceRecordingMetrics, String>;
    fn stop_voice_recording(&mut self) -> Result<i32, String>;
    fn cancel_voice_recording(&mut self) -> Result<(), String>;
    fn send_voice_note(
        &mut self,
        sip_address: &str,
        file_path: &str,
        duration_ms: i32,
        mime_type: &str,
    ) -> Result<String, String>;
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct VoiceRecordingMetrics {
    pub duration_ms: i32,
    pub capture_level_permille: i32,
}

const MAX_VOICE_NOTE_DURATION_MS: i32 = 60_000;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BackendEvent {
    RegistrationChanged {
        state: String,
        reason: String,
    },
    IncomingCall {
        call_id: String,
        from_uri: String,
    },
    CallStateChanged {
        call_id: String,
        state: String,
    },
    BackendStopped {
        reason: String,
    },
    MessageReceived {
        message: MessageRecord,
    },
    MessageDeliveryChanged {
        message_id: String,
        delivery_state: String,
        local_file_path: String,
        error: String,
    },
    MessageDownloadCompleted {
        message_id: String,
        local_file_path: String,
        mime_type: String,
    },
    MessageFailed {
        message_id: String,
        reason: String,
    },
}

#[derive(Debug)]
pub struct VoipHost {
    config: Option<VoipConfig>,
    backend_started: bool,
    registered: bool,
    registration_state: String,
    lifecycle: LifecycleState,
    call: CallSession,
    call_history: CallHistoryStore,
    voice_note_playback: VoiceNotePlayback,
    voice_note: VoiceNoteSession,
    message_store: MessageStore,
    last_message: Option<MessageSessionState>,
    outbound_message_ids: OutboundMessageIds,
}

impl Default for VoipHost {
    fn default() -> Self {
        Self {
            config: None,
            backend_started: false,
            registered: false,
            registration_state: "none".to_string(),
            lifecycle: LifecycleState::default(),
            call: CallSession::default(),
            call_history: CallHistoryStore::default(),
            voice_note_playback: VoiceNotePlayback::default(),
            voice_note: VoiceNoteSession::default(),
            message_store: MessageStore::default(),
            last_message: None,
            outbound_message_ids: OutboundMessageIds::default(),
        }
    }
}

impl VoipHost {
    pub fn configure(&mut self, config: VoipConfig) {
        self.message_store = MessageStore::open(&config.message_store_dir, 200);
        self.config = Some(config);
        self.backend_started = false;
        self.registered = false;
        self.registration_state = "none".to_string();
        self.lifecycle.clear_recovery_pending();
        self.lifecycle.record("configured", "configured", false);
        self.call.clear();
        self.voice_note_playback.stop();
        self.voice_note.reset();
        self.last_message = None;
        self.outbound_message_ids.clear();
    }

    pub fn mark_registered(&mut self, registered: bool) {
        self.registered = registered;
        self.registration_state = if registered { "ok" } else { "none" }.to_string();
        if registered {
            self.lifecycle.record("registered", "registered", false);
        }
    }

    pub fn set_active_call_id(&mut self, call_id: Option<String>) {
        self.call.set_active_call_id(call_id);
    }

    pub fn health_payload(&self) -> serde_json::Value {
        json!({
            "configured": self.config.is_some(),
            "registered": self.registered,
            "active_call_id": self.call.active_call_id(),
            "lifecycle_state": self.lifecycle.state(),
            "lifecycle_reason": self.lifecycle.reason(),
            "backend_available": self.lifecycle.backend_available(self.backend_started),
        })
    }

    pub fn lifecycle_payload(&self) -> serde_json::Value {
        self.lifecycle.payload(self.registered)
    }

    pub fn session_snapshot_payload(&self) -> serde_json::Value {
        RuntimeSnapshot {
            configured: self.config.is_some(),
            backend_started: self.backend_started,
            registered: self.registered,
            registration_state: &self.registration_state,
            lifecycle: &self.lifecycle,
            call: &self.call,
            call_history: &self.call_history,
            voice_note_playback: &self.voice_note_playback,
            voice_note: &self.voice_note,
            last_message: self.last_message.as_ref(),
            pending_outbound_messages: self.outbound_message_ids.len(),
            message_store: &self.message_store,
        }
        .payload()
    }

    pub fn iterate_interval_ms(&self) -> u64 {
        self.config
            .as_ref()
            .map(|config| config.iterate_interval_ms.max(1))
            .unwrap_or(20)
    }

    pub fn register<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
    ) -> Result<(), String> {
        let config = self
            .config
            .as_ref()
            .ok_or_else(|| "voip host is not configured".to_string())?
            .clone();
        let has_sip_account = config.has_sip_account();
        self.lifecycle.record(
            if has_sip_account {
                "registering"
            } else {
                "starting_local"
            },
            if has_sip_account {
                "registering"
            } else {
                "starting local voice-note backend"
            },
            false,
        );
        if let Err(error) = backend.start(&config) {
            self.backend_started = false;
            self.registered = false;
            self.registration_state = "failed".to_string();
            self.lifecycle.mark_recovery_pending();
            self.lifecycle.record("failed", &error, false);
            return Err(error);
        }
        self.backend_started = true;
        self.registered = false;
        self.registration_state = if has_sip_account { "progress" } else { "none" }.to_string();
        let recovered = self.lifecycle.recovery_pending();
        self.lifecycle.clear_recovery_pending();
        self.lifecycle.record(
            if has_sip_account {
                "started"
            } else {
                "local_ready"
            },
            if has_sip_account {
                "SIP backend started; awaiting registration"
            } else {
                "local voice-note backend ready"
            },
            recovered,
        );
        Ok(())
    }

    pub fn unregister<B: VoipRuntimeBackend + ?Sized>(&mut self, backend: &mut B) {
        backend.stop();
        self.backend_started = false;
        self.registered = false;
        self.registration_state = "none".to_string();
        self.lifecycle.clear_recovery_pending();
        self.lifecycle.record("stopped", "unregistered", false);
        self.call.clear();
        self.voice_note.reset();
        self.outbound_message_ids.clear();
    }

    pub fn dial<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
        sip_address: &str,
    ) -> Result<(), String> {
        let call_id = backend.make_call(sip_address)?;
        self.call.start_outgoing(&call_id, sip_address);
        Ok(())
    }

    pub fn answer<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
    ) -> Result<(), String> {
        backend.answer_call()
    }

    pub fn reject<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
    ) -> Result<(), String> {
        backend.reject_call()?;
        self.call.clear_with_state_and_action("released", "reject");
        Ok(())
    }

    pub fn hangup<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
    ) -> Result<(), String> {
        backend.hangup()?;
        self.call.clear_with_state_and_action("released", "hangup");
        Ok(())
    }

    pub fn set_muted<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
        muted: bool,
    ) -> Result<(), String> {
        backend.set_muted(muted)?;
        self.call.set_muted(muted);
        Ok(())
    }

    pub fn send_text_message<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
        sip_address: &str,
        text: &str,
        client_id: &str,
    ) -> Result<String, String> {
        let client_id = client_id.trim();
        if client_id.is_empty() {
            return Err("voip text message requires client_id".to_string());
        }
        let backend_id = backend.send_text_message(sip_address, text)?;
        self.outbound_message_ids
            .remember(&backend_id, client_id, "voip text message")?;
        let sender_sip_address = self.local_identity();
        if let Err(error) = self.message_store.upsert(MessageRecord {
            message_id: client_id.to_string(),
            peer_sip_address: sip_address.to_string(),
            sender_sip_address,
            recipient_sip_address: sip_address.to_string(),
            kind: "text".to_string(),
            direction: "outgoing".to_string(),
            delivery_state: "sending".to_string(),
            text: text.to_string(),
            local_file_path: String::new(),
            mime_type: String::new(),
            duration_ms: 0,
            unread: false,
        }) {
            eprintln!("failed to persist accepted outgoing VoIP text message: {error}");
        }
        Ok(client_id.to_string())
    }

    pub fn start_voice_recording<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
        file_path: &str,
    ) -> Result<(), String> {
        backend.start_voice_recording(file_path)?;
        self.voice_note.start_recording(file_path);
        Ok(())
    }

    pub fn stop_voice_recording<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
    ) -> Result<i32, String> {
        if let Some(duration_ms) = self.voice_note.recorded_duration_ms() {
            return Ok(duration_ms);
        }
        let duration_ms = backend.stop_voice_recording()?;
        self.voice_note.finish_recording(duration_ms);
        Ok(duration_ms)
    }

    pub fn refresh_voice_recording_metrics<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
    ) -> Result<bool, String> {
        if !self.voice_note.is_recording() {
            return Ok(false);
        }
        let metrics = backend.voice_recording_metrics()?;
        if voice_recording_limit_reached(metrics.duration_ms) {
            let duration_ms = backend.stop_voice_recording()?;
            self.voice_note.finish_recording(duration_ms);
            return Ok(true);
        }
        Ok(self
            .voice_note
            .update_recording_metrics(metrics.duration_ms, metrics.capture_level_permille))
    }

    pub fn cancel_voice_recording<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
    ) -> Result<(), String> {
        backend.cancel_voice_recording()?;
        self.voice_note.reset();
        Ok(())
    }

    pub fn send_voice_note<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
        sip_address: &str,
        file_path: &str,
        duration_ms: i32,
        mime_type: &str,
        client_id: &str,
    ) -> Result<String, String> {
        let client_id = client_id.trim();
        if client_id.is_empty() {
            return Err("voip voice note requires client_id".to_string());
        }
        let backend_id = backend.send_voice_note(sip_address, file_path, duration_ms, mime_type)?;
        self.outbound_message_ids
            .remember(&backend_id, client_id, "voip voice note")?;
        self.voice_note
            .start_sending(file_path, duration_ms, mime_type, client_id);
        let sender_sip_address = self.local_identity();
        if let Err(error) = self.message_store.upsert(MessageRecord {
            message_id: client_id.to_string(),
            peer_sip_address: sip_address.to_string(),
            sender_sip_address,
            recipient_sip_address: sip_address.to_string(),
            kind: "voice_note".to_string(),
            direction: "outgoing".to_string(),
            delivery_state: "sending".to_string(),
            text: String::new(),
            local_file_path: file_path.to_string(),
            mime_type: mime_type.to_string(),
            duration_ms,
            unread: false,
        }) {
            eprintln!("failed to persist accepted outgoing VoIP voice note: {error}");
        }
        Ok(client_id.to_string())
    }

    pub fn mark_voice_notes_seen(&mut self, sip_address: &str) -> Result<(), String> {
        self.message_store.mark_contact_seen(sip_address)
    }

    pub fn mark_call_history_seen(&mut self, sip_address: &str) {
        self.call_history.mark_seen(sip_address);
    }

    pub fn play_voice_note(&mut self, file_path: &str) -> Result<(), String> {
        self.voice_note_playback.play(file_path)
    }

    pub fn stop_voice_note_playback(&mut self) {
        self.voice_note_playback.stop();
    }

    pub fn poll_backend_events<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
    ) -> Result<Vec<BackendEvent>, String> {
        let events: Vec<BackendEvent> = backend
            .iterate()?
            .into_iter()
            .map(|event| self.translate_backend_event(event))
            .collect();
        for event in &events {
            self.apply_backend_event(event);
        }
        Ok(events)
    }

    pub fn take_lifecycle_events(&mut self) -> Vec<LifecycleEvent> {
        self.lifecycle.take_events()
    }

    fn apply_backend_event(&mut self, event: &BackendEvent) {
        match event {
            BackendEvent::RegistrationChanged { state, .. } => {
                self.registration_state = state.clone();
                if state == "ok" {
                    self.registered = true;
                } else if matches!(state.as_str(), "failed" | "cleared" | "none") {
                    self.registered = false;
                }
            }
            BackendEvent::IncomingCall { call_id, from_uri } => {
                self.call.incoming(call_id, from_uri);
            }
            BackendEvent::CallStateChanged { call_id, state } => {
                if matches!(
                    state.as_str(),
                    "incoming"
                        | "outgoing_init"
                        | "outgoing_progress"
                        | "outgoing_ringing"
                        | "outgoing_early_media"
                        | "connected"
                        | "streams_running"
                ) {
                    self.voice_note_playback.stop();
                }
                self.call.apply_call_state(call_id, state);
                self.record_finished_call_history();
            }
            BackendEvent::BackendStopped { reason } => {
                self.backend_started = false;
                self.registered = false;
                self.registration_state = "failed".to_string();
                self.lifecycle.mark_recovery_pending();
                self.lifecycle.record("failed", reason, false);
                self.call.clear_with_state("error");
                self.outbound_message_ids.clear();
            }
            BackendEvent::MessageReceived { message } => {
                if let Err(error) = self.message_store.upsert(message.clone()) {
                    eprintln!("failed to persist received VoIP message: {error}");
                }
                self.last_message = Some(MessageSessionState::received(message));
            }
            BackendEvent::MessageDeliveryChanged {
                message_id,
                delivery_state,
                local_file_path,
                error,
            } => {
                self.last_message = Some(MessageSessionState::delivery_changed(
                    message_id,
                    delivery_state,
                    local_file_path,
                    error,
                ));
                if let Err(store_error) =
                    self.message_store
                        .update_delivery(message_id, delivery_state, local_file_path)
                {
                    eprintln!("failed to persist VoIP delivery update: {store_error}");
                }
                self.voice_note
                    .apply_delivery(message_id, delivery_state, local_file_path);
            }
            BackendEvent::MessageDownloadCompleted {
                message_id,
                local_file_path,
                mime_type,
            } => {
                self.last_message = Some(MessageSessionState::download_completed(
                    message_id,
                    local_file_path,
                ));
                if let Err(error) =
                    self.message_store
                        .update_download(message_id, local_file_path, mime_type)
                {
                    eprintln!("failed to persist VoIP download update: {error}");
                }
                self.voice_note
                    .apply_download(message_id, local_file_path, mime_type);
            }
            BackendEvent::MessageFailed { message_id, reason } => {
                self.last_message = Some(MessageSessionState::failed(message_id, reason));
                if let Err(error) = self.message_store.update_delivery(message_id, "failed", "") {
                    eprintln!("failed to persist VoIP failure update: {error}");
                }
                self.voice_note.fail(message_id);
            }
        }
    }

    fn record_finished_call_history(&mut self) {
        if let Some(entry) = self.call.take_unrecorded_history_entry() {
            self.call_history.record(entry);
        }
    }

    fn translate_backend_event(&mut self, event: BackendEvent) -> BackendEvent {
        match event {
            BackendEvent::MessageReceived { mut message } => {
                message.message_id = self.translate_message_id(&message.message_id, false);
                let message = normalize_message_record(message);
                BackendEvent::MessageReceived { message }
            }
            BackendEvent::MessageDeliveryChanged {
                message_id,
                delivery_state,
                local_file_path,
                error,
            } => {
                let terminal = is_terminal_delivery_state(&delivery_state);
                BackendEvent::MessageDeliveryChanged {
                    message_id: self.translate_message_id(&message_id, terminal),
                    delivery_state,
                    local_file_path,
                    error,
                }
            }
            BackendEvent::MessageDownloadCompleted {
                message_id,
                local_file_path,
                mime_type,
            } => BackendEvent::MessageDownloadCompleted {
                message_id: self.translate_message_id(&message_id, false),
                local_file_path,
                mime_type,
            },
            BackendEvent::MessageFailed { message_id, reason } => BackendEvent::MessageFailed {
                message_id: self.translate_message_id(&message_id, true),
                reason,
            },
            other => other,
        }
    }

    fn translate_message_id(&mut self, backend_id: &str, terminal: bool) -> String {
        self.outbound_message_ids.translate(backend_id, terminal)
    }

    fn local_identity(&self) -> String {
        self.config
            .as_ref()
            .map(|config| config.sip_identity.clone())
            .unwrap_or_default()
    }
}

fn voice_recording_limit_reached(duration_ms: i32) -> bool {
    duration_ms >= MAX_VOICE_NOTE_DURATION_MS
}

#[cfg(test)]
mod recording_tests {
    use super::*;

    #[derive(Default)]
    struct LocalRecordingBackend {
        started: bool,
        recording: bool,
    }

    impl VoipRuntimeBackend for LocalRecordingBackend {
        fn start(&mut self, config: &VoipConfig) -> Result<(), String> {
            if config.has_sip_account() {
                return Err("test backend expected local-only config".to_string());
            }
            self.started = true;
            Ok(())
        }

        fn stop(&mut self) {
            self.started = false;
            self.recording = false;
        }

        fn iterate(&mut self) -> Result<Vec<BackendEvent>, String> {
            Ok(Vec::new())
        }

        fn make_call(&mut self, _sip_address: &str) -> Result<String, String> {
            Err("SIP unavailable".to_string())
        }

        fn answer_call(&mut self) -> Result<(), String> {
            Err("SIP unavailable".to_string())
        }

        fn reject_call(&mut self) -> Result<(), String> {
            Err("SIP unavailable".to_string())
        }

        fn hangup(&mut self) -> Result<(), String> {
            Err("SIP unavailable".to_string())
        }

        fn set_muted(&mut self, _muted: bool) -> Result<(), String> {
            Err("SIP unavailable".to_string())
        }

        fn send_text_message(&mut self, _sip_address: &str, _text: &str) -> Result<String, String> {
            Err("SIP unavailable".to_string())
        }

        fn start_voice_recording(&mut self, _file_path: &str) -> Result<(), String> {
            if !self.started {
                return Err("backend not started".to_string());
            }
            self.recording = true;
            Ok(())
        }

        fn voice_recording_metrics(&mut self) -> Result<VoiceRecordingMetrics, String> {
            if !self.recording {
                return Err("not recording".to_string());
            }
            Ok(VoiceRecordingMetrics {
                duration_ms: 200,
                capture_level_permille: 618,
            })
        }

        fn stop_voice_recording(&mut self) -> Result<i32, String> {
            self.recording = false;
            Ok(420)
        }

        fn cancel_voice_recording(&mut self) -> Result<(), String> {
            self.recording = false;
            Ok(())
        }

        fn send_voice_note(
            &mut self,
            _sip_address: &str,
            _file_path: &str,
            _duration_ms: i32,
            _mime_type: &str,
        ) -> Result<String, String> {
            Err("SIP unavailable".to_string())
        }
    }

    #[test]
    fn held_recording_has_a_hard_sixty_second_limit() {
        assert!(!voice_recording_limit_reached(59_999));
        assert!(voice_recording_limit_reached(60_000));
    }

    #[test]
    fn local_first_backend_records_without_sip_registration() {
        let config = VoipConfig::from_payload(&json!({
            "sip_identity": "",
            "message_store_dir": "",
            "voice_note_store_dir": "data/communication/voice_notes"
        }))
        .expect("local-only config");
        let mut backend = LocalRecordingBackend::default();
        let mut host = VoipHost::default();

        host.configure(config);
        host.register(&mut backend).expect("start local backend");
        assert_eq!(host.health_payload()["backend_available"], true);
        assert_eq!(host.health_payload()["registered"], false);

        host.start_voice_recording(&mut backend, "/tmp/local.wav")
            .expect("start local recording");
        assert!(host
            .refresh_voice_recording_metrics(&mut backend)
            .expect("refresh local metrics"));
        let snapshot = host.session_snapshot_payload();
        assert_eq!(snapshot["voice_note"]["state"], "recording");
        assert_eq!(snapshot["voice_note"]["duration_ms"], 200);
        assert_eq!(snapshot["voice_note"]["capture_level_permille"], 618);
    }
}
