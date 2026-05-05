use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use thiserror::Error;

pub const SUPPORTED_SCHEMA_VERSION: u8 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Deserialize, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum EnvelopeKind {
    Command,
    Event,
    Result,
    Error,
    Heartbeat,
}

#[derive(Debug, Clone, PartialEq, Deserialize, Serialize)]
pub struct WorkerEnvelope {
    #[serde(default = "default_schema_version")]
    pub schema_version: u8,
    pub kind: EnvelopeKind,
    #[serde(rename = "type")]
    pub message_type: String,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub request_id: Option<String>,
    #[serde(default)]
    pub timestamp_ms: i64,
    #[serde(default)]
    pub deadline_ms: i64,
    #[serde(default = "empty_payload")]
    pub payload: Value,
}

#[derive(Debug, Error)]
pub enum ProtocolError {
    #[error("invalid JSON worker envelope: {0}")]
    InvalidJson(#[from] serde_json::Error),
    #[error("unsupported worker schema_version {actual}; expected {expected}")]
    UnsupportedSchemaVersion { actual: u8, expected: u8 },
    #[error("invalid worker envelope kind {0:?}")]
    InvalidKind(Value),
    #[error("worker envelope type must be a non-empty string")]
    EmptyType,
    #[error("worker envelope timestamp_ms must be non-negative")]
    NegativeTimestamp,
    #[error("worker envelope deadline_ms must be non-negative")]
    NegativeDeadline,
}

impl WorkerEnvelope {
    pub fn decode(line: &[u8]) -> Result<Self, ProtocolError> {
        let value: Value = serde_json::from_slice(line)?;
        validate_kind_shape(&value)?;
        let mut envelope: Self = serde_json::from_value(value)?;
        envelope.normalize_payload();
        envelope.validate()?;
        Ok(envelope)
    }

    pub fn encode(&self) -> Result<Vec<u8>, ProtocolError> {
        let mut envelope = self.clone();
        envelope.normalize_payload();
        envelope.validate()?;
        let mut encoded = serde_json::to_vec(&envelope)?;
        encoded.push(b'\n');
        Ok(encoded)
    }

    pub fn event(message_type: impl Into<String>, payload: Value) -> Self {
        Self {
            schema_version: SUPPORTED_SCHEMA_VERSION,
            kind: EnvelopeKind::Event,
            message_type: message_type.into(),
            request_id: None,
            timestamp_ms: 0,
            deadline_ms: 0,
            payload,
        }
    }

    pub fn result(
        message_type: impl Into<String>,
        request_id: Option<String>,
        payload: Value,
    ) -> Self {
        Self {
            schema_version: SUPPORTED_SCHEMA_VERSION,
            kind: EnvelopeKind::Result,
            message_type: message_type.into(),
            request_id,
            timestamp_ms: 0,
            deadline_ms: 0,
            payload,
        }
    }

    pub fn error(
        request_id: Option<String>,
        code: impl Into<String>,
        message: impl Into<String>,
        retryable: bool,
    ) -> Self {
        Self {
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

    fn validate(&self) -> Result<(), ProtocolError> {
        if self.schema_version != SUPPORTED_SCHEMA_VERSION {
            return Err(ProtocolError::UnsupportedSchemaVersion {
                actual: self.schema_version,
                expected: SUPPORTED_SCHEMA_VERSION,
            });
        }
        if self.message_type.trim().is_empty() {
            return Err(ProtocolError::EmptyType);
        }
        if self.timestamp_ms < 0 {
            return Err(ProtocolError::NegativeTimestamp);
        }
        if self.deadline_ms < 0 {
            return Err(ProtocolError::NegativeDeadline);
        }
        Ok(())
    }

    fn normalize_payload(&mut self) {
        if self.payload.is_null() {
            self.payload = empty_payload();
        }
    }
}

fn validate_kind_shape(value: &Value) -> Result<(), ProtocolError> {
    let Some(kind) = value.get("kind") else {
        return Err(ProtocolError::InvalidKind(Value::Null));
    };
    let Some(kind) = kind.as_str() else {
        return Err(ProtocolError::InvalidKind(kind.clone()));
    };
    match kind {
        "command" | "event" | "result" | "error" | "heartbeat" => Ok(()),
        _ => Err(ProtocolError::InvalidKind(Value::String(kind.to_string()))),
    }
}

const fn default_schema_version() -> u8 {
    SUPPORTED_SCHEMA_VERSION
}

fn empty_payload() -> Value {
    json!({})
}
