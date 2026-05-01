mod support;

use yoyopod_network_host::runtime::{NetworkRuntime, RecoveryPolicy};
use yoyopod_network_host::snapshot::NetworkLifecycleState;

use crate::support::{
    berlin_fix, blank_apn_config, enabled_config, fatal_error, ppp_link, registered_modem,
    retryable_error, roaming_modem, unregistered_modem, FakeModemController,
};

#[test]
fn start_reaches_online_when_modem_probe_init_and_ppp_succeed() {
    let modem = FakeModemController::new();
    let mut runtime = NetworkRuntime::new("config", enabled_config(), modem.clone());

    let snapshot = runtime.start().clone();

    assert_eq!(snapshot.state, NetworkLifecycleState::Online);
    assert!(snapshot.enabled);
    assert!(snapshot.gps_enabled);
    assert!(snapshot.sim_ready);
    assert!(snapshot.registered);
    assert_eq!(snapshot.carrier, "T-Mobile");
    assert_eq!(snapshot.network_type, "4G");
    assert_eq!(snapshot.signal.csq, Some(20));
    assert!(snapshot.ppp.up);
    assert_eq!(snapshot.ppp.interface, "ppp0");
    assert_eq!(snapshot.ppp.pid, Some(4242));
    assert_eq!(snapshot.error_code, "");
    assert_eq!(snapshot.error_message, "");

    let state = modem.state();
    assert_eq!(state.open_calls, 1);
    assert_eq!(state.start_ppp_apns, vec![Some("internet".to_string())]);
}

#[test]
fn start_skips_blank_apn_reconfiguration() {
    let modem = FakeModemController::new();
    let mut runtime = NetworkRuntime::new("config", blank_apn_config(), modem.clone());

    let snapshot = runtime.start().clone();

    assert_eq!(snapshot.state, NetworkLifecycleState::Online);
    assert_eq!(modem.state().start_ppp_apns, vec![None]);
}

#[test]
fn start_emits_canonical_startup_states_and_schedules_retry_after_ppp_failure() {
    let modem = FakeModemController::new();
    modem.set_ppp_results([Err(retryable_error(
        "ppp_start_failed",
        "PPP failed to start",
    ))]);
    let mut runtime = NetworkRuntime::new_with_policy(
        "config",
        enabled_config(),
        modem,
        RecoveryPolicy::new(100, 400),
    );

    runtime.start_at(1_000);
    let snapshots = runtime.drain_snapshot_events();
    let states: Vec<_> = snapshots.iter().map(|snapshot| snapshot.state).collect();
    let snapshot = snapshots.last().expect("final startup snapshot");

    assert_eq!(
        states,
        vec![
            NetworkLifecycleState::Probing,
            NetworkLifecycleState::Ready,
            NetworkLifecycleState::Registering,
            NetworkLifecycleState::Registered,
            NetworkLifecycleState::PppStarting,
            NetworkLifecycleState::Degraded,
        ]
    );
    assert_eq!(snapshot.error_code, "ppp_start_failed");
    assert_eq!(snapshot.error_message, "PPP failed to start");
    assert!(snapshot.retryable);
    assert_eq!(snapshot.reconnect_attempts, 1);
    assert_eq!(snapshot.next_retry_at_ms, Some(1_100));
}

#[test]
fn tick_retries_failed_bringup_with_bounded_backoff_until_cap() {
    let modem = FakeModemController::new();
    modem.set_ppp_results([
        Err(retryable_error("ppp_start_failed", "first")),
        Err(retryable_error("ppp_start_failed", "second")),
        Err(retryable_error("ppp_start_failed", "third")),
    ]);
    let mut runtime = NetworkRuntime::new_with_policy(
        "config",
        enabled_config(),
        modem,
        RecoveryPolicy::new(100, 250),
    );

    runtime.start_at(0);
    runtime.drain_snapshot_events();
    assert_eq!(runtime.snapshot().next_retry_at_ms, Some(100));
    assert_eq!(runtime.snapshot().reconnect_attempts, 1);

    runtime.tick_at(100);
    runtime.drain_snapshot_events();
    assert_eq!(runtime.snapshot().state, NetworkLifecycleState::Degraded);
    assert_eq!(runtime.snapshot().reconnect_attempts, 2);
    assert_eq!(runtime.snapshot().next_retry_at_ms, Some(300));

    runtime.tick_at(300);
    runtime.drain_snapshot_events();
    assert_eq!(runtime.snapshot().state, NetworkLifecycleState::Degraded);
    assert_eq!(runtime.snapshot().reconnect_attempts, 3);
    assert_eq!(runtime.snapshot().next_retry_at_ms, Some(550));
}

