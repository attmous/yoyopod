use serde_json::json;

use crate::snapshot::PowerStatusSnapshot;

pub use yoyopod_protocol::{EnvelopeKind, ProtocolError, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};
use yoyopod_worker::{ready_event as worker_ready_event, stopped_event as worker_stopped_event};

pub fn ready_event() -> WorkerEnvelope {
    worker_ready_event(
        "power",
        json!({
            "capabilities": [
                "telemetry",
                "battery",
                "rtc",
                "rtc_control",
                "watchdog",
                "health"
            ],
        }),
    )
}

pub fn snapshot_event(snapshot: &PowerStatusSnapshot) -> WorkerEnvelope {
    WorkerEnvelope::event(
        "power.snapshot",
        serde_json::to_value(snapshot).expect("power snapshot should serialize"),
    )
}

pub fn snapshot_result(
    request_id: Option<String>,
    snapshot: &PowerStatusSnapshot,
) -> WorkerEnvelope {
    WorkerEnvelope::result(
        "power.health",
        request_id,
        serde_json::to_value(snapshot).expect("power snapshot should serialize"),
    )
}

pub fn control_result(
    message_type: impl Into<String>,
    request_id: Option<String>,
    snapshot: &PowerStatusSnapshot,
) -> WorkerEnvelope {
    WorkerEnvelope::result(
        message_type,
        request_id,
        json!({
            "ok": true,
            "snapshot": snapshot,
        }),
    )
}

pub fn stopped_event(reason: &str) -> WorkerEnvelope {
    worker_stopped_event("power", json!({ "reason": reason }))
}

pub fn stopped_result(request_id: Option<String>, reason: &str) -> WorkerEnvelope {
    WorkerEnvelope::result(
        "power.stopped",
        request_id,
        json!({
            "shutdown": true,
            "reason": reason,
        }),
    )
}
