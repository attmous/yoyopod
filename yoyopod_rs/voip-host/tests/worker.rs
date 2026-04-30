mod support;

use serde_json::json;
use std::io::{BufReader, Cursor, Read};
use std::thread;
use std::time::Duration;
use support::{config, FakeBackend};
use yoyopod_voip_host::config::VoipConfig;
use yoyopod_voip_host::host::{BackendEvent, MessageRecord, VoipHost, VoipRuntimeBackend};
use yoyopod_voip_host::protocol::{EnvelopeKind, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};
use yoyopod_voip_host::worker::{backend_event_envelope, backend_event_envelopes, run_worker};

#[test]
fn backend_events_map_to_worker_envelopes() {
    let envelope = backend_event_envelope(BackendEvent::IncomingCall {
        call_id: "call-1".to_string(),
        from_uri: "sip:bob@example.com".to_string(),
    });

    assert_eq!(envelope.message_type, "voip.incoming_call");
    assert_eq!(envelope.payload["call_id"], "call-1");
    assert_eq!(envelope.payload["from_uri"], "sip:bob@example.com");
}

#[test]
fn run_worker_uses_injected_io_and_backend() {
    let commands = [
        command(
            "voip.configure",
            "configure-1",
            json!({
                "sip_server": "sip.example.com",
                "sip_identity": "sip:alice@example.com"
            }),
        ),
        command("voip.register", "register-1", json!({})),
        command("worker.stop", "stop-1", json!({})),
    ];
    let mut input = Vec::new();
    for envelope in commands {
        input.extend(envelope.encode().expect("encode command"));
    }
    let mut output = Vec::new();
    let mut errors = Vec::new();
    let mut host = VoipHost::default();
    let mut backend = FakeBackend::default();

    run_worker(
        Cursor::new(input),
        &mut output,
        &mut errors,
        &mut host,
        &mut backend,
    )
    .expect("worker should run");

    let output = String::from_utf8(output).expect("utf8 output");
    let envelopes: Vec<WorkerEnvelope> = output
        .lines()
        .map(|line| WorkerEnvelope::decode(line.as_bytes()).expect("decode output"))
        .collect();

    assert_eq!(backend.calls, vec!["start", "stop"]);
    assert!(errors.is_empty());
    assert_eq!(envelopes[0].message_type, "voip.ready");
    assert!(envelopes
        .iter()
        .any(|envelope| envelope.message_type == "voip.configure"
            && envelope.kind == EnvelopeKind::Result));
    assert!(envelopes
        .iter()
        .any(|envelope| envelope.message_type == "voip.register"
            && envelope.kind == EnvelopeKind::Result));
    assert!(envelopes
        .iter()
        .any(|envelope| envelope.message_type == "worker.stop"
            && envelope.kind == EnvelopeKind::Result));
}

#[test]
fn run_worker_polls_backend_while_stdin_is_idle() {
    let commands = [
        command(
            "voip.configure",
            "configure-1",
            json!({
                "sip_server": "sip.example.com",
                "sip_identity": "sip:alice@example.com",
                "iterate_interval_ms": 10
            }),
        ),
        command("voip.register", "register-1", json!({})),
    ];
    let mut input = Vec::new();
    for envelope in commands {
        input.extend(envelope.encode().expect("encode command"));
    }

    let reader = BufReader::new(DelayedEofReader::new(input, Duration::from_millis(80)));
    let mut output = Vec::new();
    let mut errors = Vec::new();
    let mut host = VoipHost::default();
    let mut backend = IdleThenRegistrationBackend::default();

    run_worker(reader, &mut output, &mut errors, &mut host, &mut backend)
        .expect("worker should run");

    let envelopes: Vec<WorkerEnvelope> = String::from_utf8(output)
        .expect("utf8 output")
        .lines()
        .map(|line| WorkerEnvelope::decode(line.as_bytes()).expect("decode output"))
        .collect();

    assert!(errors.is_empty());
    assert!(
        backend.iterations >= 2,
        "worker must keep polling after register even when stdin is quiet"
    );
    assert!(envelopes.iter().any(|envelope| {
        envelope.message_type == "voip.registration_changed" && envelope.payload["state"] == "ok"
    }));
}

