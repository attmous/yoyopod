use serde_json::json;
use yoyopod_runtime::protocol::{
    EnvelopeKind, ProtocolError, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION,
};

#[test]
fn decode_accepts_worker_command_without_explicit_schema_version() {
    let envelope = WorkerEnvelope::decode(
        br#"{"kind":"command","type":"media.health","request_id":"health-1","payload":{}}"#,
    )
    .expect("decode with default schema version");

    assert_eq!(envelope.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(envelope.kind, EnvelopeKind::Command);
    assert_eq!(envelope.message_type, "media.health");
    assert_eq!(envelope.request_id.as_deref(), Some("health-1"));
    assert_eq!(envelope.payload, json!({}));
}

#[test]
fn encode_command_uses_stable_ndjson_shape() {
    let envelope = WorkerEnvelope::command("ui.tick", None, json!({"renderer":"auto"}));

    let encoded = envelope.encode().expect("encode");
    let text = std::str::from_utf8(&encoded).expect("utf8");

    assert!(encoded.ends_with(b"\n"));
    assert!(text.contains("\"schema_version\":1"));
    assert!(text.contains("\"kind\":\"command\""));
    assert!(text.contains("\"type\":\"ui.tick\""));
    assert!(!text.contains("\"request_id\":null"));
}

#[test]
fn rejects_non_object_payload() {
    let err = WorkerEnvelope::decode(
        br#"{"schema_version":1,"kind":"event","type":"ui.ready","payload":[]}"#,
    )
    .expect_err("payload array must fail");

    assert!(matches!(err, ProtocolError::InvalidEnvelope(_)));
    assert!(err.to_string().contains("payload must be an object"));
}
