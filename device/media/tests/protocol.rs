use serde_json::json;
use yoyopod_media::protocol::{EnvelopeKind, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};

#[test]
fn decode_accepts_command_without_schema_version() {
    let line = br#"{"kind":"command","type":"media.health","payload":{}}"#;

    let envelope = WorkerEnvelope::decode(line).expect("decode");

    assert_eq!(envelope.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(envelope.kind, EnvelopeKind::Command);
    assert_eq!(envelope.message_type, "media.health");
    assert_eq!(envelope.payload, json!({}));
}

#[test]
fn encode_ready_event_terminates_with_newline() {
    let encoded = WorkerEnvelope::event(
        "media.ready",
        json!({"capabilities":["configure", "health"]}),
    )
    .encode()
    .expect("encode");

    assert!(encoded.ends_with(b"\n"));
    assert!(std::str::from_utf8(&encoded)
        .expect("utf8")
        .contains("\"type\":\"media.ready\""));
}
