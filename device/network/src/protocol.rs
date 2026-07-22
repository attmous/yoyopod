use serde_json::json;

use crate::snapshot::NetworkRuntimeSnapshot;
use crate::wifi::{WifiChangeOperation, WifiState};

pub use yoyopod_protocol::{EnvelopeKind, ProtocolError, WorkerEnvelope, SUPPORTED_SCHEMA_VERSION};

pub fn ready_event(config_dir: &str) -> WorkerEnvelope {
    WorkerEnvelope::event("network.ready", json!({ "config_dir": config_dir }))
}

pub fn snapshot_event(snapshot: &NetworkRuntimeSnapshot) -> WorkerEnvelope {
    WorkerEnvelope::event(
        "network.snapshot",
        serde_json::to_value(snapshot).expect("network snapshot should serialize"),
    )
}

pub fn wifi_state_event(state: &WifiState) -> WorkerEnvelope {
    WorkerEnvelope::event(
        "wifi_state",
        serde_json::to_value(state).expect("Wi-Fi state should serialize"),
    )
}

pub fn wifi_state_result(request_id: Option<String>, state: &WifiState) -> WorkerEnvelope {
    WorkerEnvelope::result(
        "wifi_state",
        request_id,
        json!({
            "state": state,
        }),
    )
}

pub fn wifi_change_candidate_event(
    command_id: &str,
    profile_id: &str,
    operation: WifiChangeOperation,
    attempt: u8,
    reported_at: u64,
) -> WorkerEnvelope {
    WorkerEnvelope::event(
        "wifi_change_candidate",
        json!({
            "schema_version": 1,
            "command_id": command_id,
            "profile_id": profile_id,
            "operation": operation,
            "attempt": attempt,
            "event_id": format!("{command_id}:{attempt}"),
            "reported_at": reported_at,
        }),
    )
}

pub fn stopped_event(reason: &str) -> WorkerEnvelope {
    WorkerEnvelope::event("network.stopped", json!({ "reason": reason }))
}

pub fn snapshot_result(
    request_id: Option<String>,
    snapshot: &NetworkRuntimeSnapshot,
) -> WorkerEnvelope {
    WorkerEnvelope::result(
        "network.snapshot",
        request_id,
        json!({
            "snapshot": snapshot,
        }),
    )
}

pub fn health_result(
    request_id: Option<String>,
    snapshot: &NetworkRuntimeSnapshot,
) -> WorkerEnvelope {
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
