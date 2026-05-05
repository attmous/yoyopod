use serde_json::{json, Value};

pub use yoyopod_protocol::{EnvelopeKind, ProtocolError, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};

pub type Envelope = WorkerEnvelope;

pub fn event_envelope(message_type: impl Into<String>, payload: Value) -> Envelope {
    let mut envelope = WorkerEnvelope::event(message_type, payload);
    envelope.timestamp_ms = monotonic_millis();
    envelope
}

pub fn error_envelope(code: impl Into<String>, message: impl Into<String>) -> Envelope {
    event_envelope(
        "ui.error",
        json!({
            "code": code.into(),
            "message": message.into(),
        }),
    )
}

pub fn monotonic_millis() -> u64 {
    use std::sync::OnceLock;
    use std::time::Instant;

    static START: OnceLock<Instant> = OnceLock::new();
    START.get_or_init(Instant::now).elapsed().as_millis() as u64
}
