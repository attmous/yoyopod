use serde_json::json;
use yoyopod_network_host::snapshot::{
    GpsSnapshot, NetworkLifecycleState, NetworkRuntimeSnapshot, PppSnapshot, SignalSnapshot,
};

#[test]
fn snapshot_serializes_expected_network_fields() {
    let snapshot = NetworkRuntimeSnapshot {
        enabled: true,
        gps_enabled: true,
        config_dir: "config".to_string(),
        state: NetworkLifecycleState::Online,
        sim_ready: true,
        registered: true,
        carrier: "Telekom.de".to_string(),
        network_type: "4G".to_string(),
        signal: SignalSnapshot {
            csq: Some(17),
            bars: 3,
        },
        ppp: PppSnapshot {
            up: true,
            interface: "ppp0".to_string(),
            pid: Some(1234),
            default_route_owned: true,
            last_failure: String::new(),
        },
        gps: GpsSnapshot {
            has_fix: false,
            lat: None,
            lng: None,
            altitude: None,
            speed: None,
            timestamp: None,
            last_query_result: "no_fix".to_string(),
        },
        recovering: false,
        retryable: false,
        reconnect_attempts: 0,
        next_retry_at_ms: None,
        error_code: String::new(),
        error_message: String::new(),
        updated_at_ms: 42,
    };

    let payload = serde_json::to_value(snapshot).expect("serialize");

    assert_eq!(payload["state"], "online");
    assert_eq!(payload["ppp"]["interface"], "ppp0");
    assert_eq!(payload["gps"]["last_query_result"], json!("no_fix"));
    assert_eq!(payload["signal"]["csq"], json!(17));
    assert_eq!(payload["updated_at_ms"], json!(42));
}

#[test]
fn offline_snapshot_uses_canonical_baseline_shape() {
    let snapshot = NetworkRuntimeSnapshot::offline("config");
    let payload = serde_json::to_value(&snapshot).expect("serialize");

    assert_eq!(snapshot.config_dir, "config");
    assert_eq!(snapshot.state, NetworkLifecycleState::Off);
    assert_eq!(payload["enabled"], json!(false));
    assert_eq!(payload["gps_enabled"], json!(false));
    assert_eq!(payload["state"], json!("off"));
    assert_eq!(payload["ppp"]["up"], json!(false));
    assert_eq!(payload["gps"]["last_query_result"], json!("idle"));
}
