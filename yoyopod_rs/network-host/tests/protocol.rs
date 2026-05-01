use yoyopod_network_host::protocol::{
    ready_event, stopped_event, EnvelopeKind, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION,
};

#[test]
fn ready_event_uses_network_ready_type() {
    let message = ready_event("config");

    assert_eq!(message.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(message.kind, EnvelopeKind::Event);
    assert_eq!(message.message_type, "network.ready");
    assert_eq!(message.request_id, None);
    assert_eq!(message.timestamp_ms, 0);
    assert_eq!(message.deadline_ms, 0);
    assert_eq!(message.payload["config_dir"], "config");
}

#[test]
fn stopped_event_uses_network_stopped_type() {
    let message = stopped_event("shutdown");

    assert_eq!(message.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(message.kind, EnvelopeKind::Event);
    assert_eq!(message.message_type, "network.stopped");
    assert_eq!(message.payload["reason"], "shutdown");
}

#[test]
fn encode_round_trip_matches_shared_worker_protocol_shape() {
    let encoded = ready_event("config").encode().expect("encode");

    let decoded = WorkerEnvelope::decode(&encoded).expect("decode");

    assert_eq!(decoded.schema_version, SUPPORTED_SCHEMA_VERSION);
    assert_eq!(decoded.kind, EnvelopeKind::Event);
    assert_eq!(decoded.message_type, "network.ready");
    assert_eq!(decoded.request_id, None);
    assert_eq!(decoded.timestamp_ms, 0);
    assert_eq!(decoded.deadline_ms, 0);
    assert_eq!(decoded.payload["config_dir"], "config");
}
