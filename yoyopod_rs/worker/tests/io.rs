use serde_json::json;
use yoyopod_protocol::WorkerEnvelope;
use yoyopod_worker::{emit, health_result, ready_event, standard_error, stopped_event};

#[test]
fn emit_writes_one_newline_delimited_envelope() {
    let mut output = Vec::new();
    emit(
        &mut output,
        &WorkerEnvelope::event("power.ready", json!({"ready": true})),
    )
    .expect("emit");

    let rendered = String::from_utf8(output).expect("utf8");
    assert!(rendered.ends_with('\n'));
    assert!(rendered.contains(r#""type":"power.ready""#));
}

#[test]
fn ready_event_uses_domain_namespace() {
    let envelope = ready_event("power", json!({"ready": true}));

    assert_eq!(envelope.message_type, "power.ready");
    assert_eq!(envelope.payload["ready"], true);
}

#[test]
fn health_result_uses_domain_namespace() {
    let envelope = health_result("power", Some("req-1".to_string()), json!({"healthy": true}));

    assert_eq!(envelope.message_type, "power.health.result");
    assert_eq!(envelope.request_id.as_deref(), Some("req-1"));
    assert_eq!(envelope.payload["healthy"], true);
}

#[test]
fn stopped_event_uses_domain_namespace() {
    let envelope = stopped_event("power", json!({"reason": "shutdown"}));

    assert_eq!(envelope.message_type, "power.stopped");
    assert_eq!(envelope.payload["reason"], "shutdown");
}

#[test]
fn standard_error_uses_domain_namespace() {
    let envelope = standard_error(
        "power",
        Some("req-1".to_string()),
        "invalid_payload",
        "bad battery payload",
        false,
    );

    assert_eq!(envelope.message_type, "power.error");
    assert_eq!(envelope.request_id.as_deref(), Some("req-1"));
    assert_eq!(envelope.payload["code"], "invalid_payload");
    assert_eq!(envelope.payload["retryable"], false);
}
