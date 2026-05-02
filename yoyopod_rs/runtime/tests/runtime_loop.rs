use std::collections::VecDeque;

use serde_json::{json, Value};
use yoyopod_runtime::protocol::{EnvelopeKind, WorkerEnvelope};
use yoyopod_runtime::runtime_loop::{LoopIo, RuntimeLoop};
use yoyopod_runtime::state::{RuntimeState, WorkerDomain};
use yoyopod_runtime::worker::WorkerProtocolError;

#[test]
fn media_snapshot_updates_state_and_sends_ui_snapshot() {
    let mut runtime_loop = RuntimeLoop::new(RuntimeState::default());
    let mut io = FakeLoopIo::with_messages([(
        WorkerDomain::Media,
        event_envelope(
            "media.snapshot",
            json!({
                "connected": true,
                "playback_state": "playing",
                "current_track": {
                    "title": "A Song",
                    "artist": "An Artist"
                }
            }),
        ),
    )]);

    let processed = runtime_loop.run_once(&mut io);

    assert_eq!(processed, 1);
    assert_eq!(runtime_loop.state().media.playback_state, "playing");
    let snapshot = sent_to(&io, WorkerDomain::Ui, "ui.runtime_snapshot");
    assert_eq!(snapshot.kind, EnvelopeKind::Command);
    assert_eq!(snapshot.payload["music"]["playing"], true);
    assert_eq!(snapshot.payload["music"]["title"], "A Song");
}

#[test]
fn ui_tick_is_sent_every_iteration() {
    let mut runtime_loop = RuntimeLoop::new(RuntimeState::default());
    let mut io = FakeLoopIo::default();

    assert_eq!(runtime_loop.run_once(&mut io), 0);
    assert_eq!(runtime_loop.run_once(&mut io), 0);

    let ticks: Vec<_> = io
        .sent
        .iter()
        .filter(|(domain, envelope)| {
            *domain == WorkerDomain::Ui && envelope.message_type == "ui.tick"
        })
        .collect();
    assert_eq!(ticks.len(), 2);
    assert!(ticks
        .iter()
        .all(|(_, envelope)| envelope.kind == EnvelopeKind::Command));
    assert!(ticks
        .iter()
        .all(|(_, envelope)| envelope.payload == json!({"renderer": "auto"})));
    assert_eq!(runtime_loop.state().loop_iterations, 2);
}

#[test]
fn ui_play_pause_intent_while_media_is_playing_sends_media_pause() {
    let mut state = RuntimeState::default();
    state.apply_media_snapshot(&json!({"playback_state": "playing"}));
    let mut runtime_loop = RuntimeLoop::new(state);
    let mut io = FakeLoopIo::with_messages([(
        WorkerDomain::Ui,
        ui_intent("music", "play_pause", json!({})),
    )]);

    let processed = runtime_loop.run_once(&mut io);

    assert_eq!(processed, 1);
    let pause = sent_to(&io, WorkerDomain::Media, "media.pause");
    assert_eq!(pause.kind, EnvelopeKind::Command);
    assert_eq!(pause.payload, json!({}));
}

#[test]
fn runtime_shutdown_ui_intent_sets_shutdown_requested() {
    let mut runtime_loop = RuntimeLoop::new(RuntimeState::default());
    let mut io = FakeLoopIo::with_messages([(
        WorkerDomain::Ui,
        ui_intent("runtime", "shutdown", json!({})),
    )]);

    let processed = runtime_loop.run_once(&mut io);

    assert_eq!(processed, 1);
    assert!(runtime_loop.shutdown_requested());
}

#[test]
fn worker_protocol_error_increments_health_and_records_reason() {
    let mut runtime_loop = RuntimeLoop::new(RuntimeState::default());
    let mut io = FakeLoopIo::with_protocol_errors([(
        WorkerDomain::Voice,
        WorkerProtocolError {
            raw_line: "not-json".to_string(),
            message: "expected value at line 1 column 1".to_string(),
        },
    )]);

    let processed = runtime_loop.run_once(&mut io);

    assert_eq!(processed, 0);
    assert_eq!(runtime_loop.state().voice_worker.protocol_errors, 1);
    assert!(runtime_loop
        .state()
        .voice_worker
        .last_reason
        .contains("expected value"));
}

