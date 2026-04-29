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

#[derive(Debug, Default)]
pub struct VoipHost {
    config: Option<VoipConfig>,
    registered: bool,
    active_call_id: Option<String>,
    outbound_message_ids: HashMap<String, String>,
}

impl VoipHost {
    pub fn configure(&mut self, config: VoipConfig) {
        self.config = Some(config);
        self.registered = false;
        self.active_call_id = None;
        self.outbound_message_ids.clear();
    }

    pub fn mark_registered(&mut self, registered: bool) {
        self.registered = registered;
    }

    pub fn set_active_call_id(&mut self, call_id: Option<String>) {
        self.active_call_id = call_id;
    }

    pub fn health_payload(&self) -> serde_json::Value {
        json!({
            "configured": self.config.is_some(),
            "registered": self.registered,
            "active_call_id": self.active_call_id,
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
            .ok_or_else(|| "voip host is not configured".to_string())?;
        backend.start(config)?;
        self.registered = true;
        Ok(())
    }

    pub fn unregister<B: CallBackend>(&mut self, backend: &mut B) {
        backend.stop();
        self.registered = false;
        self.active_call_id = None;
        self.outbound_message_ids.clear();
    }

    pub fn dial<B: CallBackend>(
        &mut self,
        backend: &mut B,
        sip_address: &str,
    ) -> Result<(), String> {
        let call_id = backend.make_call(sip_address)?;
        self.active_call_id = Some(call_id);
        Ok(())
    }

    pub fn answer<B: CallBackend>(&mut self, backend: &mut B) -> Result<(), String> {
        backend.answer_call()
    }

    pub fn reject<B: CallBackend>(&mut self, backend: &mut B) -> Result<(), String> {
        backend.reject_call()?;
        self.active_call_id = None;
        Ok(())
    }

    pub fn hangup<B: CallBackend>(&mut self, backend: &mut B) -> Result<(), String> {
        backend.hangup()?;
        self.active_call_id = None;
        Ok(())
    }

    pub fn set_muted<B: CallBackend>(
        &mut self,
        backend: &mut B,
        muted: bool,
    ) -> Result<(), String> {
        backend.set_muted(muted)
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
        backend.start_voice_recording(file_path)
    }

    pub fn stop_voice_recording<B: CallBackend>(&mut self, backend: &mut B) -> Result<i32, String> {
        backend.stop_voice_recording()
    }

    pub fn cancel_voice_recording<B: CallBackend>(
        &mut self,
        backend: &mut B,
    ) -> Result<(), String> {
        backend.cancel_voice_recording()
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

    fn apply_backend_event(&mut self, event: &BackendEvent) {
        match event {
            BackendEvent::RegistrationChanged { state, .. } => {
                if state == "ok" {
                    self.registered = true;
                } else if matches!(state.as_str(), "failed" | "cleared" | "none") {
                    self.registered = false;
                }
            }
            BackendEvent::IncomingCall { call_id, .. } => {
                self.active_call_id = Some(call_id.clone());
            }
            BackendEvent::CallStateChanged { call_id, state } => {
                if matches!(state.as_str(), "idle" | "released" | "error" | "end") {
                    if self.active_call_id.as_deref() == Some(call_id.as_str())
                        || self.active_call_id.is_none()
                    {
                        self.active_call_id = None;
                    }
                } else {
                    self.active_call_id = Some(call_id.clone());
                }
            }
            BackendEvent::BackendStopped { .. } => {
                self.registered = false;
                self.active_call_id = None;
                self.outbound_message_ids.clear();
            }
            BackendEvent::MessageReceived { .. }
            | BackendEvent::MessageDeliveryChanged { .. }
            | BackendEvent::MessageDownloadCompleted { .. }
            | BackendEvent::MessageFailed { .. } => {}
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
}

fn is_terminal_delivery_state(value: &str) -> bool {
    matches!(value, "delivered" | "failed")
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn config() -> VoipConfig {
        VoipConfig::from_payload(&json!({
            "sip_server": "sip.example.com",
            "sip_identity": "sip:alice@example.com"
        }))
        .unwrap()
    }

    #[test]
    fn health_reports_configured_registered_and_call_id() {
        let mut host = VoipHost::default();
        host.configure(config());
        host.mark_registered(true);
        host.set_active_call_id(Some("call-1".to_string()));

        let payload = host.health_payload();

        assert_eq!(payload["configured"], true);
        assert_eq!(payload["registered"], true);
        assert_eq!(payload["active_call_id"], "call-1");
    }
}

#[cfg(test)]
mod command_tests {
    use super::*;
    use serde_json::json;

    #[derive(Default)]
    struct FakeBackend {
        calls: Vec<String>,
    }

    impl CallBackend for FakeBackend {
        fn start(&mut self, _config: &VoipConfig) -> Result<(), String> {
            self.calls.push("start".to_string());
            Ok(())
        }

        fn stop(&mut self) {
            self.calls.push("stop".to_string());
        }

        fn iterate(&mut self) -> Result<Vec<BackendEvent>, String> {
            Ok(vec![])
        }

        fn make_call(&mut self, sip_address: &str) -> Result<String, String> {
            self.calls.push(format!("dial:{sip_address}"));
            Ok("call-outgoing".to_string())
        }

        fn answer_call(&mut self) -> Result<(), String> {
            self.calls.push("answer".to_string());
            Ok(())
        }

        fn reject_call(&mut self) -> Result<(), String> {
            self.calls.push("reject".to_string());
            Ok(())
        }

        fn hangup(&mut self) -> Result<(), String> {
            self.calls.push("hangup".to_string());
            Ok(())
        }

        fn set_muted(&mut self, muted: bool) -> Result<(), String> {
            self.calls.push(format!("mute:{muted}"));
            Ok(())
        }

        fn send_text_message(&mut self, sip_address: &str, text: &str) -> Result<String, String> {
            self.calls.push(format!("text:{sip_address}:{text}"));
            Ok("backend-msg-1".to_string())
        }

        fn start_voice_recording(&mut self, file_path: &str) -> Result<(), String> {
            self.calls.push(format!("record:{file_path}"));
            Ok(())
        }

        fn stop_voice_recording(&mut self) -> Result<i32, String> {
            self.calls.push("stop_recording".to_string());
            Ok(1250)
        }

        fn cancel_voice_recording(&mut self) -> Result<(), String> {
            self.calls.push("cancel_recording".to_string());
            Ok(())
        }

        fn send_voice_note(
            &mut self,
            sip_address: &str,
            file_path: &str,
            duration_ms: i32,
            mime_type: &str,
        ) -> Result<String, String> {
            self.calls.push(format!(
                "voice:{sip_address}:{file_path}:{duration_ms}:{mime_type}"
            ));
            Ok("backend-vn-1".to_string())
        }
    }

    fn config() -> VoipConfig {
        VoipConfig::from_payload(&json!({
            "sip_server":"sip.example.com",
            "sip_identity":"sip:alice@example.com"
        }))
        .unwrap()
    }

    #[test]
    fn register_starts_backend_and_health_reports_registered() {
        let mut host = VoipHost::default();
        let mut backend = FakeBackend::default();
        host.configure(config());

        host.register(&mut backend).expect("register");

        assert_eq!(backend.calls, vec!["start"]);
        assert_eq!(host.health_payload()["registered"], true);
    }

    #[test]
    fn dial_sets_active_call_id() {
        let mut host = VoipHost::default();
        let mut backend = FakeBackend::default();
        host.configure(config());
        host.register(&mut backend).unwrap();

        host.dial(&mut backend, "sip:bob@example.com")
            .expect("dial");

        assert_eq!(host.health_payload()["active_call_id"], "call-outgoing");
    }

    #[test]
    fn call_commands_forward_to_backend_and_clear_finished_call() {
        let mut host = VoipHost::default();
        let mut backend = FakeBackend::default();
        host.configure(config());
        host.register(&mut backend).unwrap();
        host.dial(&mut backend, "sip:bob@example.com").unwrap();

        host.answer(&mut backend).expect("answer");
        host.set_muted(&mut backend, true).expect("mute");
        host.hangup(&mut backend).expect("hangup");

        assert_eq!(
            backend.calls,
            vec![
                "start",
                "dial:sip:bob@example.com",
                "answer",
                "mute:true",
                "hangup"
            ]
        );
        assert_eq!(
            host.health_payload()["active_call_id"],
            serde_json::Value::Null
        );
    }

    #[test]
    fn send_text_message_returns_client_id_and_maps_delivery_back_to_client_id() {
        struct EventBackend {
            calls: Vec<String>,
            events: Vec<BackendEvent>,
        }

        impl CallBackend for EventBackend {
            fn start(&mut self, _config: &VoipConfig) -> Result<(), String> {
                self.calls.push("start".to_string());
                Ok(())
            }

            fn stop(&mut self) {
                self.calls.push("stop".to_string());
            }

            fn iterate(&mut self) -> Result<Vec<BackendEvent>, String> {
                Ok(std::mem::take(&mut self.events))
            }

            fn make_call(&mut self, _sip_address: &str) -> Result<String, String> {
                Ok("call-outgoing".to_string())
            }

            fn answer_call(&mut self) -> Result<(), String> {
                Ok(())
            }

            fn reject_call(&mut self) -> Result<(), String> {
                Ok(())
            }

            fn hangup(&mut self) -> Result<(), String> {
                Ok(())
            }

            fn set_muted(&mut self, _muted: bool) -> Result<(), String> {
                Ok(())
            }

            fn send_text_message(
                &mut self,
                sip_address: &str,
                text: &str,
            ) -> Result<String, String> {
                self.calls.push(format!("text:{sip_address}:{text}"));
                Ok("backend-msg-1".to_string())
            }

            fn start_voice_recording(&mut self, _file_path: &str) -> Result<(), String> {
                Ok(())
            }

            fn stop_voice_recording(&mut self) -> Result<i32, String> {
                Ok(1250)
            }

            fn cancel_voice_recording(&mut self) -> Result<(), String> {
                Ok(())
            }

            fn send_voice_note(
                &mut self,
                _sip_address: &str,
                _file_path: &str,
                _duration_ms: i32,
                _mime_type: &str,
            ) -> Result<String, String> {
                Ok("backend-vn-1".to_string())
            }
        }

        let mut host = VoipHost::default();
        host.configure(config());
        let mut backend = EventBackend {
            calls: Vec::new(),
            events: Vec::new(),
        };
        host.register(&mut backend).unwrap();

        let message_id = host
            .send_text_message(&mut backend, "sip:bob@example.com", "hello", "client-msg-1")
            .expect("send text");

        assert_eq!(message_id, "client-msg-1");
        assert_eq!(
            backend.calls,
            vec!["start", "text:sip:bob@example.com:hello"]
        );

        backend.events = vec![BackendEvent::MessageDeliveryChanged {
            message_id: "backend-msg-1".to_string(),
            delivery_state: "delivered".to_string(),
            local_file_path: "".to_string(),
            error: "".to_string(),
        }];
        let events = host.poll_backend_events(&mut backend).expect("poll");

        assert_eq!(
            events,
            vec![BackendEvent::MessageDeliveryChanged {
                message_id: "client-msg-1".to_string(),
                delivery_state: "delivered".to_string(),
                local_file_path: "".to_string(),
                error: "".to_string(),
            }]
        );
    }

    #[test]
    fn voice_note_recording_commands_forward_to_backend() {
        let mut host = VoipHost::default();
        let mut backend = FakeBackend::default();
        host.configure(config());
        host.register(&mut backend).unwrap();

        host.start_voice_recording(&mut backend, "/tmp/a.wav")
            .expect("start voice recording");
        let duration_ms = host
            .stop_voice_recording(&mut backend)
            .expect("stop voice recording");
        host.cancel_voice_recording(&mut backend)
            .expect("cancel voice recording");

        assert_eq!(duration_ms, 1250);
        assert_eq!(
            backend.calls,
            vec![
                "start",
                "record:/tmp/a.wav",
                "stop_recording",
                "cancel_recording"
            ]
        );
    }

    #[test]
    fn send_voice_note_returns_client_id_and_maps_delivery_back_to_client_id() {
        let mut host = VoipHost::default();
        let mut backend = FakeBackend::default();
        host.configure(config());
        host.register(&mut backend).unwrap();

        let message_id = host
            .send_voice_note(
                &mut backend,
                "sip:bob@example.com",
                "/tmp/a.wav",
                1250,
                "audio/wav",
                "client-vn-1",
            )
            .expect("send voice note");

        assert_eq!(message_id, "client-vn-1");
        assert_eq!(
            backend.calls,
            vec![
                "start",
                "voice:sip:bob@example.com:/tmp/a.wav:1250:audio/wav"
            ]
        );

        struct EventBackend {
            events: Vec<BackendEvent>,
        }

        impl CallBackend for EventBackend {
            fn start(&mut self, _config: &VoipConfig) -> Result<(), String> {
                Ok(())
            }

            fn stop(&mut self) {}

            fn iterate(&mut self) -> Result<Vec<BackendEvent>, String> {
                Ok(std::mem::take(&mut self.events))
            }

            fn make_call(&mut self, _sip_address: &str) -> Result<String, String> {
                Ok("call-outgoing".to_string())
            }

            fn answer_call(&mut self) -> Result<(), String> {
                Ok(())
            }

            fn reject_call(&mut self) -> Result<(), String> {
                Ok(())
            }

            fn hangup(&mut self) -> Result<(), String> {
                Ok(())
            }

            fn set_muted(&mut self, _muted: bool) -> Result<(), String> {
                Ok(())
            }

            fn send_text_message(
                &mut self,
                _sip_address: &str,
                _text: &str,
            ) -> Result<String, String> {
                Ok("backend-msg-1".to_string())
            }

            fn start_voice_recording(&mut self, _file_path: &str) -> Result<(), String> {
                Ok(())
            }

            fn stop_voice_recording(&mut self) -> Result<i32, String> {
                Ok(1250)
            }

            fn cancel_voice_recording(&mut self) -> Result<(), String> {
                Ok(())
            }

            fn send_voice_note(
                &mut self,
                _sip_address: &str,
                _file_path: &str,
                _duration_ms: i32,
                _mime_type: &str,
            ) -> Result<String, String> {
                Ok("backend-vn-1".to_string())
            }
        }

        let mut event_backend = EventBackend {
            events: vec![BackendEvent::MessageDeliveryChanged {
                message_id: "backend-vn-1".to_string(),
                delivery_state: "delivered".to_string(),
                local_file_path: "/tmp/a.wav".to_string(),
                error: "".to_string(),
            }],
        };

        let events = host
            .poll_backend_events(&mut event_backend)
            .expect("poll voice note delivery");

        assert_eq!(
            events,
            vec![BackendEvent::MessageDeliveryChanged {
                message_id: "client-vn-1".to_string(),
                delivery_state: "delivered".to_string(),
                local_file_path: "/tmp/a.wav".to_string(),
                error: "".to_string(),
            }]
        );
    }

    #[test]
    fn reject_and_unregister_clear_state() {
        let mut host = VoipHost::default();
        let mut backend = FakeBackend::default();
        host.configure(config());
        host.register(&mut backend).unwrap();
        host.dial(&mut backend, "sip:bob@example.com").unwrap();

        host.reject(&mut backend).expect("reject");
        host.unregister(&mut backend);

        assert_eq!(
            backend.calls,
            vec!["start", "dial:sip:bob@example.com", "reject", "stop"]
        );
        assert_eq!(host.health_payload()["registered"], false);
        assert_eq!(
            host.health_payload()["active_call_id"],
            serde_json::Value::Null
        );
    }

    #[test]
    fn poll_backend_events_updates_registration_and_call_state() {
        struct EventBackend {
            events: Vec<BackendEvent>,
        }

        impl CallBackend for EventBackend {
            fn start(&mut self, _config: &VoipConfig) -> Result<(), String> {
                Ok(())
            }

            fn stop(&mut self) {}

            fn iterate(&mut self) -> Result<Vec<BackendEvent>, String> {
                Ok(std::mem::take(&mut self.events))
            }

            fn make_call(&mut self, _sip_address: &str) -> Result<String, String> {
                Ok("call-outgoing".to_string())
            }

            fn answer_call(&mut self) -> Result<(), String> {
                Ok(())
            }

            fn reject_call(&mut self) -> Result<(), String> {
                Ok(())
            }

            fn hangup(&mut self) -> Result<(), String> {
                Ok(())
            }

            fn set_muted(&mut self, _muted: bool) -> Result<(), String> {
                Ok(())
            }

            fn send_text_message(
                &mut self,
                _sip_address: &str,
                _text: &str,
            ) -> Result<String, String> {
                Ok("backend-msg-1".to_string())
            }

            fn start_voice_recording(&mut self, _file_path: &str) -> Result<(), String> {
                Ok(())
            }

            fn stop_voice_recording(&mut self) -> Result<i32, String> {
                Ok(1250)
            }

            fn cancel_voice_recording(&mut self) -> Result<(), String> {
                Ok(())
            }

            fn send_voice_note(
                &mut self,
                _sip_address: &str,
                _file_path: &str,
                _duration_ms: i32,
                _mime_type: &str,
            ) -> Result<String, String> {
                Ok("backend-vn-1".to_string())
            }
        }

        let mut host = VoipHost::default();
        host.configure(config());
        let mut backend = EventBackend {
            events: vec![
                BackendEvent::RegistrationChanged {
                    state: "ok".to_string(),
                    reason: "".to_string(),
                },
                BackendEvent::IncomingCall {
                    call_id: "call-1".to_string(),
                    from_uri: "sip:bob@example.com".to_string(),
                },
                BackendEvent::CallStateChanged {
                    call_id: "call-1".to_string(),
                    state: "released".to_string(),
                },
            ],
        };

        let events = host.poll_backend_events(&mut backend).expect("poll");

        assert_eq!(events.len(), 3);
        assert_eq!(host.health_payload()["registered"], true);
        assert_eq!(
            host.health_payload()["active_call_id"],
            serde_json::Value::Null
        );
    }

    #[test]
    fn iterate_interval_comes_from_config() {
        let mut host = VoipHost::default();
        host.configure(
            VoipConfig::from_payload(&json!({
                "sip_server":"sip.example.com",
                "sip_identity":"sip:alice@example.com",
                "iterate_interval_ms": 37
            }))
            .unwrap(),
        );

        assert_eq!(host.iterate_interval_ms(), 37);
    }
}
