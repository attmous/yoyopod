use serde_json::json;
use yoyopod_ui_host::protocol::{error_envelope, Envelope, EnvelopeKind, SUPPORTED_SCHEMA_VERSION};

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
    let encoded =
        yoyopod_ui_host::protocol::event_envelope("ui.ready", json!({"width": 240, "height": 280}))
            .encode()
            .expect("encode");

    assert!(encoded.ends_with(b"\n"));
    assert!(std::str::from_utf8(&encoded)
        .unwrap()
        .contains("\"type\":\"ui.ready\""));
}

#[test]
fn ui_error_preserves_event_shape() {
    let envelope = error_envelope("lvgl_unavailable", "LVGL renderer unavailable");

    assert_eq!(envelope.kind, EnvelopeKind::Event);
    assert_eq!(envelope.message_type, "ui.error");
    assert_eq!(envelope.payload["code"], "lvgl_unavailable");
    assert_eq!(envelope.payload["message"], "LVGL renderer unavailable");
}

#[test]
fn rejects_unknown_kind() {
    let err =
        Envelope::decode(br#"{"schema_version":1,"kind":"bogus","type":"ui.ready","payload":{}}"#)
            .expect_err("must reject invalid kind");

    assert!(err.to_string().contains("unknown variant"));
}
