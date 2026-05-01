mod support;

use std::fs;
use std::io::{self, Cursor, Read};
use std::time::Duration;

use serde_json::json;

use yoyopod_network_host::runtime::{NetworkRuntime, RecoveryPolicy};
use yoyopod_network_host::snapshot::NetworkLifecycleState;
use yoyopod_network_host::worker::{
    run_with_io, run_with_runtime_io, run_with_runtime_io_and_poll_interval,
};

use crate::support::{
    berlin_fix, command, controlled_input, decode_output, enabled_config, encode_commands,
    ppp_link, registered_modem, retryable_error, roaming_modem, FakeModemController,
};

struct ErroringInput;

impl Read for ErroringInput {
    fn read(&mut self, _buf: &mut [u8]) -> io::Result<usize> {
        Err(io::Error::other("synthetic read failure"))
    }
}

#[test]
fn worker_emits_startup_transition_snapshots_in_order() {
    let modem = FakeModemController::new();
    let runtime = NetworkRuntime::new("config", enabled_config(), modem);
    let mut output = Vec::new();

    run_with_runtime_io(runtime, io::empty(), &mut output).expect("worker exits cleanly");

    let envelopes = decode_output(&output);
    assert_eq!(envelopes[0].message_type, "network.ready");
    assert_eq!(
        envelopes[1..7]
            .iter()
            .map(|envelope| envelope.payload["state"].as_str().unwrap_or_default())
            .collect::<Vec<_>>(),
        vec![
            "probing",
            "ready",
            "registering",
            "registered",
            "ppp_starting",
            "online",
        ]
    );
    assert!(envelopes.iter().any(|envelope| {
        envelope.message_type == "network.snapshot" && envelope.payload["state"] == "off"
    }));
    assert_eq!(
        envelopes.last().expect("final envelope").message_type,
        "network.stopped"
    );
}

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

    run_with_runtime_io(runtime, Cursor::new(input), &mut output).expect("worker exits cleanly");

    let envelopes = decode_output(&output);
    assert_eq!(envelopes[0].message_type, "network.ready");
    assert_eq!(envelopes[6].message_type, "network.snapshot");
    assert_eq!(envelopes[6].payload["state"], "online");

    assert_eq!(
        envelopes[7].kind,
        yoyopod_network_host::protocol::EnvelopeKind::Result
    );
    assert_eq!(envelopes[7].message_type, "network.snapshot");
    assert_eq!(envelopes[7].request_id.as_deref(), Some("gps-1"));
    assert_eq!(
        envelopes[7].payload["snapshot"]["gps"]["last_query_result"],
        "fix"
    );

    assert_eq!(envelopes[8].message_type, "network.snapshot");
    assert_eq!(envelopes[8].payload["gps"]["lat"], 52.52);

    assert_eq!(
        envelopes[9].kind,
        yoyopod_network_host::protocol::EnvelopeKind::Result
    );
    assert_eq!(envelopes[9].message_type, "network.health");
    assert_eq!(envelopes[9].request_id.as_deref(), Some("health-1"));
    assert_eq!(
        envelopes[9].payload["snapshot"]["gps"]["last_query_result"],
        "fix"
    );
    assert_eq!(envelopes[9].payload["snapshot"]["gps"]["lat"], 52.52);

    assert_eq!(
        envelopes[10].kind,
        yoyopod_network_host::protocol::EnvelopeKind::Result
    );
    assert_eq!(envelopes[10].message_type, "network.stopped");
    assert_eq!(envelopes[10].payload["shutdown"], true);
    assert_eq!(envelopes[11].message_type, "network.snapshot");
    assert_eq!(envelopes[11].payload["state"], "ppp_stopping");
    assert_eq!(envelopes[12].message_type, "network.snapshot");
    assert_eq!(envelopes[12].payload["state"], "off");
    assert_eq!(envelopes[13].message_type, "network.stopped");
    assert!(envelopes.iter().all(|envelope| {
        !matches!(
            envelope.message_type.as_str(),
            "network.query_gps" | "network.reset_modem" | "worker.stop" | "network.shutdown"
        )
    }));
}