#[test]
fn message_events_map_to_worker_envelopes() {
    let envelope = backend_event_envelope(BackendEvent::MessageReceived {
        message: MessageRecord {
            message_id: "msg-1".to_string(),
            peer_sip_address: "sip:bob@example.com".to_string(),
            sender_sip_address: "sip:bob@example.com".to_string(),
            recipient_sip_address: "sip:alice@example.com".to_string(),
            kind: "text".to_string(),
            direction: "incoming".to_string(),
            delivery_state: "delivered".to_string(),
            text: "hello".to_string(),
            local_file_path: "".to_string(),
            mime_type: "".to_string(),
            duration_ms: 0,
            unread: true,
        },
    });

    assert_eq!(envelope.message_type, "voip.message_received");
    assert_eq!(envelope.payload["message_id"], "msg-1");
    assert_eq!(envelope.payload["kind"], "text");
    assert_eq!(envelope.payload["text"], "hello");
}

#[test]
fn backend_event_batch_appends_canonical_snapshot() {
    let mut host = VoipHost::default();
    host.configure(config());
    host.mark_registered(true);

    let envelopes = backend_event_envelopes(
        vec![BackendEvent::RegistrationChanged {
            state: "ok".to_string(),
            reason: "".to_string(),
        }],
        vec![],
        &host,
    );

    assert_eq!(envelopes.len(), 2);
    assert_eq!(envelopes[0].message_type, "voip.registration_changed");
    assert_eq!(envelopes[1].message_type, "voip.snapshot");
    assert_eq!(envelopes[1].payload["registered"], true);
    assert_eq!(envelopes[1].payload["registration_state"], "ok");
}

#[test]
fn backend_event_batch_appends_lifecycle_before_snapshot() {
    let mut host = VoipHost::default();
    host.configure(config());
    host.take_lifecycle_events();
    let mut backend = FakeBackend {
        events: vec![BackendEvent::BackendStopped {
            reason: "iterate failed".to_string(),
        }],
        ..FakeBackend::default()
    };
    let events = host.poll_backend_events(&mut backend).expect("poll");

    let envelopes = backend_event_envelopes(events, host.take_lifecycle_events(), &host);

    assert_eq!(envelopes.len(), 3);
    assert_eq!(envelopes[0].message_type, "voip.backend_stopped");
    assert_eq!(envelopes[1].message_type, "voip.lifecycle_changed");
    assert_eq!(envelopes[1].payload["state"], "failed");
    assert_eq!(envelopes[1].payload["reason"], "iterate failed");
    assert_eq!(envelopes[2].message_type, "voip.snapshot");
    assert_eq!(envelopes[2].payload["lifecycle"]["state"], "failed");
}

#[test]
fn worker_stop_uses_shutdown_path() {
    let mut host = VoipHost::default();
    let mut backend = FakeBackend::default();

    let envelopes = run_worker_commands(
        &mut host,
        &mut backend,
        &[command("worker.stop", "stop-1", json!({}))],
    );

    assert!(envelopes
        .iter()
        .any(|envelope| envelope.message_type == "worker.stop"
            && envelope.kind == EnvelopeKind::Result));
}

#[test]
fn mark_voice_notes_seen_command_updates_snapshot_summary() {
    let mut host = VoipHost::default();
    host.configure(config());
    let mut backend = FakeBackend {
        events: vec![BackendEvent::MessageReceived {
            message: MessageRecord {
                message_id: "note-1".to_string(),
                peer_sip_address: "sip:mom@example.com".to_string(),
                sender_sip_address: "sip:mom@example.com".to_string(),
                recipient_sip_address: "sip:alice@example.com".to_string(),
                kind: "voice_note".to_string(),
                direction: "incoming".to_string(),
                delivery_state: "delivered".to_string(),
                text: String::new(),
                local_file_path: "/tmp/note.wav".to_string(),
                mime_type: "audio/wav".to_string(),
                duration_ms: 1000,
                unread: true,
            },
        }],
        ..FakeBackend::default()
    };
    host.poll_backend_events(&mut backend)
        .expect("incoming message");
    let mut backend = FakeBackend::default();

    run_worker_commands(
        &mut host,
        &mut backend,
        &[command(
            "voip.mark_voice_notes_seen",
            "mark-seen-1",
            json!({"uri": "sip:mom@example.com"}),
        )],
    );

    assert_eq!(host.session_snapshot_payload()["unread_voice_notes"], 0);
}

