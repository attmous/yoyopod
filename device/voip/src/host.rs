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
use std::collections::BTreeMap;
use std::fs;
use std::io::ErrorKind;
use yoyopod_protocol::call::{
    CallAction, CallCommand, CallDirection, CallOffer, CallPhase, CallTransport, CallUpdate,
    SessionKey,
};

pub use crate::lifecycle::LifecycleEvent;
pub use crate::messages::MessageRecord;

pub trait VoipRuntimeBackend {
    fn set_worker_generation(&mut self, _generation: u64) {}
    fn start(&mut self, config: &VoipConfig) -> Result<(), String>;
    fn stop(&mut self);
    fn iterate(&mut self) -> Result<Vec<BackendEvent>, String>;
    fn apply_call(&mut self, _command: &CallCommand) -> Result<(), String> {
        Err("session call control unavailable".into())
    }
    fn make_session_call(&mut self, _key: &SessionKey, _address: &str) -> Result<(), String> {
        Err("session dialing unavailable".into())
    }
    fn make_call(&mut self, sip_address: &str) -> Result<String, String>;
    fn answer_call(&mut self) -> Result<(), String>;
    fn reject_call(&mut self) -> Result<(), String>;
    fn hangup(&mut self) -> Result<(), String>;
    fn set_muted(&mut self, muted: bool) -> Result<(), String>;
    fn set_audio_devices(
        &mut self,
        _playback_device: &str,
        _ringer_device: &str,
        _capture_device: &str,
        _media_device: &str,
        _microphone_gain: u8,
        _output_volume: u8,
        _alert_volume: u8,
    ) -> Result<(), String> {
        Ok(())
    }
    fn send_text_message(&mut self, sip_address: &str, text: &str) -> Result<String, String>;
    fn start_voice_recording(&mut self, file_path: &str) -> Result<(), String>;
    fn voice_recording_metrics(&mut self) -> Result<VoiceRecordingMetrics, String>;
    fn stop_voice_recording(&mut self) -> Result<i32, String>;
    /// Close capture and release its native owner without deleting a saved WAV.
    fn finalize_voice_recording_for_call(&mut self) -> Result<i32, String> {
        match self.stop_voice_recording() {
            Ok(duration) => Ok(duration),
            Err(error) => {
                self.cancel_voice_recording()?;
                Err(error)
            }
        }
    }
    fn cancel_voice_recording(&mut self) -> Result<(), String>;
    fn send_voice_note(
        &mut self,
        sip_address: &str,
        file_path: &str,
        duration_ms: i32,
        mime_type: &str,
    ) -> Result<String, String>;
    fn send_saved_voice_note(
        &mut self,
        _sip_address: &str,
        _file_path: &str,
    ) -> Result<String, String> {
        Err("saved voice-note sending unavailable in this backend".into())
    }
    fn saved_transfer_uses_path(&self, _path: &str) -> bool {
        false
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct VoiceRecordingMetrics {
    pub duration_ms: i32,
    pub capture_level_permille: i32,
}

const MAX_VOICE_NOTE_DURATION_MS: i32 = 60_000;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum BackendEvent {
    Cleanup(SessionKey),
    Offer(CallOffer),
    Update(CallUpdate),
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
    interrupted_draft: Option<String>,
    finalized_draft_source: Option<(String, i32)>,
    discarded_draft_path: Option<String>,
    restored_draft_source: Option<String>,
    audio_fence: yoyopod_protocol::audio::AudioCallFence,
    config: Option<VoipConfig>,
    worker_generation: u64,
    sessions: BTreeMap<String, CallUpdate>,
    watermarks: [u64; 2],
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
            interrupted_draft: None,
            finalized_draft_source: None,
            discarded_draft_path: None,
            restored_draft_source: None,
            audio_fence: Default::default(),
            config: None,
            worker_generation: 0,
            sessions: BTreeMap::new(),
            watermarks: [0; 2],
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
    pub fn interrupt_for_call<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
        request: &yoyopod_protocol::call::InterruptForCall,
    ) -> Result<Option<String>, String> {
        self.interrupt_for_call_with_copy(
            backend,
            request,
            crate::voice_notes::preserve_interrupted_wav,
        )
    }

    fn interrupt_for_call_with_copy<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
        request: &yoyopod_protocol::call::InterruptForCall,
        preserve: impl FnOnce(&str) -> Result<String, String>,
    ) -> Result<Option<String>, String> {
        self.audio_fence.interrupt(request)?;
        self.voice_note_playback.stop_checked()?;
        if !self.voice_note.is_recording() && self.voice_note.recorded_duration_ms().is_none() {
            return Ok(None);
        }
        let path = self.voice_note.payload()["file_path"]
            .as_str()
            .unwrap_or_default()
            .to_string();
        if !self.voice_note.is_recording()
            && self.interrupted_draft.as_deref() == Some(path.as_str())
        {
            return Ok(Some(path));
        }
        let duration = match self
            .finalized_draft_source
            .as_ref()
            .filter(|(source, _)| source == &path)
            .map(|(_, duration)| Ok(*duration))
            .unwrap_or_else(|| backend.finalize_voice_recording_for_call())
        {
            Ok(duration) => duration,
            Err(error) => {
                self.voice_note.reset();
                return Err(error);
            }
        };
        if duration <= 0 || !crate::voice_notes::usable_wav(&path) {
            let _ = fs::remove_file(path);
            self.voice_note.reset();
            return Ok(None);
        }
        self.finalized_draft_source = Some((path.clone(), duration));
        let saved_path = preserve(&path)?;
        self.voice_note.start_recording(&saved_path);
        self.voice_note.finish_recording(duration);
        self.interrupted_draft = Some(saved_path.clone());
        self.finalized_draft_source = None;
        if !self.message_store.references_file(&path) {
            let _ = fs::remove_file(&path);
        }
        Ok(Some(saved_path))
    }
    pub fn release_call(&mut self, request: &yoyopod_protocol::call::InterruptForCall) -> bool {
        self.audio_fence.release(request)
    }