#[test]
fn worker_polls_runtime_for_autonomous_recovery_without_stdin_commands() {
    let modem = FakeModemController::new();
    modem.set_probe_results([Ok(true), Ok(true)]);
    modem.set_init_results([Ok(registered_modem()), Ok(registered_modem())]);
    modem.set_ppp_results([
        Err(retryable_error("ppp_start_failed", "PPP failed to start")),
        Ok(ppp_link()),
    ]);
    let runtime = NetworkRuntime::new_with_policy(
        "config",
        enabled_config(),
        modem,
        RecoveryPolicy::new(5, 20),
    );
    let (input, handle) = controlled_input();
    let worker = std::thread::spawn(move || {
        let mut output = Vec::new();
        run_with_runtime_io_and_poll_interval(
            runtime,
            input,
            &mut output,
            Duration::from_millis(1),
        )
        .expect("worker exits cleanly");
        output
    });

    handle.sleep(Duration::from_millis(30));
    handle.send(&command("worker.stop", "stop-1", json!({})));
    handle.close();

    let output = worker.join().expect("join worker");
    let envelopes = decode_output(&output);
    let states: Vec<_> = envelopes
        .iter()
        .filter(|envelope| envelope.message_type == "network.snapshot")
        .map(|envelope| {
            envelope.payload["state"]
                .as_str()
                .unwrap_or_default()
                .to_string()
        })
        .collect();
    assert!(states.iter().any(|state| state == "degraded"));
    assert!(states.iter().any(|state| state == "recovering"));
    assert!(states.iter().any(|state| state == "online"));
}

#[test]
fn worker_emits_network_error_for_command_triggered_health_fault() {
    let modem = FakeModemController::new();
    modem.set_ppp_health_results([yoyopod_network_host::modem::PppHealth::ProcessExited]);
    let runtime = NetworkRuntime::new("config", enabled_config(), modem);
    let input = encode_commands(&[
        command("network.health", "health-1", json!({})),
        command("network.shutdown", "shutdown-1", json!({})),
    ]);
    let mut output = Vec::new();

    run_with_runtime_io(runtime, Cursor::new(input), &mut output).expect("worker exits cleanly");

    let envelopes = decode_output(&output);
    let error = envelopes
        .iter()
        .find(|envelope| envelope.kind == yoyopod_network_host::protocol::EnvelopeKind::Error)
        .expect("health should emit network.error");
    assert_eq!(error.message_type, "network.error");
    assert_eq!(error.request_id.as_deref(), Some("health-1"));
    assert_eq!(error.payload["code"], "ppp_process_exited");

    let snapshot = envelopes
        .iter()
        .find(|envelope| {
            envelope.message_type == "network.snapshot"
                && envelope.payload["state"] == "registered"
                && envelope.payload["error_code"] == "ppp_process_exited"
        })
        .expect("registered snapshot expected");
    assert_eq!(
        snapshot.payload["state"],
        json!(NetworkLifecycleState::Registered)
    );
    assert_eq!(snapshot.payload["error_code"], "ppp_process_exited");
    assert!(snapshot.payload["next_retry_at_ms"].as_u64().is_some());
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

    run_with_runtime_io(runtime, Cursor::new(input), &mut output).expect("worker exits cleanly");

    let envelopes = decode_output(&output);
    assert_eq!(
        envelopes
            .iter()
            .find(|envelope| {
                envelope.message_type == "network.snapshot"
                    && envelope.payload["state"] == "degraded"
            })
            .expect("degraded startup snapshot")
            .payload["state"],
        "degraded"
    );
    assert_eq!(
        envelopes
            .iter()
            .find(|envelope| {
                envelope.kind == yoyopod_network_host::protocol::EnvelopeKind::Result
                    && envelope.request_id.as_deref() == Some("reset-1")
            })
            .expect("reset result")
            .payload["snapshot"]["state"],
        "online"
    );
    assert!(envelopes
        .iter()
        .all(|envelope| envelope.message_type != "network.reset_modem"));
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
        Cursor::new(input),
        &mut output,
    )
    .expect("worker should degrade instead of aborting");

    let envelopes = decode_output(&output);
    assert_eq!(envelopes[0].message_type, "network.ready");
    assert_eq!(envelopes[1].message_type, "network.snapshot");
    assert_eq!(envelopes[1].payload["state"], "degraded");
    assert_eq!(envelopes[1].payload["error_code"], "config_load_failed");
    assert_eq!(envelopes[1].payload["retryable"], false);
    assert!(envelopes[1].payload["next_retry_at_ms"].is_null());
}

