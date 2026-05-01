use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use thiserror::Error;

use crate::snapshot::NetworkRuntimeSnapshot;

pub const SUPPORTED_SCHEMA_VERSION: u16 = 1;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EnvelopeKind {
    Command,
    Event,
    Result,
    Error,
    Heartbeat,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct WorkerEnvelope {
    #[serde(default = "default_schema_version")]
    pub schema_version: u16,
    pub kind: EnvelopeKind,
    #[serde(rename = "type")]
    pub message_type: String,
    #[serde(default)]
    pub request_id: Option<String>,
    #[serde(default)]
    pub timestamp_ms: u64,
    #[serde(default)]
    pub deadline_ms: u64,
    #[serde(default = "empty_payload")]
    pub payload: Value,
}

#[derive(Debug, Error)]
pub enum ProtocolError {
    #[error("invalid JSON worker envelope: {0}")]
    InvalidJson(#[from] serde_json::Error),
    #[error("unsupported schema_version {actual}; expected {expected}")]
    UnsupportedSchema { actual: u16, expected: u16 },
    #[error("invalid worker envelope: {0}")]
    InvalidEnvelope(String),
}

fn default_schema_version() -> u16 {
    SUPPORTED_SCHEMA_VERSION
}

fn empty_payload() -> Value {
    json!({})
}

impl WorkerEnvelope {
    pub fn decode(line: &[u8]) -> Result<Self, ProtocolError> {
        let envelope: WorkerEnvelope = serde_json::from_slice(line)?;
        envelope.validate()?;
        Ok(envelope)
    }

    pub fn encode(&self) -> Result<Vec<u8>, ProtocolError> {
        self.validate()?;
        let mut encoded = serde_json::to_vec(self)?;
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
        message_type: impl Into<String>,
        request_id: Option<String>,
        code: impl Into<String>,
        message: impl Into<String>,
    ) -> Self {
        Self {
            schema_version: SUPPORTED_SCHEMA_VERSION,
            kind: EnvelopeKind::Error,
            message_type: message_type.into(),
            request_id,
            timestamp_ms: 0,
            deadline_ms: 0,
            payload: json!({
                "code": code.into(),
                "message": message.into(),
            }),
        }
    }

    pub fn validate(&self) -> Result<(), ProtocolError> {
        if self.schema_version != SUPPORTED_SCHEMA_VERSION {
            return Err(ProtocolError::UnsupportedSchema {
                actual: self.schema_version,
                expected: SUPPORTED_SCHEMA_VERSION,
            });
        }
        if self.message_type.trim().is_empty() {
            return Err(ProtocolError::InvalidEnvelope(
                "type must be a non-empty string".to_string(),
            ));
        }
        if !self.payload.is_object() {
            return Err(ProtocolError::InvalidEnvelope(
                "payload must be an object".to_string(),
            ));
        }
        Ok(())
    }
}

pub fn ready_event(config_dir: &str) -> WorkerEnvelope {
    WorkerEnvelope::event("network.ready", json!({ "config_dir": config_dir }))
}

pub fn snapshot_event(snapshot: &NetworkRuntimeSnapshot) -> WorkerEnvelope {
    WorkerEnvelope::event(
        "network.snapshot",
        serde_json::to_value(snapshot).expect("network snapshot should serialize"),
    )
}

pub fn stopped_event(reason: &str) -> WorkerEnvelope {
    WorkerEnvelope::event("network.stopped", json!({ "reason": reason }))
}

pub fn snapshot_result(request_id: Option<String>, snapshot: &NetworkRuntimeSnapshot) -> WorkerEnvelope {
    WorkerEnvelope::result(
        "network.snapshot",
        request_id,
        json!({
            "snapshot": snapshot,
        }),
    )
}

pub fn health_result(request_id: Option<String>, snapshot: &NetworkRuntimeSnapshot) -> WorkerEnvelope {
    WorkerEnvelope::result(
        "network.health",
        request_id,
        json!({
            "snapshot": snapshot,
        }),
    )
}

pub fn stopped_result(request_id: Option<String>, reason: &str) -> WorkerEnvelope {
    WorkerEnvelope::result(
        "network.stopped",
        request_id,
        json!({
            "shutdown": true,
            "reason": reason,
        }),
    )
}
