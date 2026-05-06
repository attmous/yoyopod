use serde_json::json;
use yoyopod_protocol::{EnvelopeKind, ProtocolError, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};

#[test]
fn command_round_trip_preserves_fields_and_newline() {
    let envelope = WorkerEnvelope::command(
        "power.health",
        Some("req-1".to_string()),
        json!({"include": "battery"}),
    );

    let encoded = envelope.encode().expect("encode");
    assert!(encoded.ends_with(b"\n"));

    let decoded = WorkerEnvelope::decode(&encoded).expect("decode");
    assert_eq!(decoded.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(decoded.kind, EnvelopeKind::Command);
    assert_eq!(decoded.message_type, "power.health");
    assert_eq!(decoded.request_id.as_deref(), Some("req-1"));
    assert_eq!(decoded.payload, json!({"include": "battery"}));
}

#[test]
fn event_and_result_constructors_use_expected_shape() {
    let event = WorkerEnvelope::event("power.ready", json!({"ready": true}));
    assert_eq!(event.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(event.kind, EnvelopeKind::Event);
    assert_eq!(event.message_type, "power.ready");
    assert_eq!(event.request_id, None);
    assert_eq!(event.timestamp_ms, 0);
    assert_eq!(event.deadline_ms, 0);
    assert_eq!(event.payload, json!({"ready": true}));

    let result = WorkerEnvelope::result(
        "power.health",
        Some("req-2".to_string()),
        json!({"ok": true}),
    );
    assert_eq!(result.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(result.kind, EnvelopeKind::Result);
    assert_eq!(result.message_type, "power.health");
    assert_eq!(result.request_id.as_deref(), Some("req-2"));
    assert_eq!(result.timestamp_ms, 0);
    assert_eq!(result.deadline_ms, 0);
    assert_eq!(result.payload, json!({"ok": true}));
}

#[test]
fn error_constructor_accepts_domain_specific_type() {
    let envelope = WorkerEnvelope::error(
        "power.error",
        Some("req-1".to_string()),
        "invalid_payload",
        "bad",
    );

    assert_eq!(envelope.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(envelope.kind, EnvelopeKind::Error);
    assert_eq!(envelope.message_type, "power.error");
    assert_eq!(envelope.request_id.as_deref(), Some("req-1"));
    assert_eq!(
        envelope.payload,
        json!({"code": "invalid_payload", "message": "bad"})
    );
}

#[test]
fn heartbeat_constructor_uses_expected_shape() {
    let envelope = WorkerEnvelope::heartbeat("power.heartbeat", json!({"alive": true}));

    assert_eq!(envelope.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(envelope.kind, EnvelopeKind::Heartbeat);
    assert_eq!(envelope.message_type, "power.heartbeat");
    assert_eq!(envelope.request_id, None);
    assert_eq!(envelope.timestamp_ms, 0);
    assert_eq!(envelope.deadline_ms, 0);
    assert_eq!(envelope.payload, json!({"alive": true}));
}

#[test]
fn rejects_unsupported_schema_version() {
    let err = WorkerEnvelope::decode(
        br#"{"schema_version":2,"kind":"command","type":"power.health","payload":{}}"#,
    )
    .expect_err("schema version 2 must fail");

    assert!(matches!(
        err,
        ProtocolError::UnsupportedSchema {
            actual: 2,
            expected: SUPPORTED_SCHEMA_VERSION
        }
    ));
}

#[test]
fn accepts_missing_schema_version_as_current_version() {
    let envelope =
        WorkerEnvelope::decode(br#"{"kind":"command","type":"power.health","payload":{}}"#)
            .expect("decode with default schema version");

    assert_eq!(envelope.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(envelope.kind, EnvelopeKind::Command);
    assert_eq!(envelope.message_type, "power.health");
    assert_eq!(envelope.payload, json!({}));
}

#[test]
fn normalizes_null_payload_to_empty_object() {
    let envelope = WorkerEnvelope::decode(
        br#"{"schema_version":1,"kind":"command","type":"voice.health","payload":null}"#,
    )
    .expect("decode null payload");

    assert_eq!(envelope.payload, json!({}));
}

#[test]
fn rejects_empty_type() {
    let err = WorkerEnvelope::decode(
        br#"{"schema_version":1,"kind":"command","type":"  ","payload":{}}"#,
    )
    .expect_err("empty type must fail");

    assert!(matches!(err, ProtocolError::InvalidEnvelope(_)));
    assert!(err.to_string().contains("type must be a non-empty string"));
}

#[test]
fn rejects_non_object_payload() {
    let err = WorkerEnvelope::decode(
        br#"{"schema_version":1,"kind":"event","type":"power.ready","payload":[]}"#,
    )
    .expect_err("payload array must fail");

    assert!(matches!(err, ProtocolError::InvalidEnvelope(_)));
    assert!(err.to_string().contains("payload must be an object"));
}