#[test]
fn worker_emits_network_error_for_gps_query_failure() {
    let modem = FakeModemController::new();
    modem.set_gps_results([Err(retryable_error(
        "gps_query_failed",
        "GPS query timed out",
    ))]);
    let runtime = NetworkRuntime::new("config", enabled_config(), modem);
    let input = encode_commands(&[
        command("network.query_gps", "gps-1", json!({})),
        command("worker.stop", "stop-1", json!({})),
    ]);
    let mut output = Vec::new();

    run_with_runtime_io(runtime, Cursor::new(input), &mut output).expect("worker exits cleanly");

    let envelopes = decode_output(&output);
    let error = envelopes
        .iter()
        .find(|envelope| {
            envelope.kind == yoyopod_network_host::protocol::EnvelopeKind::Error
                && envelope.request_id.as_deref() == Some("gps-1")
        })
        .expect("gps failure should emit network.error");
    assert_eq!(error.message_type, "network.error");
    assert_eq!(error.payload["code"], "gps_query_failed");
    assert!(envelopes
        .iter()
        .all(|envelope| envelope.message_type != "network.query_gps"));
    assert!(envelopes.iter().any(|envelope| {
        envelope.message_type == "network.snapshot"
            && envelope.payload["gps"]["last_query_result"] == "error"
    }));
}

#[test]
fn worker_emits_network_error_for_reset_failure() {
    let modem = FakeModemController::new();
    modem.set_reset_results([Err(retryable_error("reset_failed", "radio reset failed"))]);
    let runtime = NetworkRuntime::new("config", enabled_config(), modem);
    let input = encode_commands(&[
        command("network.reset_modem", "reset-1", json!({})),
        command("worker.stop", "stop-1", json!({})),
    ]);
    let mut output = Vec::new();

    run_with_runtime_io(runtime, Cursor::new(input), &mut output).expect("worker exits cleanly");

    let envelopes = decode_output(&output);
    let error = envelopes
        .iter()
        .find(|envelope| {
            envelope.kind == yoyopod_network_host::protocol::EnvelopeKind::Error
                && envelope.request_id.as_deref() == Some("reset-1")
        })
        .expect("reset failure should emit network.error");
    assert_eq!(error.message_type, "network.error");
    assert_eq!(error.payload["code"], "reset_failed");
    assert!(envelopes.iter().any(|envelope| {
        envelope.message_type == "network.snapshot" && envelope.payload["state"] == "degraded"
    }));
}

#[test]
fn worker_publishes_live_modem_fact_changes_while_running() {
    let modem = FakeModemController::new();
    modem.set_live_fact_results([Ok(roaming_modem())]);
    let runtime = NetworkRuntime::new_with_policy_and_live_fact_poll_interval(
        "config",
        enabled_config(),
        modem,
        RecoveryPolicy::default(),
        5,
    );
    let (input, handle) = controlled_input();
    let worker = std::thread::spawn(move || {
        let mut output = Vec::new();
        run_with_runtime_io_and_poll_interval(
            runtime,
            input,
            &mut output,
            Duration::from_millis(1),
        )
        .expect("worker exits cleanly");
        output
    });

    handle.sleep(Duration::from_millis(30));
    handle.send(&command("worker.stop", "stop-1", json!({})));
    handle.close();

    let output = worker.join().expect("join worker");
    let envelopes = decode_output(&output);
    let live_snapshot = envelopes
        .iter()
        .find(|envelope| {
            envelope.message_type == "network.snapshot"
                && envelope.payload["carrier"] == "Vodafone"
                && envelope.payload["signal"]["csq"] == 9
        })
        .expect("live modem facts snapshot");
    assert_eq!(live_snapshot.payload["state"], "online");
    assert_eq!(live_snapshot.payload["network_type"], "3G");
    assert_eq!(live_snapshot.payload["registered"], true);
}

#[test]
fn worker_emits_network_error_for_command_triggered_live_fact_refresh_failure() {
    let modem = FakeModemController::new();
    modem.set_live_fact_results([Err(retryable_error(
        "signal_read_failed",
        "AT+CSQ timed out",
    ))]);
    let runtime = NetworkRuntime::new("config", enabled_config(), modem);
    let input = encode_commands(&[
        command("network.health", "health-1", json!({})),
        command("worker.stop", "stop-1", json!({})),
    ]);
    let mut output = Vec::new();

    run_with_runtime_io(runtime, Cursor::new(input), &mut output).expect("worker exits cleanly");

    let envelopes = decode_output(&output);
    let error = envelopes
        .iter()
        .find(|envelope| {
            envelope.kind == yoyopod_network_host::protocol::EnvelopeKind::Error
                && envelope.request_id.as_deref() == Some("health-1")
        })
        .expect("health refresh failure should emit network.error");
    assert_eq!(error.message_type, "network.error");
    assert_eq!(error.payload["code"], "signal_read_failed");

    assert!(envelopes.iter().any(|envelope| {
        envelope.message_type == "network.snapshot"
            && envelope.payload["state"] == "degraded"
            && envelope.payload["error_code"] == "signal_read_failed"
    }));
}