#[test]
fn protocol_error_remains_visible_after_same_iteration_ready_event() {
    let mut runtime_loop = RuntimeLoop::new(RuntimeState::default());
    let mut io = FakeLoopIo {
        messages: [(
            WorkerDomain::Voice,
            event_envelope("voice.ready", json!({})),
        )]
        .into_iter()
        .collect(),
        protocol_errors: [(
            WorkerDomain::Voice,
            WorkerProtocolError {
                raw_line: "not-json".to_string(),
                message: "expected value at line 1 column 1".to_string(),
            },
        )]
        .into_iter()
        .collect(),
        sent: Vec::new(),
        ..FakeLoopIo::default()
    };

    let processed = runtime_loop.run_once(&mut io);

    assert_eq!(processed, 1);
    assert_eq!(runtime_loop.state().voice_worker.protocol_errors, 1);
    assert_eq!(
        runtime_loop.state().status_payload()["workers"]["voice"]["state"],
        "degraded"
    );
    assert!(runtime_loop
        .state()
        .voice_worker
        .last_reason
        .contains("expected value"));
}

#[test]
fn protocol_error_only_iteration_sends_tick_without_runtime_snapshot() {
    let mut runtime_loop = RuntimeLoop::new(RuntimeState::default());
    let mut io = FakeLoopIo::with_protocol_errors([(
        WorkerDomain::Voice,
        WorkerProtocolError {
            raw_line: "not-json".to_string(),
            message: "expected value at line 1 column 1".to_string(),
        },
    )]);

    let processed = runtime_loop.run_once(&mut io);

    assert_eq!(processed, 0);
    assert!(sent_optional(&io, WorkerDomain::Ui, "ui.tick").is_some());
    assert!(sent_optional(&io, WorkerDomain::Ui, "ui.runtime_snapshot").is_none());
}

#[test]
fn incoming_voip_snapshot_pauses_media_before_applying_call_state() {
    let mut state = RuntimeState::default();
    state.apply_media_snapshot(&json!({"playback_state": "playing"}));
    let mut runtime_loop = RuntimeLoop::new(state);
    let mut io = FakeLoopIo::with_messages([(
        WorkerDomain::Voip,
        event_envelope("voip.snapshot", json!({"call_state": "incoming"})),
    )]);

    let processed = runtime_loop.run_once(&mut io);

    assert_eq!(processed, 1);
    let pause = sent_to(&io, WorkerDomain::Media, "media.pause");
    let snapshot = sent_to(&io, WorkerDomain::Ui, "ui.runtime_snapshot");
    let pause_index = sent_index(&io, WorkerDomain::Media, "media.pause");
    let snapshot_index = sent_index(&io, WorkerDomain::Ui, "ui.runtime_snapshot");
    assert_eq!(pause.kind, EnvelopeKind::Command);
    assert_eq!(pause.payload, json!({}));
    assert_eq!(snapshot.payload["call"]["state"], "incoming");
    assert!(pause_index < snapshot_index);
}

#[test]
fn cloud_remote_media_command_acks_after_media_dispatch_succeeds() {
    let mut runtime_loop = RuntimeLoop::new(RuntimeState::default());
    let mut io = FakeLoopIo::with_messages([(
        WorkerDomain::Cloud,
        event_envelope(
            "cloud.command",
            json!({
                "command": {
                    "command": "pause",
                    "commandId": "cmd-1"
                }
            }),
        ),
    )]);

    let processed = runtime_loop.run_once(&mut io);

    assert_eq!(processed, 1);
    let pause = sent_to(&io, WorkerDomain::Media, "media.pause");
    assert_eq!(pause.payload, json!({}));
    let ack = sent_to(&io, WorkerDomain::Cloud, "cloud.ack");
    assert_eq!(
        ack.payload,
        json!({
            "command_id": "cmd-1",
            "ok": true,
            "payload": {"command": "pause"}
        })
    );
}