#[test]
fn query_gps_updates_snapshot_with_fix_without_dropping_online_state() {
    let modem = FakeModemController::new();
    modem.set_gps_results([Ok(Some(berlin_fix()))]);
    let mut runtime = NetworkRuntime::new("config", enabled_config(), modem.clone());
    runtime.start();

    let snapshot = runtime.query_gps().clone();

    assert_eq!(snapshot.state, NetworkLifecycleState::Online);
    assert!(snapshot.gps.has_fix);
    assert_eq!(snapshot.gps.lat, Some(52.52));
    assert_eq!(snapshot.gps.lng, Some(13.405));
    assert_eq!(snapshot.gps.last_query_result, "fix");
    assert_eq!(modem.state().query_gps_calls, 1);
}

#[test]
fn tick_reconciles_ppp_loss_and_recovers_automatically() {
    let modem = FakeModemController::new();
    modem.set_probe_results([Ok(true), Ok(true)]);
    modem.set_init_results([Ok(registered_modem()), Ok(registered_modem())]);
    modem.set_ppp_results([Ok(ppp_link()), Ok(ppp_link())]);
    modem.set_ppp_health_results([yoyopod_network_host::modem::PppHealth::ProcessExited]);
    let mut runtime = NetworkRuntime::new_with_policy(
        "config",
        enabled_config(),
        modem.clone(),
        RecoveryPolicy::new(100, 400),
    );

    runtime.start_at(1_000);
    runtime.drain_snapshot_events();

    runtime.tick_at(2_000);
    let dropped = runtime.drain_snapshot_events();
    assert_eq!(
        dropped
            .iter()
            .map(|snapshot| snapshot.state)
            .collect::<Vec<_>>(),
        vec![NetworkLifecycleState::Registered]
    );
    let snapshot = runtime.snapshot().clone();
    assert_eq!(snapshot.error_code, "ppp_process_exited");
    assert_eq!(snapshot.reconnect_attempts, 1);
    assert_eq!(snapshot.next_retry_at_ms, Some(2_100));

    runtime.tick_at(2_100);
    let recovered = runtime.drain_snapshot_events();
    assert_eq!(
        recovered
            .iter()
            .map(|snapshot| snapshot.state)
            .collect::<Vec<_>>(),
        vec![
            NetworkLifecycleState::Recovering,
            NetworkLifecycleState::Probing,
            NetworkLifecycleState::Ready,
            NetworkLifecycleState::Registering,
            NetworkLifecycleState::Registered,
            NetworkLifecycleState::PppStarting,
            NetworkLifecycleState::Online,
        ]
    );
    assert_eq!(runtime.snapshot().state, NetworkLifecycleState::Online);
    assert_eq!(modem.state().reset_calls, 1);
}

#[test]
fn reset_modem_retries_bringup_and_tracks_reconnect_attempts() {
    let modem = FakeModemController::new();
    modem.set_probe_results([Ok(true), Ok(true)]);
    modem.set_init_results([Ok(registered_modem()), Ok(registered_modem())]);
    modem.set_ppp_results([
        Err(fatal_error("ppp_start_failed", "PPP failed to start")),
        Ok(ppp_link()),
    ]);
    let mut runtime = NetworkRuntime::new("config", enabled_config(), modem.clone());

    let degraded = runtime.start().clone();
    assert_eq!(degraded.state, NetworkLifecycleState::Degraded);
    runtime.drain_snapshot_events();

    let recovered = runtime.reset_modem().clone();

    assert_eq!(recovered.state, NetworkLifecycleState::Online);
    assert_eq!(recovered.reconnect_attempts, 1);
    assert!(!recovered.recovering);
    assert!(!recovered.retryable);
    assert_eq!(recovered.error_code, "");
    assert_eq!(
        runtime
            .drain_snapshot_events()
            .iter()
            .map(|snapshot| snapshot.state)
            .collect::<Vec<_>>(),
        vec![
            NetworkLifecycleState::Recovering,
            NetworkLifecycleState::Probing,
            NetworkLifecycleState::Ready,
            NetworkLifecycleState::Registering,
            NetworkLifecycleState::Registered,
            NetworkLifecycleState::PppStarting,
            NetworkLifecycleState::Online,
        ]
    );
    let state = modem.state();
    assert_eq!(state.reset_calls, 1);
    assert_eq!(state.open_calls, 2);
}

