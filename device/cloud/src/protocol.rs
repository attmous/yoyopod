use serde_json::json;

use crate::snapshot::CloudStatusSnapshot;

pub use yoyopod_protocol::{EnvelopeKind, ProtocolError, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};

pub fn ready_event(config_dir: &str) -> WorkerEnvelope {
    WorkerEnvelope::event(
        "cloud.ready",
        json!({
            "config_dir": config_dir,
            "capabilities": [
                "mqtt",
                "telemetry",
                "heartbeat",
                "battery",
                "connectivity",
                "ack",
                "command_subscribe"
            ],
        }),
    )
}

pub fn snapshot_event(snapshot: &CloudStatusSnapshot) -> WorkerEnvelope {
    WorkerEnvelope::event(
        "cloud.snapshot",
        serde_json::to_value(snapshot).expect("cloud snapshot should serialize"),
    )
}

pub fn snapshot_result(
    request_id: Option<String>,
    snapshot: &CloudStatusSnapshot,
) -> WorkerEnvelope {
    health_result(request_id, snapshot)
}

pub fn health_result(request_id: Option<String>, snapshot: &CloudStatusSnapshot) -> WorkerEnvelope {
    WorkerEnvelope::result(
        "cloud.health",
        request_id,
        json!({
            "snapshot": snapshot,
        }),
    )
}

pub fn stopped_event(reason: &str) -> WorkerEnvelope {
    WorkerEnvelope::event("cloud.stopped", json!({ "reason": reason }))
}

pub fn stopped_result(request_id: Option<String>, reason: &str) -> WorkerEnvelope {
    WorkerEnvelope::result(
        "cloud.stopped",
        request_id,
        json!({
            "shutdown": true,
            "reason": reason,
        }),
    )
}
