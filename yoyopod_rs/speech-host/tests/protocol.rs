use serde_json::json;
use yoyopod_speech_host::protocol::{EnvelopeKind, WorkerEnvelope};

#[test]
fn encode_defaults_schema_version_and_payload() {
    let envelope = WorkerEnvelope::result(
        "voice.health.result",
        Some("health-1".to_string()),
        json!({}),
    );

    let encoded = envelope.encode().expect("encode envelope");
    let decoded: serde_json::Value =
        serde_json::from_slice(&encoded).expect("encoded envelope is JSON");

    assert_eq!(decoded["schema_version"], 1);
    assert_eq!(decoded["kind"], "result");
    assert_eq!(decoded["type"], "voice.health.result");
    assert_eq!(decoded["request_id"], "health-1");
    assert_eq!(decoded["payload"], json!({}));
    assert!(encoded.ends_with(b"\n"));
}

#[test]
fn decode_rejects_invalid_kind() {
    let error = WorkerEnvelope::decode(
        br#"{"schema_version":1,"kind":"bogus","type":"voice.health","payload":{}}"#,
    )
    .expect_err("invalid kind should fail");

    assert!(error.to_string().contains("unknown variant"));
}

#[test]
fn decode_preserves_command_fields() {
    let envelope = WorkerEnvelope::decode(
        br#"{"schema_version":1,"kind":"command","type":"voice.transcribe","request_id":"stt-1","deadline_ms":250,"payload":{"audio_path":"/tmp/input.wav"}}"#,
    )
    .expect("decode command envelope");

    assert_eq!(envelope.kind, EnvelopeKind::Command);
    assert_eq!(envelope.message_type, "voice.transcribe");
    assert_eq!(envelope.request_id.as_deref(), Some("stt-1"));
    assert_eq!(envelope.deadline_ms, 250);
    assert_eq!(envelope.payload["audio_path"], "/tmp/input.wav");
}

#[test]
fn decode_normalizes_null_payload_to_empty_object() {
    let envelope = WorkerEnvelope::decode(
        br#"{"schema_version":1,"kind":"command","type":"voice.health","request_id":"health-1","payload":null}"#,
    )
    .expect("decode command envelope");

    assert_eq!(envelope.payload, json!({}));
}