#[test]
fn tick_refreshes_live_modem_facts_and_emits_snapshot_when_they_change() {
    let modem = FakeModemController::new();
    modem.set_live_fact_results([Ok(roaming_modem())]);
    let mut runtime = NetworkRuntime::new_with_policy(
        "config",
        enabled_config(),
        modem.clone(),
        RecoveryPolicy::new(100, 400),
    );

    runtime.start_at(1_000);
    runtime.drain_snapshot_events();

    runtime.tick_at(6_000);
    let snapshots = runtime.drain_snapshot_events();
    let snapshot = snapshots.last().expect("live facts snapshot");

    assert_eq!(snapshot.state, NetworkLifecycleState::Online);
    assert_eq!(snapshot.carrier, "Vodafone");
    assert_eq!(snapshot.network_type, "3G");
    assert_eq!(snapshot.signal.csq, Some(9));
    assert_eq!(snapshot.signal.bars, 1);
    assert!(snapshot.registered);
    assert_eq!(modem.state().refresh_facts_calls, 1);
}

#[test]
fn tick_refreshes_registration_loss_without_restart() {
    let modem = FakeModemController::new();
    modem.set_live_fact_results([Ok(unregistered_modem())]);
    let mut runtime = NetworkRuntime::new_with_policy(
        "config",
        enabled_config(),
        modem,
        RecoveryPolicy::new(100, 400),
    );

    runtime.start_at(1_000);
    runtime.drain_snapshot_events();

    runtime.tick_at(6_000);
    let snapshots = runtime.drain_snapshot_events();
    let snapshot = snapshots.last().expect("registration loss snapshot");

    assert_eq!(snapshot.state, NetworkLifecycleState::Online);
    assert!(!snapshot.registered);
    assert_eq!(snapshot.carrier, "Vodafone");
    assert_eq!(snapshot.signal.csq, Some(9));
}

#[test]
fn health_command_surfaces_live_fact_refresh_failure_and_marks_runtime_retryable() {
    let modem = FakeModemController::new();
    modem.set_live_fact_results([Err(retryable_error(
        "signal_read_failed",
        "AT+CSQ timed out",
    ))]);
    let mut runtime = NetworkRuntime::new_with_policy(
        "config",
        enabled_config(),
        modem,
        RecoveryPolicy::new(100, 400),
    );

    runtime.start_at(1_000);
    runtime.drain_snapshot_events();

    let error = runtime
        .health_command()
        .expect_err("health command should report live fact refresh failure");

    assert_eq!(error.code, "signal_read_failed");
    assert_eq!(error.message, "AT+CSQ timed out");
    assert_eq!(runtime.snapshot().state, NetworkLifecycleState::Degraded);
    assert!(runtime.snapshot().retryable);
    assert_eq!(runtime.snapshot().error_code, "signal_read_failed");
    assert!(runtime.snapshot().next_retry_at_ms.is_some());
}

#[test]
fn autonomous_live_fact_refresh_failure_transitions_runtime_into_retryable_fault() {
    let modem = FakeModemController::new();
    modem.set_live_fact_results([Err(retryable_error(
        "signal_read_failed",
        "AT+CSQ timed out",
    ))]);
    let mut runtime = NetworkRuntime::new_with_policy(
        "config",
        enabled_config(),
        modem.clone(),
        RecoveryPolicy::new(100, 400),
    );

    runtime.start_at(1_000);
    runtime.drain_snapshot_events();

    runtime.tick_at(6_000);
    let snapshots = runtime.drain_snapshot_events();
    let snapshot = snapshots.last().expect("autonomous fact fault snapshot");

    assert_eq!(snapshot.state, NetworkLifecycleState::Degraded);
    assert_eq!(snapshot.error_code, "signal_read_failed");
    assert_eq!(snapshot.error_message, "AT+CSQ timed out");
    assert!(snapshot.retryable);
    assert_eq!(snapshot.next_retry_at_ms, Some(6_100));
    assert_eq!(modem.state().refresh_facts_calls, 1);
}

#[test]
fn repeated_health_calls_keep_returning_error_while_runtime_is_degraded() {
    let modem = FakeModemController::new();
    modem.set_ppp_results([Err(retryable_error(
        "ppp_start_failed",
        "PPP failed to start",
    ))]);
    let mut runtime = NetworkRuntime::new_with_policy(
        "config",
        enabled_config(),
        modem,
        RecoveryPolicy::new(100, 400),
    );

    runtime.start_at(1_000);
    runtime.drain_snapshot_events();

    let first = runtime
        .health_command()
        .expect_err("degraded runtime should fail health checks");
    let second = runtime
        .health_command()
        .expect_err("repeated health should keep failing until recovery");

    assert_eq!(first.code, "ppp_start_failed");
    assert_eq!(second.code, "ppp_start_failed");
    assert_eq!(runtime.snapshot().state, NetworkLifecycleState::Degraded);
    assert_eq!(runtime.snapshot().error_code, "ppp_start_failed");
}
