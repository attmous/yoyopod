use serde_json::json;
use yoyopod_voip_host::protocol::{EnvelopeKind, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};

#[test]
fn decode_accepts_voip_health_command() {
    let raw = br#"{"schema_version":1,"kind":"command","type":"voip.health","request_id":"r1","payload":{}}"#;

    let envelope = WorkerEnvelope::decode(raw).expect("decode");

    assert_eq!(envelope.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(envelope.kind, EnvelopeKind::Command);
    assert_eq!(envelope.message_type, "voip.health");
    assert_eq!(envelope.request_id.as_deref(), Some("r1"));
}

#[test]
fn encode_ready_event_has_newline() {
    let encoded = WorkerEnvelope::event("voip.ready", json!({"capabilities":["calls"]}))
        .encode()
        .expect("encode");

    assert!(encoded.ends_with(b"\n"));
    assert!(std::str::from_utf8(&encoded)
        .unwrap()
        .contains("\"type\":\"voip.ready\""));
}

#[test]
fn rejects_array_payload() {
    let err = WorkerEnvelope::decode(
        br#"{"schema_version":1,"kind":"command","type":"voip.health","payload":[]}"#,
    )
    .expect_err("payload must be rejected");

    assert!(err.to_string().contains("payload must be an object"));
}
