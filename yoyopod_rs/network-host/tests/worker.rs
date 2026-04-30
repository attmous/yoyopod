mod support;

use std::fs;

use serde_json::json;

use yoyopod_network_host::runtime::NetworkRuntime;
use yoyopod_network_host::snapshot::NetworkLifecycleState;
use yoyopod_network_host::worker::{run_with_io, run_with_runtime_io};

use crate::support::{
    berlin_fix, command, decode_output, enabled_config, encode_commands, ppp_link,
    registered_modem, retryable_error, FakeModemController,
};

#[test]
fn worker_keeps_runtime_snapshot_across_query_gps_and_health_commands() {
    let modem = FakeModemController::new();
    modem.set_gps_results([Ok(Some(berlin_fix()))]);
    let runtime = NetworkRuntime::new("config", enabled_config(), modem);
    let input = encode_commands(&[
        command("network.query_gps", "gps-1", json!({})),
        command("network.health", "health-1", json!({})),
        command("worker.stop", "stop-1", json!({})),
    ]);
    let mut output = Vec::new();

    run_with_runtime_io(runtime, input.as_slice(), &mut output).expect("worker exits cleanly");

    let envelopes = decode_output(&output);
    assert_eq!(envelopes[0].message_type, "network.ready");
    assert_eq!(envelopes[1].message_type, "network.snapshot");
    assert_eq!(envelopes[1].payload["state"], "online");

    assert_eq!(
        envelopes[2].kind,
        yoyopod_network_host::protocol::EnvelopeKind::Result
    );
    assert_eq!(envelopes[2].message_type, "network.query_gps");
    assert_eq!(envelopes[2].request_id.as_deref(), Some("gps-1"));
    assert_eq!(
        envelopes[2].payload["snapshot"]["gps"]["last_query_result"],
        "fix"
    );

    assert_eq!(envelopes[3].message_type, "network.snapshot");
    assert_eq!(envelopes[3].payload["gps"]["lat"], 52.52);

    assert_eq!(
        envelopes[4].kind,
        yoyopod_network_host::protocol::EnvelopeKind::Result
    );
    assert_eq!(envelopes[4].message_type, "network.health");
    assert_eq!(envelopes[4].request_id.as_deref(), Some("health-1"));
    assert_eq!(
        envelopes[4].payload["snapshot"]["gps"]["last_query_result"],
        "fix"
    );
    assert_eq!(envelopes[4].payload["snapshot"]["gps"]["lat"], 52.52);

    assert_eq!(
        envelopes[5].kind,
        yoyopod_network_host::protocol::EnvelopeKind::Result
    );
    assert_eq!(envelopes[5].message_type, "worker.stop");
    assert_eq!(envelopes[5].payload["shutdown"], true);
    assert_eq!(envelopes[6].message_type, "network.snapshot");
    assert_eq!(envelopes[6].payload["state"], "off");
    assert_eq!(envelopes[7].message_type, "network.stopped");
}

#[test]
fn worker_health_reconciles_stale_online_state_when_ppp_link_dies() {
    let modem = FakeModemController::new();
    modem.set_ppp_health_results([yoyopod_network_host::modem::PppHealth::ProcessExited]);
    let runtime = NetworkRuntime::new("config", enabled_config(), modem);
    let input = encode_commands(&[
        command("network.health", "health-1", json!({})),
        command("network.shutdown", "shutdown-1", json!({})),
    ]);
    let mut output = Vec::new();

    run_with_runtime_io(runtime, input.as_slice(), &mut output).expect("worker exits cleanly");

    let envelopes = decode_output(&output);
    assert_eq!(envelopes[2].message_type, "network.health");
    assert_eq!(
        envelopes[2].payload["snapshot"]["state"],
        json!(NetworkLifecycleState::Registered)
    );
    assert_eq!(
        envelopes[2].payload["snapshot"]["error_code"],
        "ppp_process_exited"
    );
    assert_eq!(envelopes[3].message_type, "network.snapshot");
    assert_eq!(envelopes[3].payload["state"], "registered");
}

#[test]
fn worker_reset_modem_returns_recovered_snapshot_and_shutdown_stops_runtime() {
    let modem = FakeModemController::new();
    modem.set_probe_results([
        Err(retryable_error("probe_failed", "AT ping timed out")),
        Ok(true),
    ]);
    modem.set_init_results([Ok(registered_modem())]);
    modem.set_ppp_results([Ok(ppp_link())]);
    let runtime = NetworkRuntime::new("config", enabled_config(), modem.clone());
    let input = encode_commands(&[
        command("network.reset_modem", "reset-1", json!({})),
        command("network.shutdown", "shutdown-1", json!({})),
    ]);
    let mut output = Vec::new();

    run_with_runtime_io(runtime, input.as_slice(), &mut output).expect("worker exits cleanly");

    let envelopes = decode_output(&output);
    assert_eq!(envelopes[1].payload["state"], "degraded");
    assert_eq!(envelopes[2].message_type, "network.reset_modem");
    assert_eq!(envelopes[2].payload["snapshot"]["state"], "online");
    assert_eq!(envelopes[2].payload["snapshot"]["reconnect_attempts"], 1);
    assert_eq!(envelopes[3].message_type, "network.snapshot");
    assert_eq!(envelopes[3].payload["state"], "online");
    assert_eq!(envelopes[4].message_type, "network.shutdown");
    assert_eq!(envelopes[4].payload["shutdown"], true);
    assert_eq!(envelopes[5].message_type, "network.snapshot");
    assert_eq!(envelopes[5].payload["state"], "off");
    assert_eq!(modem.state().reset_calls, 1);
}

#[test]
fn worker_preserves_degraded_snapshot_when_config_load_fails() {
    let temp = tempfile::tempdir().expect("tempdir");
    let config_dir = temp.path().join("config");
    let network_dir = config_dir.join("network");
    fs::create_dir_all(&network_dir).expect("network dir");
    fs::write(network_dir.join("cellular.yaml"), "network: [broken\n").expect("write config");
    let input = encode_commands(&[command("network.shutdown", "shutdown-1", json!({}))]);
    let mut output = Vec::new();

    run_with_io(
        config_dir.to_str().expect("config dir"),
        input.as_slice(),
        &mut output,
    )
    .expect("worker should degrade instead of aborting");

    let envelopes = decode_output(&output);
    assert_eq!(envelopes[0].message_type, "network.ready");
    assert_eq!(envelopes[1].message_type, "network.snapshot");
    assert_eq!(envelopes[1].payload["state"], "degraded");
    assert_eq!(envelopes[1].payload["error_code"], "config_load_failed");
}