#[test]
fn cloud_remote_media_command_nacks_when_media_dispatch_fails() {
    let mut runtime_loop = RuntimeLoop::new(RuntimeState::default());
    let mut io = FakeLoopIo::with_messages([(
        WorkerDomain::Cloud,
        event_envelope(
            "cloud.command",
            json!({
                "command": {
                    "command": "stop",
                    "commandId": "cmd-2"
                }
            }),
        ),
    )]);
    io.fail_sends
        .push_back((WorkerDomain::Media, "media.stop_playback".to_string()));

    let processed = runtime_loop.run_once(&mut io);

    assert_eq!(processed, 1);
    assert!(sent_optional(&io, WorkerDomain::Media, "media.stop_playback").is_none());
    assert_eq!(
        io.failed_sends,
        vec![(WorkerDomain::Media, "media.stop_playback".to_string())]
    );
    let ack = sent_to(&io, WorkerDomain::Cloud, "cloud.ack");
    assert_eq!(
        ack.payload,
        json!({
            "command_id": "cmd-2",
            "ok": false,
            "reason": "media_dispatch_failed",
            "payload": {
                "command": "stop",
                "media_command": "media.stop_playback"
            }
        })
    );
}

#[derive(Default)]
struct FakeLoopIo {
    messages: VecDeque<(WorkerDomain, WorkerEnvelope)>,
    protocol_errors: VecDeque<(WorkerDomain, WorkerProtocolError)>,
    fail_sends: VecDeque<(WorkerDomain, String)>,
    failed_sends: Vec<(WorkerDomain, String)>,
    sent: Vec<(WorkerDomain, WorkerEnvelope)>,
}

impl FakeLoopIo {
    fn with_messages(messages: impl IntoIterator<Item = (WorkerDomain, WorkerEnvelope)>) -> Self {
        Self {
            messages: messages.into_iter().collect(),
            ..Self::default()
        }
    }

    fn with_protocol_errors(
        protocol_errors: impl IntoIterator<Item = (WorkerDomain, WorkerProtocolError)>,
    ) -> Self {
        Self {
            protocol_errors: protocol_errors.into_iter().collect(),
            ..Self::default()
        }
    }
}

impl LoopIo for FakeLoopIo {
    fn drain_worker_messages(&mut self) -> Vec<(WorkerDomain, WorkerEnvelope)> {
        self.messages.drain(..).collect()
    }

    fn drain_worker_protocol_errors(&mut self) -> Vec<(WorkerDomain, WorkerProtocolError)> {
        self.protocol_errors.drain(..).collect()
    }

    fn send_worker_envelope(&mut self, domain: WorkerDomain, envelope: WorkerEnvelope) -> bool {
        if self
            .fail_sends
            .front()
            .is_some_and(|(failed_domain, message_type)| {
                *failed_domain == domain && message_type == &envelope.message_type
            })
        {
            let failed = self.fail_sends.pop_front().expect("checked failed send");
            self.failed_sends.push(failed);
            return false;
        }
        self.sent.push((domain, envelope));
        true
    }
}

fn sent_to<'a>(io: &'a FakeLoopIo, domain: WorkerDomain, message_type: &str) -> &'a WorkerEnvelope {
    sent_optional(io, domain, message_type)
        .unwrap_or_else(|| panic!("missing sent envelope {message_type} to {domain:?}"))
}

fn sent_optional<'a>(
    io: &'a FakeLoopIo,
    domain: WorkerDomain,
    message_type: &str,
) -> Option<&'a WorkerEnvelope> {
    io.sent
        .iter()
        .find(|(sent_domain, envelope)| {
            *sent_domain == domain && envelope.message_type == message_type
        })
        .map(|(_, envelope)| envelope)
}

fn sent_index(io: &FakeLoopIo, domain: WorkerDomain, message_type: &str) -> usize {
    io.sent
        .iter()
        .position(|(sent_domain, envelope)| {
            *sent_domain == domain && envelope.message_type == message_type
        })
        .unwrap_or_else(|| panic!("missing sent envelope {message_type} to {domain:?}"))
}

fn event_envelope(message_type: &str, payload: Value) -> WorkerEnvelope {
    WorkerEnvelope {
        schema_version: 1,
        kind: EnvelopeKind::Event,
        message_type: message_type.to_string(),
        request_id: None,
        timestamp_ms: 0,
        deadline_ms: 0,
        payload,
    }
}

fn ui_intent(domain: &str, action: &str, payload: Value) -> WorkerEnvelope {
    event_envelope(
        "ui.intent",
        json!({
            "domain": domain,
            "action": action,
            "payload": payload,
        }),
    )
}
