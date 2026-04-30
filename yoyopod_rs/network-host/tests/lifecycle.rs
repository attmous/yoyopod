mod support;

use yoyopod_network_host::runtime::NetworkRuntime;
use yoyopod_network_host::snapshot::NetworkLifecycleState;

use crate::support::{
    berlin_fix, blank_apn_config, enabled_config, fatal_error, ppp_link, registered_modem,
    retryable_error, FakeModemController,
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
fn start_degrades_snapshot_with_meaningful_error_when_probe_fails() {
    let modem = FakeModemController::new();
    modem.set_probe_results([Err(retryable_error("probe_failed", "AT ping timed out"))]);
    let mut runtime = NetworkRuntime::new("config", enabled_config(), modem);

    let snapshot = runtime.start().clone();

    assert_eq!(snapshot.state, NetworkLifecycleState::Degraded);
    assert_eq!(snapshot.error_code, "probe_failed");
    assert_eq!(snapshot.error_message, "AT ping timed out");
    assert!(snapshot.retryable);
    assert!(!snapshot.ppp.up);
}

#[test]
fn health_reconciles_stale_online_state_when_ppp_disappears() {
    let modem = FakeModemController::new();
    modem.set_ppp_health_results([yoyopod_network_host::modem::PppHealth::InterfaceDown]);
    let mut runtime = NetworkRuntime::new("config", enabled_config(), modem);
    runtime.start();

    let snapshot = runtime.health().clone();

    assert_eq!(snapshot.state, NetworkLifecycleState::Registered);
    assert!(!snapshot.ppp.up);
    assert_eq!(snapshot.error_code, "ppp_interface_down");
    assert_eq!(snapshot.error_message, "PPP interface down");
    assert!(snapshot.retryable);
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

    let recovered = runtime.reset_modem().clone();

    assert_eq!(recovered.state, NetworkLifecycleState::Online);
    assert_eq!(recovered.reconnect_attempts, 1);
    assert!(!recovered.recovering);
    assert!(!recovered.retryable);
    assert_eq!(recovered.error_code, "");
    let state = modem.state();
    assert_eq!(state.reset_calls, 1);
    assert_eq!(state.open_calls, 2);
}