#[test]
fn worker_publishes_autonomous_live_fact_refresh_failure_without_command() {
    let modem = FakeModemController::new();
    modem.set_live_fact_results([Err(retryable_error(
        "signal_read_failed",
        "AT+CSQ timed out",
    ))]);
    let runtime = NetworkRuntime::new_with_policy_and_live_fact_poll_interval(
        "config",
        enabled_config(),
        modem,
        RecoveryPolicy::new(5, 20),
        5,
    );
    let (input, handle) = controlled_input();
    let worker = std::thread::spawn(move || {
        let mut output = Vec::new();
        run_with_runtime_io_and_poll_interval(
            runtime,
            input,
            &mut output,
            Duration::from_millis(1),
        )
        .expect("worker exits cleanly");
        output
    });

    handle.sleep(Duration::from_millis(30));
    handle.send(&command("worker.stop", "stop-1", json!({})));
    handle.close();

    let output = worker.join().expect("join worker");
    let envelopes = decode_output(&output);
    assert!(envelopes.iter().any(|envelope| {
        envelope.message_type == "network.snapshot"
            && envelope.payload["state"] == "degraded"
            && envelope.payload["error_code"] == "signal_read_failed"
    }));
}

#[test]
fn worker_eof_triggers_runtime_shutdown_cleanup() {
    let modem = FakeModemController::new();
    let runtime = NetworkRuntime::new("config", enabled_config(), modem.clone());
    let mut output = Vec::new();

    run_with_runtime_io(runtime, io::empty(), &mut output).expect("worker exits cleanly");

    let state = modem.state();
    assert_eq!(state.stop_ppp_calls, 1);
    assert_eq!(state.close_calls, 1);

    let envelopes = decode_output(&output);
    assert!(envelopes.iter().any(|envelope| {
        envelope.message_type == "network.snapshot" && envelope.payload["state"] == "ppp_stopping"
    }));
    assert!(envelopes.iter().any(|envelope| {
        envelope.message_type == "network.snapshot" && envelope.payload["state"] == "off"
    }));
    assert_eq!(
        envelopes.last().expect("final envelope").message_type,
        "network.stopped"
    );
}

#[test]
fn worker_read_error_shuts_runtime_down_before_returning_error() {
    let modem = FakeModemController::new();
    let runtime = NetworkRuntime::new("config", enabled_config(), modem.clone());
    let mut output = Vec::new();

    let error =
        run_with_runtime_io(runtime, ErroringInput, &mut output).expect_err("read error expected");
    assert!(error.to_string().contains("synthetic read failure"));

    let state = modem.state();
    assert_eq!(state.stop_ppp_calls, 1);
    assert_eq!(state.close_calls, 1);

    let envelopes = decode_output(&output);
    assert!(envelopes.iter().any(|envelope| {
        envelope.message_type == "network.snapshot" && envelope.payload["state"] == "off"
    }));
}

#[test]
fn worker_repeated_health_calls_stay_errors_while_runtime_is_degraded() {
    let modem = FakeModemController::new();
    modem.set_ppp_results([Err(retryable_error(
        "ppp_start_failed",
        "PPP failed to start",
    ))]);
    let runtime = NetworkRuntime::new_with_policy(
        "config",
        enabled_config(),
        modem,
        RecoveryPolicy::new(1_000, 2_000),
    );
    let input = encode_commands(&[
        command("network.health", "health-1", json!({})),
        command("network.health", "health-2", json!({})),
        command("worker.stop", "stop-1", json!({})),
    ]);
    let mut output = Vec::new();

    run_with_runtime_io(runtime, Cursor::new(input), &mut output).expect("worker exits cleanly");

    let envelopes = decode_output(&output);
    let health_errors: Vec<_> = envelopes
        .iter()
        .filter(|envelope| {
            envelope.kind == yoyopod_network_host::protocol::EnvelopeKind::Error
                && matches!(
                    envelope.request_id.as_deref(),
                    Some("health-1") | Some("health-2")
                )
        })
        .collect();
    assert_eq!(health_errors.len(), 2);
    assert!(health_errors
        .iter()
        .all(|envelope| envelope.payload["code"] == "ppp_start_failed"));
    assert!(envelopes.iter().all(|envelope| {
        !(envelope.kind == yoyopod_network_host::protocol::EnvelopeKind::Result
            && envelope.message_type == "network.health")
    }));
}