    pub fn draft_recovery_source(&self) -> Option<(String, i32)> {
        self.finalized_draft_source.clone()
    }

    pub fn restore_finalized_source(
        &mut self,
        source: &str,
        duration_ms: i32,
    ) -> Result<String, String> {
        if self.interrupted_draft.is_some()
            || (self.voice_note.is_recording() && self.finalized_draft_source.is_none())
            || !crate::voice_notes::usable_wav(source)
        {
            return Err("finalized source unavailable or another draft owns recorder".into());
        }
        self.finalized_draft_source = Some((source.into(), duration_ms));
        let path = crate::voice_notes::preserve_interrupted_wav(source)?;
        self.interrupted_draft = Some(path.clone());
        self.restored_draft_source = Some(source.into());
        self.finalized_draft_source = None;
        self.voice_note.start_recording(&path);
        self.voice_note.finish_recording(duration_ms);
        if !self.message_store.references_file(source) {
            let _ = fs::remove_file(source);
        }
        Ok(path)
    }

    pub fn mark_saved_source_failed(
        &mut self,
        source: &str,
        duration_ms: i32,
        mime: &str,
        client_id: &str,
    ) {
        self.voice_note
            .start_sending(source, duration_ms, mime, client_id);
        self.voice_note.fail(client_id);
    }

    pub fn adopt_finalized_source_for_discard(&mut self, source: &str) -> Result<(), String> {
        if self.interrupted_draft.is_some()
            || (self.voice_note.is_recording() && self.finalized_draft_source.is_none())
        {
            return Err("another draft owns recorder".into());
        }
        self.interrupted_draft = Some(source.into());
        self.finalized_draft_source = None;
        Ok(())
    }
    pub fn permit_audio_start(&self, payload: &serde_json::Value) -> Result<(), String> {
        self.audio_fence
            .permit_start(serde_json::from_value(payload.clone()).ok())
    }
    pub fn configure(&mut self, config: VoipConfig) {
        self.sessions.clear();
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

    pub fn set_worker_generation(&mut self, generation: u64) {
        if generation <= self.worker_generation {
            return;
        }
        self.worker_generation = generation;
        self.sessions.clear();
        self.watermarks = [0; 2];
    }

    /// Admission is explicit runtime policy. Raw native offers never create history.
    pub fn admit_session(&mut self, key: &SessionKey) -> Result<(), String> {
        if key.transport != CallTransport::Sip || key.generation != self.worker_generation {
            return Err("stale admission".into());
        }
        let session = self
            .sessions
            .get(&key.call_id)
            .ok_or("unknown admission key")?;
        if session.phase == CallPhase::Ended || session.direction != CallDirection::Incoming {
            return Err("inadmissible native session".into());
        }
        if self.call.active_call_id() == Some(key.call_id.as_str()) {
            return Ok(());
        }
        if self.call.active_call_id().is_some() {
            return Err("another admitted call owns history".into());
        }
        self.call.incoming(&key.call_id, &session.address);
        Ok(())
    }

    pub fn apply_call<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
        command: &CallCommand,
    ) -> Result<(), String> {
        if command.key.transport != CallTransport::Sip
            || command.key.generation != self.worker_generation
        {
            return Err("stale or incorrect call transport generation".into());
        }
        let session = self
            .sessions
            .get(&command.key.call_id)
            .ok_or("unknown call ID")?;
        if session.phase == CallPhase::Ended {
            return Err("call already ended".into());
        }
        backend.apply_call(command)?;
        if self.call.active_call_id() == Some(command.key.call_id.as_str())
            && matches!(command.action, CallAction::Reject(_))
        {
            self.call.clear_with_state_and_action("end", "reject");
            self.record_finished_call_history();
        }
        if let CallAction::SetMute(muted) = command.action {
            if let Some(session) = self.sessions.get_mut(&command.key.call_id) {
                session.muted = muted;
            }
        }
        Ok(())
    }

