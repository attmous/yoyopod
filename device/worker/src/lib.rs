use std::io::Write;

use anyhow::Result;
use serde_json::{json, Value};
use yoyopod_protocol::{EnvelopeKind, WorkerEnvelope};

pub fn emit<W>(output: &mut W, envelope: &WorkerEnvelope) -> Result<()>
where
    W: Write + ?Sized,
{
    output.write_all(&envelope.encode()?)?;
    output.flush()?;
    Ok(())
}

pub fn ready_event(domain: &str, payload: Value) -> WorkerEnvelope {
    WorkerEnvelope::event(format!("{domain}.ready"), payload)
}

pub fn health_result(domain: &str, request_id: Option<String>, payload: Value) -> WorkerEnvelope {
    WorkerEnvelope::result(format!("{domain}.health.result"), request_id, payload)
}

pub fn stopped_event(domain: &str, payload: Value) -> WorkerEnvelope {
    WorkerEnvelope::event(format!("{domain}.stopped"), payload)
}

pub fn standard_error(
    domain: &str,
    request_id: Option<String>,
    code: &str,
    message: impl Into<String>,
    retryable: bool,
) -> WorkerEnvelope {
    WorkerEnvelope {
        schema_version: yoyopod_protocol::SUPPORTED_SCHEMA_VERSION,
        kind: EnvelopeKind::Error,
        message_type: format!("{domain}.error"),
        request_id,
        timestamp_ms: 0,
        deadline_ms: 0,
        payload: json!({
            "code": code,
            "message": message.into(),
            "retryable": retryable,
        }),
    }
}