#[test]
fn mark_call_history_seen_command_updates_snapshot_summary() {
    let mut host = VoipHost::default();
    host.configure(config());
    let mut backend = FakeBackend {
        events: vec![
            BackendEvent::IncomingCall {
                call_id: "sip:mom@example.com".to_string(),
                from_uri: "sip:mom@example.com".to_string(),
            },
            BackendEvent::CallStateChanged {
                call_id: "sip:mom@example.com".to_string(),
                state: "end".to_string(),
            },
        ],
        ..FakeBackend::default()
    };
    host.poll_backend_events(&mut backend)
        .expect("incoming call");
    let mut backend = FakeBackend::default();

    run_worker_commands(
        &mut host,
        &mut backend,
        &[command(
            "voip.mark_call_history_seen",
            "mark-history-1",
            json!({"uri": ""}),
        )],
    );

    assert_eq!(host.session_snapshot_payload()["unseen_call_history"], 0);
}

fn run_worker_commands(
    host: &mut VoipHost,
    backend: &mut FakeBackend,
    commands: &[WorkerEnvelope],
) -> Vec<WorkerEnvelope> {
    let mut input = Vec::new();
    for envelope in commands {
        input.extend(envelope.encode().expect("encode command"));
    }
    let mut output = Vec::new();
    let mut errors = Vec::new();

    run_worker(Cursor::new(input), &mut output, &mut errors, host, backend)
        .expect("worker should run commands");

    assert!(errors.is_empty());
    String::from_utf8(output)
        .expect("utf8 output")
        .lines()
        .map(|line| WorkerEnvelope::decode(line.as_bytes()).expect("decode output"))
        .collect()
}

fn command(message_type: &str, request_id: &str, payload: serde_json::Value) -> WorkerEnvelope {
    WorkerEnvelope {
        schema_version: SUPPORTED_SCHEMA_VERSION,
        kind: EnvelopeKind::Command,
        message_type: message_type.to_string(),
        request_id: Some(request_id.to_string()),
        timestamp_ms: 0,
        deadline_ms: 0,
        payload,
    }
}

struct DelayedEofReader {
    cursor: Cursor<Vec<u8>>,
    eof_delay: Duration,
    delayed: bool,
}

impl DelayedEofReader {
    fn new(input: Vec<u8>, eof_delay: Duration) -> Self {
        Self {
            cursor: Cursor::new(input),
            eof_delay,
            delayed: false,
        }
    }
}

impl Read for DelayedEofReader {
    fn read(&mut self, buffer: &mut [u8]) -> std::io::Result<usize> {
        let bytes_read = self.cursor.read(buffer)?;
        if bytes_read > 0 {
            return Ok(bytes_read);
        }
        if !self.delayed {
            self.delayed = true;
            thread::sleep(self.eof_delay);
        }
        Ok(0)
    }
}

#[derive(Default)]
struct IdleThenRegistrationBackend {
    iterations: usize,
}

impl VoipRuntimeBackend for IdleThenRegistrationBackend {
    fn start(&mut self, _config: &VoipConfig) -> Result<(), String> {
        Ok(())
    }

    fn stop(&mut self) {}

    fn iterate(&mut self) -> Result<Vec<BackendEvent>, String> {
        self.iterations += 1;
        if self.iterations == 2 {
            return Ok(vec![BackendEvent::RegistrationChanged {
                state: "ok".to_string(),
                reason: String::new(),
            }]);
        }
        Ok(vec![])
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

    fn send_text_message(&mut self, _sip_address: &str, _text: &str) -> Result<String, String> {
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