    pub fn dial_session<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
        key: &SessionKey,
        address: &str,
    ) -> Result<(), String> {
        if key.transport != CallTransport::Sip
            || key.generation != self.worker_generation
            || key.call_id.trim().is_empty()
            || key.call_id.starts_with("sip-incoming-")
            || self.sessions.contains_key(&key.call_id)
            || self.sessions.len() >= yoyopod_protocol::call::MAX_LIVE_CALLS
            || !yoyopod_protocol::call::call_ordinal(&key.transport, &key.call_id)
                .is_some_and(|(namespace, serial)| namespace == 1 && serial > self.watermarks[1])
        {
            return Err("invalid, duplicate or stale outgoing session key".into());
        }
        self.watermarks[1] = yoyopod_protocol::call::call_ordinal(&key.transport, &key.call_id)
            .unwrap()
            .1;
        backend.make_session_call(key, address)?;
        self.call.start_outgoing(&key.call_id, address);
        self.sessions.insert(
            key.call_id.clone(),
            CallUpdate {
                key: key.clone(),
                direction: CallDirection::Outgoing,
                phase: CallPhase::Outgoing,
                address: address.into(),
                duration_seconds: 0,
                muted: false,
                sequence: 0,
            },
        );
        Ok(())
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
        let mut payload = RuntimeSnapshot {
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
        .payload();
        payload["discarded_draft_path"] = json!(self.discarded_draft_path);
        payload["restored_draft_source"] = json!(self.restored_draft_source);
        payload["restored_draft_path"] = json!(self.interrupted_draft);
        payload
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
        backend.set_worker_generation(self.worker_generation);
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
        self.sessions.clear();
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
        self.sessions.insert(
            call_id.clone(),
            CallUpdate {
                key: SessionKey {
                    transport: CallTransport::Sip,
                    generation: self.worker_generation,
                    call_id,
                },
                direction: CallDirection::Outgoing,
                phase: CallPhase::Outgoing,
                address: sip_address.into(),
                duration_seconds: 0,
                muted: false,
                sequence: 0,
            },
        );
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

    pub fn set_audio_devices<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
        playback_device: &str,
        ringer_device: &str,
        capture_device: &str,
        media_device: &str,
        microphone_gain: u8,
        output_volume: u8,
        alert_volume: u8,
    ) -> Result<(), String> {
        backend.set_audio_devices(
            playback_device,
            ringer_device,
            capture_device,
            media_device,
            microphone_gain,
            output_volume,
            alert_volume,
        )
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
        if self.interrupted_draft.is_some() || self.finalized_draft_source.is_some() {
            return Err("handle interrupted draft before recording".into());
        }
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
        if self.interrupted_draft.is_some() {
            return Err("interrupted draft requires explicit saved send".into());
        }
        self.send_voice_note_from(
            backend,
            sip_address,
            file_path,
            (duration_ms, mime_type),
            client_id,
            false,
        )
    }

    pub fn send_saved_voice_note<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
        sip_address: &str,
        file_path: &str,
        duration_ms: i32,
        mime_type: &str,
        client_id: &str,
    ) -> Result<String, String> {
        self.restore_saved_voice_note(file_path, duration_ms, false)?;
        if self.audio_fence.is_reserved() || self.interrupted_draft.as_deref() != Some(file_path) {
            return Err("saved draft is unavailable or call owns audio".into());
        }
        self.send_voice_note_from(
            backend,
            sip_address,
            file_path,
            (duration_ms, mime_type),
            client_id,
            true,
        )
    }

    /// Availability is explicit; message-store and async upload bytes are retained.
    pub fn discard_saved_voice_note<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &B,
        path: &str,
    ) -> Result<(), String> {
        self.restore_saved_voice_note(path, 0, true)?;
        if self.interrupted_draft.as_deref() != Some(path) {
            return Err("stale saved draft".into());
        }
        if !backend.saved_transfer_uses_path(path) && !self.message_store.references_file(path) {
            match fs::remove_file(path) {
                Ok(()) => {}
                Err(e) if e.kind() == ErrorKind::NotFound => {}
                Err(e) => return Err(e.to_string()),
            }
        }
        self.interrupted_draft = None;
        self.discarded_draft_path = Some(path.into());
        if self.voice_note.payload()["file_path"].as_str() == Some(path) {
            self.voice_note.reset();
        }
        Ok(())
    }

    /// Only the runtime's explicit owned-draft commands use this recovery seam.
    /// UI file/recipient input never goes directly to this host operation.
    fn restore_saved_voice_note(
        &mut self,
        path: &str,
        duration_ms: i32,
        discard: bool,
    ) -> Result<(), String> {
        if self.interrupted_draft.as_deref() == Some(path) {
            return Ok(());
        }
        if self.interrupted_draft.is_some()
            || self.voice_note.is_recording()
            || self.finalized_draft_source.is_some()
            || !crate::voice_notes::is_saved_draft_path(path)
            || (!discard && !crate::voice_notes::usable_wav(path))
        {
            return Err(
                "saved draft cannot be restored over another owner or from invalid source".into(),
            );
        }
        self.interrupted_draft = Some(path.into());
        self.voice_note.start_recording(path);
        self.voice_note.finish_recording(duration_ms.max(0));
        Ok(())
    }

    fn send_voice_note_from<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
        sip_address: &str,
        file_path: &str,
        media: (i32, &str),
        client_id: &str,
        saved: bool,
    ) -> Result<String, String> {
        let (duration_ms, mime_type) = media;
        let client_id = client_id.trim();
        if client_id.is_empty() {
            return Err("voip voice note requires client_id".to_string());
        }
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
        let backend_id = match if saved && !crate::voice_notes::usable_wav(file_path) {
            Err("saved WAV missing or unusable".into())
        } else if saved {
            backend.send_saved_voice_note(sip_address, file_path)
        } else {
            backend.send_voice_note(sip_address, file_path, duration_ms, mime_type)
        } {
            Ok(message_id) => message_id,
            Err(error) => {
                self.voice_note.fail(client_id);
                self.last_message = Some(MessageSessionState::failed(client_id, &error));
                if let Err(store_error) = self
                    .message_store
                    .update_delivery(client_id, "failed", file_path)
                {
                    eprintln!("failed to persist local voice-note delivery failure: {store_error}");
                }
                return Ok(client_id.to_string());
            }
        };
        if let Err(error) =
            self.outbound_message_ids
                .remember(&backend_id, client_id, "voip voice note")
        {
            self.voice_note.fail(client_id);
            self.last_message = Some(MessageSessionState::failed(client_id, &error));
            let _ = self
                .message_store
                .update_delivery(client_id, "failed", file_path);
            return Ok(client_id.to_string());
        }
        Ok(client_id.to_string())
    }

    pub fn mark_voice_notes_seen(&mut self, sip_address: &str) -> Result<(), String> {
        self.message_store.mark_contact_seen(sip_address)
    }

    pub fn mark_call_history_seen(&mut self, sip_address: &str) {
        self.call_history.mark_seen(sip_address);
    }

    pub fn play_voice_note(&mut self, file_path: &str, duration_ms: i32) -> Result<(), String> {
        self.voice_note_playback.play(file_path, duration_ms)
    }

    pub fn play_focus_prompt(&mut self, file_path: &str, duration_ms: i32) -> Result<bool, String> {
        self.voice_note_playback
            .play_focus_prompt(file_path, duration_ms)
    }

    pub fn pause_voice_note_playback(&mut self) -> Result<(), String> {
        self.voice_note_playback.pause()
    }

    pub fn resume_voice_note_playback(&mut self) -> Result<(), String> {
        self.voice_note_playback.resume()
    }

    pub fn stop_voice_note_playback(&mut self) {
        self.voice_note_playback.stop();
    }

    pub fn stop_focus_prompt_playback(&mut self) -> bool {
        self.voice_note_playback.stop_focus_prompt()
    }

    pub fn refresh_voice_note_playback(&mut self) -> bool {
        self.voice_note_playback.refresh()
    }

    pub fn delete_voice_note<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &B,
        message_id: &str,
    ) -> Result<bool, String> {
        if self
            .message_store
            .voice_note_file(message_id)
            .is_some_and(|path| backend.saved_transfer_uses_path(path))
        {
            return Err(
                "voice transfer is still using this recording; retry deletion after completion"
                    .into(),
            );
        }
        let Some(file_path) = self.message_store.delete_voice_note(message_id)? else {
            return Ok(false);
        };
        if self.voice_note_playback.payload()["file_path"].as_str() == Some(file_path.as_str()) {
            self.voice_note_playback.stop();
        }
        // Saved files may still be read by an asynchronous native transfer or
        // another outgoing retry record. Availability/deletion never moves bytes.
        if !file_path.trim().is_empty()
            && self.interrupted_draft.as_deref() != Some(file_path.as_str())
            && !self.message_store.references_file(&file_path)
        {
            match fs::remove_file(&file_path) {
                Ok(()) => {}
                Err(error) if error.kind() == ErrorKind::NotFound => {}
                Err(error) => {
                    return Err(format!(
                        "failed to remove voice-note audio {file_path}: {error}"
                    ));
                }
            }
        }
        Ok(true)
    }

    pub fn poll_backend_events<B: VoipRuntimeBackend + ?Sized>(
        &mut self,
        backend: &mut B,
    ) -> Result<Vec<BackendEvent>, String> {
        let mut events = vec![];
        for event in backend.iterate()? {
            let released = match &event {
                BackendEvent::CallStateChanged { call_id, state } if state == "released" => {
                    self.sessions.get(call_id).map(|s| s.key.clone())
                }
                _ => None,
            };
            if let Some(event) = self.translate_backend_event(event) {
                events.push(event);
            }
            if let Some(key) = released {
                if self.sessions.remove(&key.call_id).is_some() {
                    events.push(BackendEvent::Cleanup(key));
                }
            }
        }
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
            BackendEvent::Cleanup(_)
            | BackendEvent::Offer(_)
            | BackendEvent::Update(_)
            | BackendEvent::IncomingCall { .. } => {}
            BackendEvent::CallStateChanged { call_id, state } => {
                if self.call.active_call_id() != Some(call_id.as_str()) {
                    return;
                }
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

    fn translate_backend_event(&mut self, event: BackendEvent) -> Option<BackendEvent> {
        Some(match event {
            BackendEvent::IncomingCall { call_id, from_uri } => {
                let Some((0, serial)) =
                    yoyopod_protocol::call::call_ordinal(&CallTransport::Sip, &call_id)
                else {
                    return None;
                };
                if serial <= self.watermarks[0]
                    || self.sessions.len() >= yoyopod_protocol::call::MAX_LIVE_CALLS
                {
                    return None;
                }
                self.watermarks[0] = serial;
                let key = SessionKey {
                    transport: CallTransport::Sip,
                    generation: self.worker_generation,
                    call_id: call_id.clone(),
                };
                self.sessions.entry(call_id).or_insert(CallUpdate {
                    key: key.clone(),
                    direction: CallDirection::Incoming,
                    phase: CallPhase::Ringing,
                    address: from_uri.clone(),
                    duration_seconds: 0,
                    muted: false,
                    sequence: 0,
                });
                BackendEvent::Offer(CallOffer {
                    key,
                    address: from_uri,
                })
            }
            BackendEvent::CallStateChanged { call_id, state } => {
                if self.call.active_call_id() == Some(call_id.as_str()) {
                    self.call.apply_call_state(&call_id, &state);
                    self.record_finished_call_history();
                }
                if let Some(session) = self.sessions.get_mut(&call_id) {
                    if session.phase == CallPhase::Ended {
                        return None;
                    }
                    {
                        session.phase = match state.as_str() {
                            "incoming" => CallPhase::Ringing,
                            "connected" | "streams_running" => CallPhase::Active,
                            "end" | "error" | "released" => CallPhase::Ended,
                            "outgoing_init"
                            | "outgoing_progress"
                            | "outgoing_ringing"
                            | "outgoing_early_media" => CallPhase::Outgoing,
                            _ => session.phase.clone(),
                        };
                        session.sequence = session
                            .sequence
                            .checked_add(1)
                            .expect("call sequence exhausted");
                    }
                    BackendEvent::Update(session.clone())
                } else {
                    return None;
                }
            }

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
        })
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
    fn sample_wav() -> Vec<u8> {
        let mut bytes = b"RIFF".to_vec();
        bytes.extend(38u32.to_le_bytes());
        bytes.extend(b"WAVEfmt ");
        bytes.extend(16u32.to_le_bytes());
        bytes.extend(1u16.to_le_bytes());
        bytes.extend(1u16.to_le_bytes());
        bytes.extend(16_000u32.to_le_bytes());
        bytes.extend(32_000u32.to_le_bytes());
        bytes.extend(2u16.to_le_bytes());
        bytes.extend(16u16.to_le_bytes());
        bytes.extend(b"data");
        bytes.extend(2u32.to_le_bytes());
        bytes.extend(1i16.to_le_bytes());
        bytes
    }
    #[test]
    fn call_interruption_discards_empty_or_invalid_capture_and_releases_failed_save() {
        for (case, zero, fail) in [
            ("empty", true, false),
            ("invalid", false, false),
            ("failure", false, true),
        ] {
            let mut host = VoipHost::default();
            let mut backend = LocalRecordingBackend {
                started: true,
                zero_duration: zero,
                fail_stop: fail,
                ..Default::default()
            };
            let path =
                test_directory().join(format!("call-draft-{case}-{}.wav", std::process::id()));
            std::fs::write(&path, [1u8; 100]).unwrap();
            host.start_voice_recording(&mut backend, path.to_str().unwrap())
                .unwrap();
            let request = yoyopod_protocol::call::InterruptForCall {
                key: command("sip-incoming-1", 1, CallAction::Answer).key,
                activity_generation: 1,
                voice_activity_generation: 3,
            };
            let result = host.interrupt_for_call(&mut backend, &request);
            assert!(!backend.recording, "even failed saves release capture");
            assert_eq!(backend.sends, 0);
            if fail {
                assert!(result.is_err());
                let _ = std::fs::remove_file(path);
            } else {
                assert_eq!(result.unwrap(), None, "no usable WAV draft for {case}");
                assert!(!path.exists());
            }
        }
    }

    #[test]
    fn call_interruption_closes_capture_and_returns_unsent_draft() {
        let mut host = VoipHost::default();
        let mut backend = LocalRecordingBackend {
            started: true,
            ..Default::default()
        };
        let path = test_directory().join(format!("call-draft-{}.wav", std::process::id()));
        std::fs::write(&path, sample_wav()).unwrap();
        host.start_voice_recording(&mut backend, path.to_str().unwrap())
            .unwrap();
        let request = yoyopod_protocol::call::InterruptForCall {
            key: command("sip-incoming-1", 1, CallAction::Answer).key,
            activity_generation: 1,
            voice_activity_generation: 3,
        };
        let draft = host.interrupt_for_call(&mut backend, &request).unwrap();
        assert!(
            !backend.recording,
            "capture must be released before readiness"
        );
        assert_ne!(draft.as_deref(), path.to_str());
        assert_eq!(
            std::fs::read(draft.as_ref().unwrap()).unwrap(),
            sample_wav()
        );
        assert_eq!(host.voice_note.payload()["state"], "recorded");
        assert_eq!(host.voice_note.payload()["message_id"], "");
        assert_eq!(backend.sends, 0);
        assert_eq!(
            host.interrupt_for_call(&mut backend, &request).unwrap(),
            draft
        );
        assert!(!path.exists());
        std::fs::remove_file(draft.unwrap()).unwrap();
    }

    #[derive(Default)]
    struct LocalRecordingBackend {
        saved_sends: usize,
        fail_saved_send: bool,
        pending_saved_path: Option<String>,
        fail_stop: bool,
        zero_duration: bool,
        sends: usize,
        started: bool,
        recording: bool,
        events: Vec<BackendEvent>,
        commands: Vec<CallCommand>,
    }

    impl VoipRuntimeBackend for LocalRecordingBackend {
        fn saved_transfer_uses_path(&self, path: &str) -> bool {
            self.pending_saved_path.as_deref() == Some(path)
        }
        fn send_saved_voice_note(
            &mut self,
            _recipient: &str,
            path: &str,
        ) -> Result<String, String> {
            self.saved_sends += 1;
            if self.fail_saved_send {
                return Err("upload failed".into());
            }
            self.pending_saved_path = Some(path.into());
            Ok(format!("saved-{}", self.saved_sends))
        }
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
            Ok(std::mem::take(&mut self.events))
        }

        fn apply_call(&mut self, command: &CallCommand) -> Result<(), String> {
            self.commands.push(command.clone());
            Ok(())
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
            if self.fail_stop {
                return Err("save failed".into());
            }
            self.recording = false;
            Ok(if self.zero_duration { 0 } else { 420 })
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
            self.sends += 1;
            Err("SIP unavailable".to_string())
        }
    }

    fn test_directory() -> std::path::PathBuf {
        let path = std::env::temp_dir().join(format!("yoyopod-voip-tests-{}", std::process::id()));
        std::fs::create_dir_all(&path).unwrap();
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o700)).unwrap();
        }
        path
    }
    fn incoming(id: &str) -> BackendEvent {
        BackendEvent::IncomingCall {
            call_id: id.into(),
            from_uri: "sip:same@example.test".into(),
        }
    }

    #[test]
    fn unavailable_saved_send_worker_returns_correlated_pre_native_failure() {
        let mut host = VoipHost::default();
        let mut backend = LocalRecordingBackend::default();
        let command = crate::protocol::WorkerEnvelope::command(
            "voip.send_saved_voice_note",
            Some("send-1".into()),
            json!({"draft_id":"draft-1","uri":"sip:a@test","file_path":"owned.wav","mime_type":"audio/wav","duration_ms":420,"client_id":"send-1"}),
        );
        let input = command.encode().unwrap();
        let mut output = Vec::new();
        crate::worker::run_worker(
            std::io::Cursor::new(input),
            &mut output,
            &mut Vec::new(),
            &mut host,
            &mut backend,
        )
        .unwrap();
        let envelopes: Vec<crate::protocol::WorkerEnvelope> = String::from_utf8(output)
            .unwrap()
            .lines()
            .map(|line| crate::protocol::WorkerEnvelope::decode(line.as_bytes()).unwrap())
            .collect();
        assert!(envelopes
            .iter()
            .any(|e| e.request_id.as_deref() == Some("send-1")
                && e.payload["code"] == "saved_send_not_started"));
        assert_eq!(backend.sends, 0);
    }

    #[test]
    fn released_sip_sessions_are_bounded_and_old_incoming_cannot_reappear() {
        let mut host = VoipHost::default();
        let mut backend = LocalRecordingBackend::default();
        for serial in 1..=10_000 {
            let id = format!("sip-incoming-{serial}");
            backend.events = vec![incoming(&id), state(&id, "end"), state(&id, "released")];
            host.poll_backend_events(&mut backend).unwrap();
            assert!(
                host.sessions.is_empty(),
                "Released must retire the full update"
            );
        }
        backend.events = vec![
            incoming("sip-incoming-1"),
            state("sip-incoming-1", "connected"),
        ];
        assert!(host.poll_backend_events(&mut backend).unwrap().is_empty());
        assert!(host.sessions.is_empty());
    }

    #[test]
    fn saved_send_recovers_host_without_capture_and_retains_async_bytes_until_last_delete() {
        let source = test_directory().join(format!("saved-source-{}.wav", std::process::id()));
        std::fs::write(&source, sample_wav()).unwrap();
        let path = crate::voice_notes::preserve_interrupted_wav(source.to_str().unwrap()).unwrap();
        let mut host = VoipHost::default(); // replacement worker, no recorder/draft metadata
        let mut backend = LocalRecordingBackend::default();
        host.send_saved_voice_note(
            &mut backend,
            "sip:mama@example.test",
            &path,
            420,
            "audio/wav",
            "c1",
        )
        .unwrap();
        assert_eq!(backend.saved_sends, 1);
        assert_eq!(backend.sends, 0);
        assert!(!backend.recording);
        assert_eq!(host.voice_note.payload()["state"], "sending");
        assert!(host
            .start_voice_recording(&mut backend, "replacement.wav")
            .is_err());
        host.discard_saved_voice_note(&backend, &path).unwrap();
        assert!(std::path::Path::new(&path).exists());
        assert!(host.delete_voice_note(&backend, "c1").is_err());
        assert!(host.message_store.voice_note_file("c1").is_some());
        backend.pending_saved_path = None;
        assert!(host.delete_voice_note(&backend, "c1").unwrap());
        assert!(!std::path::Path::new(&path).exists());
        std::fs::remove_file(source).unwrap();
    }

    #[test]
    fn saved_send_failure_retry_and_stale_identity_preserve_owned_source() {
        let source = test_directory().join(format!("saved-failure-{}.wav", std::process::id()));
        std::fs::write(&source, sample_wav()).unwrap();
        let a = crate::voice_notes::preserve_interrupted_wav(source.to_str().unwrap()).unwrap();
        let b = crate::voice_notes::preserve_interrupted_wav(source.to_str().unwrap()).unwrap();
        assert_ne!(a, b);
        let mut host = VoipHost::default();
        let mut backend = LocalRecordingBackend {
            fail_saved_send: true,
            ..Default::default()
        };
        host.send_saved_voice_note(
            &mut backend,
            "sip:mama@example.test",
            &b,
            420,
            "audio/wav",
            "f1",
        )
        .unwrap();
        assert_eq!(host.voice_note.payload()["state"], "failed");
        assert!(host
            .send_saved_voice_note(
                &mut backend,
                "sip:mama@example.test",
                &a,
                420,
                "audio/wav",
                "stale"
            )
            .is_err());
        assert!(host.discard_saved_voice_note(&backend, &a).is_err());
        backend.fail_saved_send = false;
        host.send_saved_voice_note(
            &mut backend,
            "sip:mama@example.test",
            &b,
            420,
            "audio/wav",
            "f2",
        )
        .unwrap();
        assert_eq!(backend.saved_sends, 2);
        assert_eq!(backend.sends, 0);
        host.discard_saved_voice_note(&backend, &b).unwrap();
        backend.pending_saved_path = None;
        host.delete_voice_note(&backend, "f2").unwrap();
        assert!(
            std::path::Path::new(&b).exists(),
            "retry metadata still references source"
        );
        host.delete_voice_note(&backend, "f1").unwrap();
        assert!(!std::path::Path::new(&b).exists());
        std::fs::remove_file(a).unwrap();
        std::fs::remove_file(source).unwrap();
    }

    #[test]
    fn copy_failure_retains_finalized_source_for_replacement_host_without_capture() {
        let source = test_directory().join(format!("copy-failure-{}.wav", std::process::id()));
        std::fs::write(&source, sample_wav()).unwrap();
        let mut host = VoipHost::default();
        let mut backend = LocalRecordingBackend {
            started: true,
            ..Default::default()
        };
        host.start_voice_recording(&mut backend, source.to_str().unwrap())
            .unwrap();
        let request = yoyopod_protocol::call::InterruptForCall {
            key: command("sip-incoming-1", 1, CallAction::Answer).key,
            activity_generation: 1,
            voice_activity_generation: 3,
        };
        assert!(host
            .interrupt_for_call_with_copy(&mut backend, &request, |_| Err("disk full".into()))
            .is_err());
        assert!(!backend.recording);
        let (path, duration) = host.draft_recovery_source().expect("owned recovery source");
        assert_eq!(std::fs::read(&path).unwrap(), sample_wav());
        drop(host);
        let mut replacement = VoipHost::default();
        let copied = replacement
            .restore_finalized_source(&path, duration)
            .unwrap();
        replacement
            .send_saved_voice_note(
                &mut backend,
                "sip:mama@example.test",
                &copied,
                duration,
                "audio/wav",
                "recovered",
            )
            .unwrap();
        assert_eq!(backend.saved_sends, 1);
        assert!(!backend.recording);
        assert_eq!(
            replacement.session_snapshot_payload()["restored_draft_source"],
            path
        );
        backend.pending_saved_path = None;
        replacement
            .discard_saved_voice_note(&backend, &copied)
            .unwrap();
        replacement
            .delete_voice_note(&backend, "recovered")
            .unwrap();
        assert!(!source.exists());
    }
    fn state(id: &str, value: &str) -> BackendEvent {
        BackendEvent::CallStateChanged {
            call_id: id.into(),
            state: value.into(),
        }
    }
    fn command(id: &str, generation: u64, action: CallAction) -> CallCommand {
        CallCommand {
            key: SessionKey {
                transport: CallTransport::Sip,
                generation,
                call_id: id.into(),
            },
            action,
        }
    }

    #[test]
    fn incoming_offers_and_secondary_terminal_never_replace_foreground() {
        let mut host = VoipHost::default();
        host.set_worker_generation(7);
        host.call
            .start_outgoing("sip-incoming-1", "sip:primary@example.test");
        host.call.apply_call_state("sip-incoming-1", "connected");
        let mut backend = LocalRecordingBackend::default();
        backend.events = vec![
            incoming("sip-incoming-2"),
            state("sip-incoming-2", "incoming"),
            state("sip-incoming-2", "end"),
        ];
        let events = host.poll_backend_events(&mut backend).unwrap();
        assert_eq!(host.call.active_call_id(), Some("sip-incoming-1"));
        assert_eq!(host.call.state(), "connected");
        assert!(
            matches!(&events[0], BackendEvent::Offer(offer) if offer.key.call_id == "sip-incoming-2" && offer.key.generation == 7)
        );
        assert!(
            matches!(&events[2], BackendEvent::Update(update) if update.phase == CallPhase::Ended && update.sequence == 2)
        );
        let envelope = crate::worker::backend_event_envelope(events[0].clone());
        assert_eq!(envelope.message_type, "call.offer");
    }

    #[test]
    fn admitted_history_and_released_cleanup_are_explicit_and_keyed() {
        let mut host = VoipHost::default();
        host.set_worker_generation(7);
        let mut backend = LocalRecordingBackend::default();
        backend.events = vec![incoming("sip-incoming-1"), incoming("sip-incoming-2")];
        host.poll_backend_events(&mut backend).unwrap();
        assert!(host.call.active_call_id().is_none());
        host.admit_session(&command("sip-incoming-1", 7, CallAction::Answer).key)
            .unwrap();
        assert_eq!(host.call.active_call_id(), Some("sip-incoming-1"));
        assert!(host
            .admit_session(&command("sip-incoming-2", 7, CallAction::Answer).key)
            .is_err());
        backend.events = vec![
            state("sip-incoming-2", "end"),
            state("sip-incoming-2", "released"),
            state("sip-incoming-1", "connected"),
            state("sip-incoming-1", "end"),
        ];
        let events = host.poll_backend_events(&mut backend).unwrap();
        assert!(events
            .iter()
            .any(|e| matches!(e,BackendEvent::Cleanup(key) if key.call_id=="sip-incoming-2")));
        assert!(!events
            .iter()
            .any(|e| matches!(e,BackendEvent::Cleanup(key) if key.call_id=="sip-incoming-1")));
        assert_eq!(host.call.session_payload()["history_outcome"], "completed");
        backend.events = vec![
            state("sip-incoming-1", "released"),
            state("sip-incoming-1", "released"),
        ];
        let events = host.poll_backend_events(&mut backend).unwrap();
        assert_eq!(
            events
                .iter()
                .filter(|e| matches!(e,BackendEvent::Cleanup(key) if key.call_id=="sip-incoming-1"))
                .count(),
            1
        );
    }

    #[test]
    fn targeted_actions_are_fenced_and_do_not_answer_the_other_call() {
        use yoyopod_protocol::call::RejectReason;
        let mut host = VoipHost::default();
        host.set_worker_generation(7);
        let mut backend = LocalRecordingBackend::default();
        backend.events = vec![incoming("sip-incoming-1"), incoming("sip-incoming-2")];
        host.poll_backend_events(&mut backend).unwrap();
        assert_eq!(host.call.active_call_id(), None);
        for cmd in [
            command("sip-incoming-1", 7, CallAction::Answer),
            command("sip-incoming-2", 7, CallAction::Reject(RejectReason::Busy)),
            command("sip-incoming-1", 7, CallAction::Hangup),
        ] {
            host.apply_call(&mut backend, &cmd).unwrap();
        }
        assert_eq!(
            backend
                .commands
                .iter()
                .map(|c| c.key.call_id.as_str())
                .collect::<Vec<_>>(),
            vec!["sip-incoming-1", "sip-incoming-2", "sip-incoming-1"]
        );
        assert!(host
            .apply_call(
                &mut backend,
                &command("sip-incoming-1", 6, CallAction::Answer)
            )
            .is_err());
        assert!(host
            .apply_call(
                &mut backend,
                &command("sip-incoming-99", 7, CallAction::Hangup)
            )
            .is_err());
        backend.events = vec![state("sip-incoming-1", "end")];
        host.poll_backend_events(&mut backend).unwrap();
        assert!(host
            .apply_call(
                &mut backend,
                &command("sip-incoming-1", 7, CallAction::Answer)
            )
            .is_err());
        assert_eq!(backend.commands.len(), 3);
    }

    #[test]
    fn worker_dispatches_targeted_commands_and_reports_stale_requests() {
        use yoyopod_protocol::call::RejectReason;
        let mut host = VoipHost::default();
        let mut backend = LocalRecordingBackend {
            events: vec![incoming("sip-incoming-1"), incoming("sip-incoming-2")],
            ..Default::default()
        };
        let mut commands = vec![
            crate::protocol::WorkerEnvelope::command(
                "voip.configure",
                Some("configure".into()),
                json!({"sip_identity":"", "message_store_dir":"", "worker_generation":7}),
            ),
            crate::protocol::WorkerEnvelope::command(
                "voip.register",
                Some("register".into()),
                json!({}),
            ),
        ];
        for (index, cmd) in [
            command("sip-incoming-1", 7, CallAction::Answer),
            command("sip-incoming-2", 7, CallAction::Reject(RejectReason::Busy)),
            command("sip-incoming-1", 7, CallAction::Hangup),
            command("sip-incoming-1", 6, CallAction::Answer),
            command("missing", 7, CallAction::Answer),
        ]
        .into_iter()
        .enumerate()
        {
            commands.push(crate::protocol::WorkerEnvelope::command(
                "call.action",
                Some(format!("action-{index}")),
                json!(cmd),
            ));
        }
        let input = commands
            .into_iter()
            .map(|c| serde_json::to_string(&c).unwrap())
            .collect::<Vec<_>>()
            .join("\n");
        let mut output = Vec::new();
        crate::worker::run_worker(
            std::io::Cursor::new(input),
            &mut output,
            &mut Vec::new(),
            &mut host,
            &mut backend,
        )
        .unwrap();
        assert_eq!(backend.commands.len(), 3);
        let output = String::from_utf8(output).unwrap();
        assert!(output.contains("call.offer"));
        assert!(output.contains("stale or incorrect call transport generation"));
        assert!(output.contains("unknown call ID"));
    }
    #[test]
    fn early_updates_and_unknown_live_states_preserve_offer_phase_before_answer() {
        let mut host = VoipHost::default();
        let mut backend = LocalRecordingBackend::default();
        backend.events = vec![
            incoming("sip-incoming-3"),
            state("sip-incoming-3", "incoming"),
            state("sip-incoming-3", "early_updated_by_remote"),
            state("sip-incoming-3", "early_updating"),
            state("sip-incoming-3", "transitional"),
        ];
        let events = host.poll_backend_events(&mut backend).unwrap();
        for event in events.into_iter().skip(1) {
            assert!(
                matches!(event, BackendEvent::Update(update) if update.phase == CallPhase::Ringing)
            );
        }
        assert_eq!(host.call.active_call_id(), None);
        assert!(backend.commands.is_empty());
        host.apply_call(
            &mut backend,
            &command("sip-incoming-3", 0, CallAction::Hangup),
        )
        .unwrap();
    }

    #[test]
    fn duplicate_offer_or_late_update_cannot_revive_an_ended_session() {
        let mut host = VoipHost::default();
        let mut backend = LocalRecordingBackend::default();
        backend.events = vec![
            incoming("sip-incoming-2"),
            state("sip-incoming-2", "end"),
            incoming("sip-incoming-2"),
            state("sip-incoming-2", "connected"),
        ];
        let events = host.poll_backend_events(&mut backend).unwrap();
        assert_eq!(
            events
                .iter()
                .filter(|e| matches!(e, BackendEvent::Offer(_)))
                .count(),
            1
        );
        assert_eq!(host.sessions["sip-incoming-2"].phase, CallPhase::Ended);
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

    #[test]
    fn failed_sip_send_remains_in_the_local_replay_queue() {
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
        host.start_voice_recording(&mut backend, "/tmp/local.wav")
            .expect("start local recording");
        let duration_ms = host
            .stop_voice_recording(&mut backend)
            .expect("stop local recording");
        let message_id = host
            .send_voice_note(
                &mut backend,
                "sip:mama@example.test",
                "/tmp/local.wav",
                duration_ms,
                "audio/wav",
                "local-note-1",
            )
            .expect("accept the local note even when SIP delivery fails");

        assert_eq!(message_id, "local-note-1");
        let snapshot = host.session_snapshot_payload();
        assert_eq!(snapshot["voice_note"]["state"], "failed");
        assert_eq!(
            snapshot["voice_notes_by_contact"]["sip:mama@example.test"][0]["message_id"],
            "local-note-1"
        );
        assert_eq!(
            snapshot["voice_notes_by_contact"]["sip:mama@example.test"][0]["delivery_state"],
            "failed"
        );
    }
}
