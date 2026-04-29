use serde_json::json;
use yoyopod_ui_host::protocol::{Envelope, EnvelopeKind, SUPPORTED_SCHEMA_VERSION};

#[test]
fn decode_accepts_spec_style_command_without_schema_version() {
    let line = br#"{"kind":"command","type":"ui.show_test_scene","payload":{"counter":7}}"#;

    let envelope = Envelope::decode(line).expect("decode");

    assert_eq!(envelope.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(envelope.kind, EnvelopeKind::Command);
    assert_eq!(envelope.message_type, "ui.show_test_scene");
    assert_eq!(envelope.payload["counter"], json!(7));
}

#[test]
fn encode_ready_event_terminates_with_newline() {
    let encoded = Envelope::event("ui.ready", json!({"width": 240, "height": 280}))
        .encode()
        .expect("encode");

    assert!(encoded.ends_with(b"\n"));
    assert!(std::str::from_utf8(&encoded)
        .unwrap()
        .contains("\"type\":\"ui.ready\""));
}

#[test]
fn rejects_unknown_kind() {
    let err = Envelope::decode(br#"{"kind":"bogus","type":"ui.ready","payload":{}}"#)
        .expect_err("must reject invalid kind");

    assert!(err.to_string().contains("invalid JSON UI envelope"));
}
