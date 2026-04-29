mod support;

use std::fs;

use serde_json::Value;
use support::{config, config_with_message_store, FakeBackend};
use yoyopod_voip_host::config::VoipConfig;
use yoyopod_voip_host::host::{BackendEvent, MessageRecord, VoipHost};

fn poll_one(host: &mut VoipHost, event: BackendEvent) {
    let mut backend = FakeBackend {
        events: vec![event],
        ..FakeBackend::default()
    };
    let events = host.poll_backend_events(&mut backend).expect("poll event");
    assert_eq!(events.len(), 1);
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

#[test]
fn session_snapshot_tracks_call_message_and_voice_note_state() {
    let mut host = VoipHost::default();
    let mut backend = FakeBackend::default();
    host.configure(config());
    host.register(&mut backend).expect("register");

    assert_eq!(
        host.session_snapshot_payload()["registration_state"],
        "none"
    );
    assert_eq!(host.session_snapshot_payload()["call_state"], "idle");
    assert_eq!(
        host.session_snapshot_payload()["voice_note"]["state"],
        "idle"
    );

    poll_one(
        &mut host,
        BackendEvent::RegistrationChanged {
            state: "ok".to_string(),
            reason: "".to_string(),
        },
    );
    poll_one(
        &mut host,
        BackendEvent::IncomingCall {
            call_id: "call-1".to_string(),
            from_uri: "sip:bob@example.com".to_string(),
        },
    );
    poll_one(
        &mut host,
        BackendEvent::CallStateChanged {
            call_id: "call-1".to_string(),
            state: "streams_running".to_string(),
        },
    );

    let snapshot = host.session_snapshot_payload();
    assert_eq!(snapshot["configured"], true);
    assert_eq!(snapshot["registered"], true);
    assert_eq!(snapshot["registration_state"], "ok");
    assert_eq!(snapshot["active_call_id"], "call-1");
    assert_eq!(snapshot["call_state"], "streams_running");

    host.start_voice_recording(&mut backend, "/tmp/note.wav")
        .expect("start voice note");
    assert_eq!(
        host.session_snapshot_payload()["voice_note"]["state"],
        "recording"
    );
    assert_eq!(
        host.session_snapshot_payload()["voice_note"]["file_path"],
        "/tmp/note.wav"
    );

    host.stop_voice_recording(&mut backend)
        .expect("stop voice note");
    assert_eq!(
        host.session_snapshot_payload()["voice_note"]["state"],
        "recorded"
    );
    assert_eq!(
        host.session_snapshot_payload()["voice_note"]["duration_ms"],
        1250
    );

    host.send_voice_note(
        &mut backend,
        "sip:bob@example.com",
        "/tmp/note.wav",
        1250,
        "audio/wav",
        "client-vn-1",
    )
    .expect("send voice note");
    assert_eq!(
        host.session_snapshot_payload()["voice_note"]["state"],
        "sending"
    );
    assert_eq!(
        host.session_snapshot_payload()["voice_note"]["message_id"],
        "client-vn-1"
    );
    assert_eq!(
        host.session_snapshot_payload()["pending_outbound_messages"],
        1
    );

    poll_one(
        &mut host,
        BackendEvent::MessageDeliveryChanged {
            message_id: "client-vn-1".to_string(),
            delivery_state: "delivered".to_string(),
            local_file_path: "/tmp/note.wav".to_string(),
            error: "".to_string(),
        },
    );
    let snapshot = host.session_snapshot_payload();
    assert_eq!(snapshot["voice_note"]["state"], "sent");
    assert_eq!(snapshot["last_message"]["message_id"], "client-vn-1");
    assert_eq!(snapshot["last_message"]["delivery_state"], "delivered");
}

#[test]
fn session_snapshot_tracks_rust_owned_voice_note_summary() {
    let store_dir = support::temp_store_dir("host-message-summary");
    let mut host = VoipHost::default();
    host.configure(config_with_message_store(&store_dir));

    poll_one(
        &mut host,
        BackendEvent::MessageReceived {
            message: MessageRecord {
                message_id: "incoming-mom-1".to_string(),
                peer_sip_address: "sip:mom@example.com".to_string(),
                sender_sip_address: "sip:mom@example.com".to_string(),
                recipient_sip_address: "sip:alice@example.com".to_string(),
                kind: "voice_note".to_string(),
                direction: "incoming".to_string(),
                delivery_state: "delivered".to_string(),
                text: String::new(),
                local_file_path: "/tmp/mom.wav".to_string(),
                mime_type: "audio/wav".to_string(),
                duration_ms: 1800,
                unread: true,
            },
        },
    );

    let snapshot = host.session_snapshot_payload();
    assert_eq!(snapshot["unread_voice_notes"], 1);
    assert_eq!(
        snapshot["unread_voice_notes_by_contact"]["sip:mom@example.com"],
        1
    );
    assert_eq!(
        snapshot["latest_voice_note_by_contact"]["sip:mom@example.com"]["message_id"],
        "incoming-mom-1"
    );

    host.mark_voice_notes_seen("sip:mom@example.com")
        .expect("mark seen");

    let snapshot = host.session_snapshot_payload();
    assert_eq!(snapshot["unread_voice_notes"], 0);
    assert!(snapshot["unread_voice_notes_by_contact"]
        .as_object()
        .expect("counts object")
        .is_empty());
}

#[test]
fn message_received_normalizes_rcs_voice_note_envelope_for_event_and_snapshot() {
    let store_dir = support::temp_store_dir("host-message-envelope");
    let mut host = VoipHost::default();
    host.configure(config_with_message_store(&store_dir));
    let mut backend = FakeBackend {
        events: vec![BackendEvent::MessageReceived {
            message: MessageRecord {
                message_id: "incoming-envelope-1".to_string(),
                peer_sip_address: "sip:mom@example.com".to_string(),
                sender_sip_address: "sip:mom@example.com".to_string(),
                recipient_sip_address: "sip:alice@example.com".to_string(),
                kind: "text".to_string(),
                direction: "incoming".to_string(),
                delivery_state: "delivered".to_string(),
                text: (r#"<?xml version="1.0" encoding="UTF-8"?>"#.to_string()
                    + r#"<file xmlns="urn:gsma:params:xml:ns:rcs:rcs:fthttp" "#
                    + r#"xmlns:am="urn:gsma:params:xml:ns:rcs:rcs:rram">"#
                    + r#"<file-info type="file">"#
                    + r#"<content-type>audio/ogg;voice-recording=yes</content-type>"#
                    + r#"<am:playing-length>4046</am:playing-length>"#
                    + r#"</file-info></file>"#),
                local_file_path: "/tmp/incoming-envelope.mka".to_string(),
                mime_type: "application/vnd.gsma.rcs-ft-http+xml".to_string(),
                duration_ms: 0,
                unread: true,
            },
        }],
        ..FakeBackend::default()
    };

    let events = host.poll_backend_events(&mut backend).expect("poll event");

    let BackendEvent::MessageReceived { message } = &events[0] else {
        panic!("expected normalized message received event");
    };
    assert_eq!(message.kind, "voice_note");
    assert_eq!(message.mime_type, "audio/ogg");
    assert_eq!(message.duration_ms, 4046);
    assert_eq!(message.text, "");

    let snapshot = host.session_snapshot_payload();
    assert_eq!(snapshot["last_message"]["kind"], "voice_note");
    assert_eq!(snapshot["unread_voice_notes"], 1);
    assert_eq!(
        snapshot["latest_voice_note_by_contact"]["sip:mom@example.com"]["duration_ms"],
        4046
    );
}

#[test]
fn call_session_snapshot_tracks_direction_terminal_outcome_and_duration() {
    let mut host = VoipHost::default();
    let mut backend = FakeBackend::default();
    host.configure(config());
    host.register(&mut backend).expect("register");

    host.dial(&mut backend, "sip:bob@example.com")
        .expect("dial");
    let snapshot = host.session_snapshot_payload();
    assert_eq!(snapshot["call_session"]["active"], true);
    assert_eq!(snapshot["call_session"]["session_id"], "call-outgoing");
    assert_eq!(snapshot["call_session"]["direction"], "outgoing");
    assert_eq!(
        snapshot["call_session"]["peer_sip_address"],
        "sip:bob@example.com"
    );
    assert_eq!(snapshot["call_session"]["answered"], false);

    poll_one(
        &mut host,
        BackendEvent::CallStateChanged {
            call_id: "call-outgoing".to_string(),
            state: "streams_running".to_string(),
        },
    );
    assert_eq!(
        host.session_snapshot_payload()["call_session"]["answered"],
        true
    );

    host.hangup(&mut backend).expect("hangup");
    let snapshot = host.session_snapshot_payload();
    assert_eq!(snapshot["call_session"]["active"], false);
    assert_eq!(snapshot["call_session"]["session_id"], "call-outgoing");
    assert_eq!(snapshot["call_session"]["terminal_state"], "released");
    assert_eq!(snapshot["call_session"]["local_end_action"], "hangup");
    assert_eq!(snapshot["call_session"]["history_outcome"], "completed");
    assert!(snapshot["call_session"]["duration_seconds"]
        .as_u64()
        .is_some());
}

#[test]
fn outgoing_terminal_call_state_finalizes_session_when_event_uses_peer_address() {
    let mut host = VoipHost::default();
    let mut backend = FakeBackend::default();
    host.configure(config());
    host.register(&mut backend).expect("register");

    host.dial(&mut backend, "sip:bob@example.com")
        .expect("dial");

    poll_one(
        &mut host,
        BackendEvent::CallStateChanged {
            call_id: "sip:bob@example.com".to_string(),
            state: "released".to_string(),
        },
    );

    let snapshot = host.session_snapshot_payload();
    assert_eq!(snapshot["active_call_id"], Value::Null);
    assert_eq!(snapshot["active_call_peer"], "");
    assert_eq!(snapshot["call_session"]["active"], false);
    assert_eq!(snapshot["call_session"]["session_id"], "call-outgoing");
    assert_eq!(
        snapshot["call_session"]["peer_sip_address"],
        "sip:bob@example.com"
    );
    assert_eq!(snapshot["call_session"]["terminal_state"], "released");
    assert_eq!(snapshot["call_session"]["history_outcome"], "cancelled");
}

#[test]
fn incoming_call_session_snapshot_reports_missed_terminal_outcome() {
    let mut host = VoipHost::default();
    host.configure(config());

    poll_one(
        &mut host,
        BackendEvent::IncomingCall {
            call_id: "call-incoming".to_string(),
            from_uri: "sip:mama@example.com".to_string(),
        },
    );
    let snapshot = host.session_snapshot_payload();
    assert_eq!(snapshot["call_session"]["active"], true);
    assert_eq!(snapshot["call_session"]["direction"], "incoming");
    assert_eq!(
        snapshot["call_session"]["peer_sip_address"],
        "sip:mama@example.com"
    );

    poll_one(
        &mut host,
        BackendEvent::CallStateChanged {
            call_id: "call-incoming".to_string(),
            state: "released".to_string(),
        },
    );
    let snapshot = host.session_snapshot_payload();
    assert_eq!(snapshot["call_session"]["active"], false);
    assert_eq!(snapshot["call_session"]["terminal_state"], "released");
    assert_eq!(snapshot["call_session"]["history_outcome"], "missed");
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
fn lifecycle_snapshot_tracks_register_failure_recovery_and_stop() {
    let mut host = VoipHost::default();
    assert_eq!(
        host.session_snapshot_payload()["lifecycle"]["state"],
        "unconfigured"
    );

    host.configure(config());
    assert_eq!(
        host.session_snapshot_payload()["lifecycle"]["state"],
        "configured"
    );

    let mut backend = FakeBackend {
        start_results: vec![Err("shim missing".to_string()), Ok(())],
        ..FakeBackend::default()
    };
    assert_eq!(
        host.register(&mut backend)
            .expect_err("register should fail"),
        "shim missing"
    );
    let snapshot = host.session_snapshot_payload();
    assert_eq!(snapshot["registered"], false);
    assert_eq!(snapshot["registration_state"], "failed");
    assert_eq!(snapshot["lifecycle"]["state"], "failed");
    assert_eq!(snapshot["lifecycle"]["reason"], "shim missing");

    host.register(&mut backend)
        .expect("register should recover");
    let lifecycle_events = host.take_lifecycle_events();
    assert!(lifecycle_events
        .iter()
        .any(|event| event.state == "registered" && event.recovered));
    let snapshot = host.session_snapshot_payload();
    assert_eq!(snapshot["registered"], true);
    assert_eq!(snapshot["lifecycle"]["state"], "registered");

    host.unregister(&mut backend);
    assert_eq!(backend.stop_calls, 1);
    let snapshot = host.session_snapshot_payload();
    assert_eq!(snapshot["registered"], false);
    assert_eq!(snapshot["lifecycle"]["state"], "stopped");
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
    assert_eq!(host.health_payload()["active_call_id"], Value::Null);
    assert_eq!(host.session_snapshot_payload()["muted"], false);
}

#[test]
fn mute_state_is_owned_by_host_snapshots_and_resets_on_stop() {
    let mut host = VoipHost::default();
    let mut backend = FakeBackend::default();
    host.configure(config());
    host.register(&mut backend).unwrap();

    assert_eq!(host.session_snapshot_payload()["muted"], false);

    host.set_muted(&mut backend, true).expect("mute");
    assert_eq!(host.session_snapshot_payload()["muted"], true);

    host.set_muted(&mut backend, false).expect("unmute");
    assert_eq!(host.session_snapshot_payload()["muted"], false);

    host.set_muted(&mut backend, true)
        .expect("mute before stop");
    host.unregister(&mut backend);
    assert_eq!(host.session_snapshot_payload()["muted"], false);
}

#[test]
fn send_text_message_returns_client_id_and_maps_delivery_back_to_client_id() {
    let mut host = VoipHost::default();
    host.configure(config());
    let mut backend = FakeBackend::default();
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
fn send_text_message_returns_client_id_when_message_store_save_fails() {
    let store_path = support::temp_store_dir("host-text-store-file");
    fs::write(&store_path, b"not a directory").expect("store blocker");
    let mut host = VoipHost::default();
    host.configure(config_with_message_store(&store_path));
    let mut backend = FakeBackend::default();
    host.register(&mut backend).unwrap();

    let message_id = host
        .send_text_message(&mut backend, "sip:bob@example.com", "hello", "client-msg-1")
        .expect("send text remains accepted");

    assert_eq!(message_id, "client-msg-1");
    assert_eq!(
        backend.calls,
        vec!["start", "text:sip:bob@example.com:hello"]
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

    let mut event_backend = FakeBackend {
        events: vec![BackendEvent::MessageDeliveryChanged {
            message_id: "backend-vn-1".to_string(),
            delivery_state: "delivered".to_string(),
            local_file_path: "/tmp/a.wav".to_string(),
            error: "".to_string(),
        }],
        ..FakeBackend::default()
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
fn send_voice_note_returns_client_id_when_message_store_save_fails() {
    let store_path = support::temp_store_dir("host-voice-store-file");
    fs::write(&store_path, b"not a directory").expect("store blocker");
    let mut host = VoipHost::default();
    host.configure(config_with_message_store(&store_path));
    let mut backend = FakeBackend::default();
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
        .expect("send voice note remains accepted");

    assert_eq!(message_id, "client-vn-1");
    assert_eq!(
        backend.calls,
        vec![
            "start",
            "voice:sip:bob@example.com:/tmp/a.wav:1250:audio/wav"
        ]
    );
}

#[test]
fn reject_and_unregister_clear_state() {
    let mut host = VoipHost::default();
    let mut backend = FakeBackend::default();
    host.configure(config());
    host.register(&mut backend).unwrap();
    host.dial(&mut backend, "sip:bob@example.com").unwrap();
    host.set_muted(&mut backend, true).expect("mute");

    host.reject(&mut backend).expect("reject");
    assert_eq!(host.session_snapshot_payload()["muted"], false);
    host.unregister(&mut backend);

    assert_eq!(
        backend.calls,
        vec![
            "start",
            "dial:sip:bob@example.com",
            "mute:true",
            "reject",
            "stop"
        ]
    );
    assert_eq!(host.health_payload()["registered"], false);
    assert_eq!(host.health_payload()["active_call_id"], Value::Null);
}

#[test]
fn poll_backend_events_updates_registration_and_call_state() {
    let mut host = VoipHost::default();
    host.configure(config());
    let mut backend = FakeBackend {
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
        ..FakeBackend::default()
    };

    let events = host.poll_backend_events(&mut backend).expect("poll");

    assert_eq!(events.len(), 3);
    assert_eq!(host.health_payload()["registered"], true);
    assert_eq!(host.health_payload()["active_call_id"], Value::Null);
}

#[test]
fn iterate_interval_comes_from_config() {
    let mut host = VoipHost::default();
    host.configure(
        VoipConfig::from_payload(&serde_json::json!({
            "sip_server":"sip.example.com",
            "sip_identity":"sip:alice@example.com",
            "iterate_interval_ms": 37
        }))
        .unwrap(),
    );

    assert_eq!(host.iterate_interval_ms(), 37);
}

#[test]
fn message_delivery_updates_last_message() {
    let mut host = VoipHost::default();
    host.configure(config());

    poll_one(
        &mut host,
        BackendEvent::MessageReceived {
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
        },
    );

    let snapshot = host.session_snapshot_payload();
    assert_eq!(snapshot["last_message"]["message_id"], "msg-1");
    assert_eq!(snapshot["last_message"]["kind"], "text");
    assert_eq!(snapshot["last_message"]["direction"], "incoming");
    assert_eq!(snapshot["last_message"]["delivery_state"], "delivered");
}
