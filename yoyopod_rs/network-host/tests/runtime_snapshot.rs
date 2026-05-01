use serde_json::json;
use yoyopod_network_host::snapshot::{
    GpsSnapshot, NetworkLifecycleState, NetworkRuntimeSnapshot, PppSnapshot, SignalSnapshot,
};

#[test]
fn snapshot_serializes_expected_network_fields() {
    let mut snapshot = NetworkRuntimeSnapshot::offline("config");
    snapshot.enabled = true;
    snapshot.gps_enabled = true;
    snapshot.state = NetworkLifecycleState::Online;
    snapshot.sim_ready = true;
    snapshot.registered = true;
    snapshot.carrier = "Telekom.de".to_string();
    snapshot.network_type = "4G".to_string();
    snapshot.signal = SignalSnapshot {
        csq: Some(17),
        bars: 3,
    };
    snapshot.ppp = PppSnapshot {
        up: true,
        interface: "ppp0".to_string(),
        pid: Some(1234),
        default_route_owned: true,
        last_failure: String::new(),
    };
    snapshot.gps = GpsSnapshot {
        has_fix: false,
        lat: None,
        lng: None,
        altitude: None,
        speed: None,
        timestamp: None,
        last_query_result: "no_fix".to_string(),
    };
    snapshot.updated_at_ms = 42;
    snapshot.refresh_derived();

    let payload = serde_json::to_value(snapshot).expect("serialize");

    assert_eq!(payload["state"], "online");
    assert_eq!(payload["ppp"]["interface"], "ppp0");
    assert_eq!(payload["gps"]["last_query_result"], json!("no_fix"));
    assert_eq!(payload["signal"]["csq"], json!(17));
    assert_eq!(payload["connected"], json!(true));
    assert_eq!(payload["gps_has_fix"], json!(false));
    assert_eq!(payload["connection_type"], json!("4g"));
    assert_eq!(payload["network_status"], json!("online"));
    assert_eq!(payload["gps_status"], json!("searching"));
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
    assert_eq!(payload["connected"], json!(false));
    assert_eq!(payload["gps_has_fix"], json!(false));
    assert_eq!(payload["connection_type"], json!("none"));
    assert_eq!(payload["network_status"], json!("disabled"));
    assert_eq!(payload["gps_status"], json!("disabled"));
}

#[test]
fn degraded_config_snapshot_does_not_claim_automatic_retry() {
    let snapshot = NetworkRuntimeSnapshot::degraded_config_error("config", "bad yaml");
    let payload = serde_json::to_value(&snapshot).expect("serialize");

    assert_eq!(snapshot.state, NetworkLifecycleState::Degraded);
    assert_eq!(payload["error_code"], json!("config_load_failed"));
    assert_eq!(payload["retryable"], json!(false));
    assert_eq!(payload["next_retry_at_ms"], json!(null));
    assert_eq!(payload["network_status"], json!("disabled"));
    assert_eq!(payload["connection_type"], json!("none"));
}

#[test]
fn registered_snapshot_exposes_rust_owned_app_projection_fields() {
    let mut snapshot = NetworkRuntimeSnapshot::offline("config");
    snapshot.enabled = true;
    snapshot.gps_enabled = true;
    snapshot.state = NetworkLifecycleState::Registered;
    snapshot.sim_ready = true;
    snapshot.registered = true;
    snapshot.carrier = "Telekom.de".to_string();
    snapshot.network_type = "4G".to_string();
    snapshot.signal = SignalSnapshot {
        csq: Some(12),
        bars: 2,
    };
    snapshot.gps = GpsSnapshot {
        has_fix: true,
        lat: Some(48.8566),
        lng: Some(2.3522),
        altitude: Some(35.0),
        speed: Some(0.0),
        timestamp: Some("2026-04-30T10:00:00Z".to_string()),
        last_query_result: "fix".to_string(),
    };
    snapshot.refresh_derived();

    let payload = serde_json::to_value(snapshot).expect("serialize");

    assert_eq!(payload["connected"], json!(false));
    assert_eq!(payload["gps_has_fix"], json!(true));
    assert_eq!(payload["connection_type"], json!("4g"));
    assert_eq!(payload["network_status"], json!("registered"));
    assert_eq!(payload["gps_status"], json!("fix"));
}

#[test]
fn snapshot_serializes_rust_owned_app_and_view_projections() {
    let mut snapshot = NetworkRuntimeSnapshot::offline("config");
    snapshot.enabled = true;
    snapshot.gps_enabled = true;
    snapshot.state = NetworkLifecycleState::Online;
    snapshot.sim_ready = true;
    snapshot.registered = true;
    snapshot.carrier = "Telekom.de".to_string();
    snapshot.network_type = "4G".to_string();
    snapshot.signal = SignalSnapshot {
        csq: Some(17),
        bars: 3,
    };
    snapshot.ppp = PppSnapshot {
        up: true,
        interface: "ppp0".to_string(),
        pid: Some(1234),
        default_route_owned: true,
        last_failure: String::new(),
    };
    snapshot.gps = GpsSnapshot {
        has_fix: true,
        lat: Some(48.8738),
        lng: Some(2.3522),
        altitude: Some(349.6),
        speed: Some(0.0),
        timestamp: Some("2026-04-30T10:00:00Z".to_string()),
        last_query_result: "fix".to_string(),
    };
    snapshot.refresh_derived();

    let payload = serde_json::to_value(snapshot).expect("serialize");

    assert_eq!(payload["app_state"]["network_enabled"], json!(true));
    assert_eq!(payload["app_state"]["signal_bars"], json!(3));
    assert_eq!(payload["app_state"]["connected"], json!(true));
    assert_eq!(payload["app_state"]["gps_has_fix"], json!(true));
    assert_eq!(
        payload["views"]["setup"]["network_rows"][0],
        json!(["Status", "Online"])
    );
    assert_eq!(
        payload["views"]["setup"]["gps_rows"][0],
        json!(["Fix", "Yes"])
    );
    assert_eq!(
        payload["views"]["setup"]["gps_refresh_allowed"],
        json!(true)
    );
    assert_eq!(payload["views"]["cli"]["probe_ok"], json!(true));
    assert_eq!(payload["views"]["cli"]["probe_error"], json!(""));
    assert_eq!(
        payload["views"]["cli"]["status_lines"][0],
        json!("phase=online")
    );
}
