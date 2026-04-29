use crate::calls::CallSession;
use crate::config::VoipConfig;
use crate::lifecycle::LifecycleState;
use crate::messages::{is_terminal_delivery_state, MessageSessionState, OutboundMessageIds};
use crate::runtime_snapshot::RuntimeSnapshot;
use crate::voice_notes::VoiceNoteSession;
use serde_json::json;

pub use crate::lifecycle::LifecycleEvent;
pub use crate::messages::MessageRecord;

pub trait CallBackend {
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
    registered: bool,
    registration_state: String,
    lifecycle: LifecycleState,
    call: CallSession,
    voice_note: VoiceNoteSession,
    last_message: Option<MessageSessionState>,
    outbound_message_ids: OutboundMessageIds,
}

impl Default for VoipHost {
    fn default() -> Self {
        Self {
            config: None,
            registered: false,
            registration_state: "none".to_string(),
            lifecycle: LifecycleState::default(),
            call: CallSession::default(),
            voice_note: VoiceNoteSession::default(),
            last_message: None,
            outbound_message_ids: OutboundMessageIds::default(),
        }
    }
}

impl VoipHost {
    pub fn configure(&mut self, config: VoipConfig) {
        self.config = Some(config);
        self.registered = false;
        self.registration_state = "none".to_string();
        self.lifecycle.clear_recovery_pending();
        self.lifecycle.record("configured", "configured", false);
        self.call.clear();
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
            "backend_available": self.lifecycle.backend_available(self.registered),
        })
    }

    pub fn lifecycle_payload(&self) -> serde_json::Value {
        self.lifecycle.payload(self.registered)
    }

    pub fn session_snapshot_payload(&self) -> serde_json::Value {
        RuntimeSnapshot {
            configured: self.config.is_some(),
            registered: self.registered,
            registration_state: &self.registration_state,
            lifecycle: &self.lifecycle,
            call: &self.call,
            voice_note: &self.voice_note,
            last_message: self.last_message.as_ref(),
            pending_outbound_messages: self.outbound_message_ids.len(),
        }
        .payload()
    }

    pub fn iterate_interval_ms(&self) -> u64 {
        self.config
            .as_ref()
            .map(|config| config.iterate_interval_ms.max(1))
            .unwrap_or(20)
    }

    pub fn register<B: CallBackend>(&mut self, backend: &mut B) -> Result<(), String> {
        let config = self
            .config
            .as_ref()
            .ok_or_else(|| "voip host is not configured".to_string())?
            .clone();
        self.lifecycle.record("registering", "registering", false);
        if let Err(error) = backend.start(&config) {
            self.registered = false;
            self.registration_state = "failed".to_string();
            self.lifecycle.mark_recovery_pending();
            self.lifecycle.record("failed", &error, false);
            return Err(error);
        }
        self.registered = true;
        self.registration_state = "none".to_string();
        let recovered = self.lifecycle.recovery_pending();
        self.lifecycle.clear_recovery_pending();
        self.lifecycle.record("registered", "registered", recovered);
        Ok(())
    }

    pub fn unregister<B: CallBackend>(&mut self, backend: &mut B) {
        backend.stop();
        self.registered = false;
        self.registration_state = "none".to_string();
        self.lifecycle.clear_recovery_pending();
        self.lifecycle.record("stopped", "unregistered", false);
        self.call.clear();
        self.voice_note.reset();
        self.outbound_message_ids.clear();
    }

    pub fn dial<B: CallBackend>(
        &mut self,
        backend: &mut B,
        sip_address: &str,
    ) -> Result<(), String> {
        let call_id = backend.make_call(sip_address)?;
        self.call.start_outgoing(&call_id, sip_address);
        Ok(())
    }

    pub fn answer<B: CallBackend>(&mut self, backend: &mut B) -> Result<(), String> {
        backend.answer_call()
    }

    pub fn reject<B: CallBackend>(&mut self, backend: &mut B) -> Result<(), String> {
        backend.reject_call()?;
        self.call.clear_with_state_and_action("released", "reject");
        Ok(())
    }

    pub fn hangup<B: CallBackend>(&mut self, backend: &mut B) -> Result<(), String> {
        backend.hangup()?;
        self.call.clear_with_state_and_action("released", "hangup");
        Ok(())
    }

    pub fn set_muted<B: CallBackend>(
        &mut self,
        backend: &mut B,
        muted: bool,
    ) -> Result<(), String> {
        backend.set_muted(muted)?;
        self.call.set_muted(muted);
        Ok(())
    }

    pub fn send_text_message<B: CallBackend>(
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
        Ok(client_id.to_string())
    }

    pub fn start_voice_recording<B: CallBackend>(
        &mut self,
        backend: &mut B,
        file_path: &str,
    ) -> Result<(), String> {
        backend.start_voice_recording(file_path)?;
        self.voice_note.start_recording(file_path);
        Ok(())
    }

    pub fn stop_voice_recording<B: CallBackend>(&mut self, backend: &mut B) -> Result<i32, String> {
        let duration_ms = backend.stop_voice_recording()?;
        self.voice_note.finish_recording(duration_ms);
        Ok(duration_ms)
    }

    pub fn cancel_voice_recording<B: CallBackend>(
        &mut self,
        backend: &mut B,
    ) -> Result<(), String> {
        backend.cancel_voice_recording()?;
        self.voice_note.reset();
        Ok(())
    }

    pub fn send_voice_note<B: CallBackend>(
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
        Ok(client_id.to_string())
    }

    pub fn poll_backend_events<B: CallBackend>(
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
                self.call.apply_call_state(call_id, state);
            }
            BackendEvent::BackendStopped { reason } => {
                self.registered = false;
                self.registration_state = "failed".to_string();
                self.lifecycle.mark_recovery_pending();
                self.lifecycle.record("failed", reason, false);
                self.call.clear_with_state("error");
                self.outbound_message_ids.clear();
            }
            BackendEvent::MessageReceived { message } => {
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
                self.voice_note
                    .apply_download(message_id, local_file_path, mime_type);
            }
            BackendEvent::MessageFailed { message_id, reason } => {
                self.last_message = Some(MessageSessionState::failed(message_id, reason));
                self.voice_note.fail(message_id);
            }
        }
    }

    fn translate_backend_event(&mut self, event: BackendEvent) -> BackendEvent {
        match event {
            BackendEvent::MessageReceived { mut message } => {
                message.message_id = self.translate_message_id(&message.message_id, false);
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
}
