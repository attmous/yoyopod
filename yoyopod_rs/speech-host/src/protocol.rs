use serde_json::json;

pub use yoyopod_protocol::{EnvelopeKind, ProtocolError, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};

pub fn voice_error(
    request_id: Option<String>,
    code: impl Into<String>,
    message: impl Into<String>,
    retryable: bool,
) -> WorkerEnvelope {
    WorkerEnvelope {
        schema_version: SUPPORTED_SCHEMA_VERSION,
        kind: EnvelopeKind::Error,
        message_type: "voice.error".to_string(),
        request_id,
        timestamp_ms: 0,
        deadline_ms: 0,
        payload: json!({
            "code": code.into(),
            "message": message.into(),
            "retryable": retryable,
        }),
    }
}
