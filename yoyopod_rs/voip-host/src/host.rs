use crate::config::VoipConfig;
use serde_json::json;
use std::collections::HashMap;

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
pub struct MessageRecord {
    pub message_id: String,
    pub peer_sip_address: String,
    pub sender_sip_address: String,
    pub recipient_sip_address: String,
    pub kind: String,
    pub direction: String,
    pub delivery_state: String,
    pub text: String,
    pub local_file_path: String,
    pub mime_type: String,
    pub duration_ms: i32,
    pub unread: bool,
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LifecycleEvent {
    pub state: String,
    pub previous_state: String,
    pub reason: String,
    pub recovered: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct VoiceNoteSessionState {
    state: String,
    file_path: String,
    duration_ms: i32,
    mime_type: String,
    message_id: String,
}

impl Default for VoiceNoteSessionState {
    fn default() -> Self {
        Self {
            state: "idle".to_string(),
            file_path: String::new(),
            duration_ms: 0,
            mime_type: String::new(),
            message_id: String::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct MessageSessionState {
    message_id: String,
    kind: String,
    direction: String,
    delivery_state: String,
    local_file_path: String,
    error: String,
}

#[derive(Debug)]
pub struct VoipHost {
    config: Option<VoipConfig>,
    registered: bool,
    registration_state: String,
    lifecycle_state: String,
    lifecycle_reason: String,
    recovery_pending: bool,
    lifecycle_events: Vec<LifecycleEvent>,
    call_state: String,
    active_call_id: Option<String>,
    active_call_peer: String,
    muted: bool,
    voice_note: VoiceNoteSessionState,
    last_message: Option<MessageSessionState>,
    outbound_message_ids: HashMap<String, String>,
}

impl Default for VoipHost {
    fn default() -> Self {
        Self {
            config: None,
            registered: false,
            registration_state: "none".to_string(),
            lifecycle_state: "unconfigured".to_string(),
            lifecycle_reason: String::new(),
            recovery_pending: false,
            lifecycle_events: Vec::new(),
            call_state: "idle".to_string(),
            active_call_id: None,
            active_call_peer: String::new(),
            muted: false,
            voice_note: VoiceNoteSessionState::default(),
            last_message: None,
            outbound_message_ids: HashMap::new(),
        }
    }
}

impl VoipHost {
    pub fn configure(&mut self, config: VoipConfig) {
        self.config = Some(config);
        self.registered = false;
        self.registration_state = "none".to_string();
        self.recovery_pending = false;
        self.record_lifecycle("configured", "configured", false);
        self.call_state = "idle".to_string();
        self.active_call_id = None;
        self.active_call_peer.clear();
        self.muted = false;
        self.voice_note = VoiceNoteSessionState::default();
        self.last_message = None;
        self.outbound_message_ids.clear();
    }

    pub fn mark_registered(&mut self, registered: bool) {
        self.registered = registered;
        self.registration_state = if registered { "ok" } else { "none" }.to_string();
        if registered {
            self.record_lifecycle("registered", "registered", false);
        }
    }

    pub fn set_active_call_id(&mut self, call_id: Option<String>) {
        self.active_call_id = call_id;
    }

    pub fn health_payload(&self) -> serde_json::Value {
        json!({
            "configured": self.config.is_some(),
            "registered": self.registered,
            "active_call_id": self.active_call_id,
            "lifecycle_state": self.lifecycle_state,
            "lifecycle_reason": self.lifecycle_reason,
            "backend_available": self.registered && self.lifecycle_state == "registered",
        })
    }

    pub fn lifecycle_payload(&self) -> serde_json::Value {
        json!({
            "state": self.lifecycle_state,
            "reason": self.lifecycle_reason,
            "backend_available": self.registered && self.lifecycle_state == "registered",
        })
    }

    pub fn session_snapshot_payload(&self) -> serde_json::Value {
        let last_message = self
            .last_message
            .as_ref()
            .map(|message| {
                json!({
                    "message_id": message.message_id,
                    "kind": message.kind,
                    "direction": message.direction,
                    "delivery_state": message.delivery_state,
                    "local_file_path": message.local_file_path,
                    "error": message.error,
                })
            })
            .unwrap_or(serde_json::Value::Null);
        json!({
            "configured": self.config.is_some(),
            "registered": self.registered,
            "registration_state": self.registration_state,
            "lifecycle": self.lifecycle_payload(),
            "call_state": self.call_state,
            "active_call_id": self.active_call_id,
            "active_call_peer": self.active_call_peer,
            "muted": self.muted,
            "pending_outbound_messages": self.outbound_message_ids.len(),
            "voice_note": {
                "state": self.voice_note.state,
                "file_path": self.voice_note.file_path,
                "duration_ms": self.voice_note.duration_ms,
                "mime_type": self.voice_note.mime_type,
                "message_id": self.voice_note.message_id,
            },
            "last_message": last_message,
        })
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
        self.record_lifecycle("registering", "registering", false);
        if let Err(error) = backend.start(&config) {
            self.registered = false;
            self.registration_state = "failed".to_string();
            self.recovery_pending = true;
            self.record_lifecycle("failed", &error, false);
            return Err(error);
        }
        self.registered = true;
        self.registration_state = "none".to_string();
        let recovered = self.recovery_pending;
        self.recovery_pending = false;
        self.record_lifecycle("registered", "registered", recovered);
        Ok(())
    }

    pub fn unregister<B: CallBackend>(&mut self, backend: &mut B) {
        backend.stop();
        self.registered = false;
        self.registration_state = "none".to_string();
        self.recovery_pending = false;
        self.record_lifecycle("stopped", "unregistered", false);
        self.call_state = "idle".to_string();
        self.active_call_id = None;
        self.active_call_peer.clear();
        self.muted = false;
        self.voice_note = VoiceNoteSessionState::default();
        self.outbound_message_ids.clear();
    }

    pub fn dial<B: CallBackend>(
        &mut self,
        backend: &mut B,
        sip_address: &str,
    ) -> Result<(), String> {
        let call_id = backend.make_call(sip_address)?;
        self.active_call_id = Some(call_id);
        self.active_call_peer = sip_address.to_string();
        self.call_state = "outgoing_init".to_string();
        Ok(())
    }

    pub fn answer<B: CallBackend>(&mut self, backend: &mut B) -> Result<(), String> {
        backend.answer_call()
    }

    pub fn reject<B: CallBackend>(&mut self, backend: &mut B) -> Result<(), String> {
        backend.reject_call()?;
        self.active_call_id = None;
        self.active_call_peer.clear();
        self.call_state = "released".to_string();
        self.muted = false;
        Ok(())
    }

    pub fn hangup<B: CallBackend>(&mut self, backend: &mut B) -> Result<(), String> {
        backend.hangup()?;
        self.active_call_id = None;
        self.active_call_peer.clear();
        self.call_state = "released".to_string();
        self.muted = false;
        Ok(())
    }

    pub fn set_muted<B: CallBackend>(
        &mut self,
        backend: &mut B,
        muted: bool,
    ) -> Result<(), String> {
        backend.set_muted(muted)?;
        self.muted = muted;
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
        self.remember_outbound_message_id(&backend_id, client_id, "voip text message")?;
        Ok(client_id.to_string())
    }

    pub fn start_voice_recording<B: CallBackend>(
        &mut self,
        backend: &mut B,
        file_path: &str,
    ) -> Result<(), String> {
        backend.start_voice_recording(file_path)?;
        self.voice_note = VoiceNoteSessionState {
            state: "recording".to_string(),
            file_path: file_path.to_string(),
            duration_ms: 0,
            mime_type: "audio/wav".to_string(),
            message_id: String::new(),
        };
        Ok(())
    }

    pub fn stop_voice_recording<B: CallBackend>(&mut self, backend: &mut B) -> Result<i32, String> {
        let duration_ms = backend.stop_voice_recording()?;
        self.voice_note.state = "recorded".to_string();
        self.voice_note.duration_ms = duration_ms;
        Ok(duration_ms)
    }

    pub fn cancel_voice_recording<B: CallBackend>(
        &mut self,
        backend: &mut B,
    ) -> Result<(), String> {
        backend.cancel_voice_recording()?;
        self.voice_note = VoiceNoteSessionState::default();
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
        self.remember_outbound_message_id(&backend_id, client_id, "voip voice note")?;
        self.voice_note = VoiceNoteSessionState {
            state: "sending".to_string(),
            file_path: file_path.to_string(),
            duration_ms,
            mime_type: mime_type.to_string(),
            message_id: client_id.to_string(),
        };
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
        std::mem::take(&mut self.lifecycle_events)
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
                self.active_call_id = Some(call_id.clone());
                self.active_call_peer = from_uri.clone();
                self.call_state = "incoming".to_string();
            }
            BackendEvent::CallStateChanged { call_id, state } => {
                self.call_state = state.clone();
                if matches!(state.as_str(), "idle" | "released" | "error" | "end") {
                    if self.active_call_id.as_deref() == Some(call_id.as_str())
                        || self.active_call_id.is_none()
                    {
                        self.active_call_id = None;
                        self.active_call_peer.clear();
                        self.muted = false;
                    }
                } else {
                    self.active_call_id = Some(call_id.clone());
                }
            }
            BackendEvent::BackendStopped { reason } => {
                self.registered = false;
                self.registration_state = "failed".to_string();
                self.recovery_pending = true;
                self.record_lifecycle("failed", reason, false);
                self.call_state = "idle".to_string();
                self.active_call_id = None;
                self.active_call_peer.clear();
                self.muted = false;
                self.outbound_message_ids.clear();
            }
            BackendEvent::MessageReceived { message } => {
                self.last_message = Some(MessageSessionState {
                    message_id: message.message_id.clone(),
                    kind: message.kind.clone(),
                    direction: message.direction.clone(),
                    delivery_state: message.delivery_state.clone(),
                    local_file_path: message.local_file_path.clone(),
                    error: String::new(),
                });
            }
            BackendEvent::MessageDeliveryChanged {
                message_id,
                delivery_state,
                local_file_path,
                error,
            } => {
                self.last_message = Some(MessageSessionState {
                    message_id: message_id.clone(),
                    kind: String::new(),
                    direction: String::new(),
                    delivery_state: delivery_state.clone(),
                    local_file_path: local_file_path.clone(),
                    error: error.clone(),
                });
                if self.voice_note.message_id == *message_id {
                    self.voice_note.state = match delivery_state.as_str() {
                        "failed" => "failed",
                        "sent" | "delivered" => "sent",
                        _ => "sending",
                    }
                    .to_string();
                }
            }
            BackendEvent::MessageDownloadCompleted {
                message_id,
                local_file_path,
                mime_type,
            } => {
                self.last_message = Some(MessageSessionState {
                    message_id: message_id.clone(),
                    kind: String::new(),
                    direction: String::new(),
                    delivery_state: "delivered".to_string(),
                    local_file_path: local_file_path.clone(),
                    error: String::new(),
                });
                if self.voice_note.message_id == *message_id {
                    self.voice_note.file_path = local_file_path.clone();
                    self.voice_note.mime_type = mime_type.clone();
                }
            }
            BackendEvent::MessageFailed { message_id, reason } => {
                self.last_message = Some(MessageSessionState {
                    message_id: message_id.clone(),
                    kind: String::new(),
                    direction: String::new(),
                    delivery_state: "failed".to_string(),
                    local_file_path: String::new(),
                    error: reason.clone(),
                });
                if self.voice_note.message_id == *message_id {
                    self.voice_note.state = "failed".to_string();
                }
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
        let client_id = self.outbound_message_ids.get(backend_id).cloned();
        if terminal && client_id.is_some() {
            self.outbound_message_ids.remove(backend_id);
        }
        client_id.unwrap_or_else(|| backend_id.to_string())
    }

    fn remember_outbound_message_id(
        &mut self,
        backend_id: &str,
        client_id: &str,
        label: &str,
    ) -> Result<(), String> {
        let backend_id = backend_id.trim();
        if backend_id.is_empty() {
            return Err(format!("{label} backend returned empty message id"));
        }
        if backend_id != client_id {
            self.outbound_message_ids
                .insert(backend_id.to_string(), client_id.to_string());
        }
        Ok(())
    }

    fn record_lifecycle(&mut self, state: &str, reason: &str, recovered: bool) {
        let previous_state = self.lifecycle_state.clone();
        let state = state.to_string();
        let reason = reason.to_string();
        self.lifecycle_state = state.clone();
        self.lifecycle_reason = reason.clone();
        self.lifecycle_events.push(LifecycleEvent {
            state,
            previous_state,
            reason,
            recovered,
        });
    }
}

fn is_terminal_delivery_state(value: &str) -> bool {
    matches!(value, "delivered" | "failed")
}
