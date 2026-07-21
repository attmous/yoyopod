use std::io::{self, BufRead, Read, Write};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::time::Duration;

use anyhow::Result;

use crate::config::NetworkHostConfig;
use crate::modem::{ModemController, Sim7600ModemController};
use crate::protocol::{
    health_result, ready_event, snapshot_event, snapshot_result, stopped_event, stopped_result,
    wifi_state_event, wifi_state_result, EnvelopeKind, WorkerEnvelope,
};
use crate::runtime::{NetworkRuntime, RuntimeCommandError};
use crate::wifi::{
    NetworkManagerWifiController, UnavailableWifiController, WifiAddProfileRequest, WifiController,
    WifiOperationError, WifiUpdateProfileRequest,
};

const DEFAULT_POLL_INTERVAL: Duration = Duration::from_millis(100);

pub fn run(config_dir: &str) -> Result<()> {
    let mut stdout = io::stdout().lock();
    let wifi: Box<dyn WifiController> = NetworkManagerWifiController::connect()
        .map(|controller| Box::new(controller) as Box<dyn WifiController>)
        .unwrap_or_else(|_| Box::new(UnavailableWifiController));
    match NetworkHostConfig::load(config_dir) {
        Ok(config) => run_with_runtime_loop(
            NetworkRuntime::new(
                config_dir,
                config.clone(),
                Sim7600ModemController::new(config),
            ),
            stdin_channel(),
            &mut stdout,
            DEFAULT_POLL_INTERVAL,
            wifi,
        ),
        Err(error) => run_with_runtime_loop(
            NetworkRuntime::degraded_config(config_dir, error.to_string()),
            stdin_channel(),
            &mut stdout,
            DEFAULT_POLL_INTERVAL,
            wifi,
        ),
    }
}

pub fn run_with_io<R, W>(config_dir: &str, input: R, output: &mut W) -> Result<()>
where
    R: Read + Send + 'static,
    W: Write,
{
    match NetworkHostConfig::load(config_dir) {
        Ok(config) => run_with_runtime_io(
            NetworkRuntime::new(
                config_dir,
                config.clone(),
                Sim7600ModemController::new(config),
            ),
            input,
            output,
        ),
        Err(error) => run_with_runtime_io(
            NetworkRuntime::degraded_config(config_dir, error.to_string()),
            input,
            output,
        ),
    }
}

pub fn run_with_runtime_io<C, R, W>(
    runtime: NetworkRuntime<C>,
    input: R,
    output: &mut W,
) -> Result<()>
where
    C: ModemController,
    R: Read + Send + 'static,
    W: Write,
{
    run_with_runtime_io_and_poll_interval(runtime, input, output, DEFAULT_POLL_INTERVAL)
}

pub fn run_with_runtime_io_and_poll_interval<C, R, W>(
    runtime: NetworkRuntime<C>,
    input: R,
    output: &mut W,
    poll_interval: Duration,
) -> Result<()>
where
    C: ModemController,
    R: Read + Send + 'static,
    W: Write,
{
    run_with_runtime_loop(
        runtime,
        reader_channel(input),
        output,
        poll_interval,
        Box::new(UnavailableWifiController),
    )
}

pub fn run_with_runtime_io_and_wifi<C, R, W>(
    runtime: NetworkRuntime<C>,
    input: R,
    output: &mut W,
    poll_interval: Duration,
    wifi: Box<dyn WifiController>,
) -> Result<()>
where
    C: ModemController,
    R: Read + Send + 'static,
    W: Write,
{
    run_with_runtime_loop(runtime, reader_channel(input), output, poll_interval, wifi)
}

fn run_with_runtime_loop<C, W>(
    mut runtime: NetworkRuntime<C>,
    input_rx: mpsc::Receiver<io::Result<String>>,
    output: &mut W,
    poll_interval: Duration,
    mut wifi: Box<dyn WifiController>,
) -> Result<()>
where
    C: ModemController,
    W: Write,
{
    write_envelope(output, &ready_event(&runtime.snapshot().config_dir))?;
    write_envelope(output, &snapshot_event(runtime.snapshot()))?;
    emit_wifi_state(
        output,
        wifi.refresh()
            .unwrap_or_else(|_| crate::wifi::WifiState::unavailable()),
    )?;
    if should_boot_runtime(runtime.snapshot()) {
        runtime.start();
    }
    emit_startup_snapshots(output, &mut runtime)?;

    loop {
        match input_rx.recv_timeout(poll_interval) {
            Ok(Ok(line)) => {
                if line.trim().is_empty() {
                    emit_pending_snapshots(output, &mut runtime)?;
                    continue;
                }
                let envelope = match WorkerEnvelope::decode(line.as_bytes()) {
                    Ok(envelope) => envelope,
                    Err(error) => {
                        write_envelope(
                            output,
                            &WorkerEnvelope::error(
                                "network.error",
                                None,
                                "protocol_error",
                                error.to_string(),
                            ),
                        )?;
                        continue;
                    }
                };
                if envelope.kind != EnvelopeKind::Command {
                    continue;
                }

                match handle_command(&mut runtime, wifi.as_mut(), envelope, output)? {
                    LoopControl::Continue => {}
                    LoopControl::Shutdown => break,
                }
            }
            Ok(Err(error)) => {
                write_envelope(
                    output,
                    &WorkerEnvelope::error(
                        "network.error",
                        None,
                        "input_read_failed",
                        error.to_string(),
                    ),
                )?;
                shutdown_for_implicit_exit(output, &mut runtime, "input_error")?;
                return Err(error.into());
            }
            Err(RecvTimeoutError::Timeout) => {
                runtime.tick();
                emit_pending_snapshots(output, &mut runtime)?;
            }
            Err(RecvTimeoutError::Disconnected) => {
                shutdown_for_implicit_exit(output, &mut runtime, "input_closed")?;
                break;
            }
        }
    }

    Ok(())
}

enum LoopControl {
    Continue,
    Shutdown,
}

fn handle_command<C, W>(
    runtime: &mut NetworkRuntime<C>,
    wifi: &mut dyn WifiController,
    envelope: WorkerEnvelope,
    output: &mut W,
) -> Result<LoopControl>
where
    C: ModemController,
    W: Write,
{
    match envelope.message_type.as_str() {
        "network.health" => {
            match runtime.health_command() {
                Ok(snapshot) => {
                    write_envelope(output, &health_result(envelope.request_id, snapshot))?;
                }
                Err(error) => emit_command_error(output, envelope.request_id, error)?,
            }
            emit_pending_snapshots(output, runtime)?;
        }
        "network.query_gps" => {
            match runtime.query_gps_command() {
                Ok(snapshot) => {
                    write_envelope(output, &snapshot_result(envelope.request_id, snapshot))?;
                }
                Err(error) => emit_command_error(output, envelope.request_id, error)?,
            }
            emit_pending_snapshots(output, runtime)?;
        }
        "network.reset_modem" => {
            match runtime.reset_modem_command() {
                Ok(snapshot) => {
                    write_envelope(output, &snapshot_result(envelope.request_id, snapshot))?;
                }
                Err(error) => emit_command_error(output, envelope.request_id, error)?,
            }
            emit_pending_snapshots(output, runtime)?;
        }
        "wifi_refresh" => {
            let result = wifi.refresh();
            handle_wifi_operation(output, envelope.request_id, result, wifi)?;
        }
        "wifi_scan" => {
            let result = wifi.scan();
            handle_wifi_operation(output, envelope.request_id, result, wifi)?;
        }
        "wifi_add_profile" => {
            let request = serde_json::from_value::<WifiAddProfileRequest>(envelope.payload)
                .map_err(|_| {
                    WifiOperationError::new(
                        "wifi_invalid_request",
                        "The Wi-Fi profile details are invalid",
                    )
                });
            let result = request.and_then(|request| wifi.add_profile(request));
            handle_wifi_operation(output, envelope.request_id, result, wifi)?;
        }
        "wifi_update_profile" => {
            let request = serde_json::from_value::<WifiUpdateProfileRequest>(envelope.payload)
                .map_err(|_| {
                    WifiOperationError::new(
                        "wifi_invalid_request",
                        "The Wi-Fi profile details are invalid",
                    )
                });
            let result = request.and_then(|request| wifi.update_profile(request));
            handle_wifi_operation(output, envelope.request_id, result, wifi)?;
        }
        "wifi_forget_profile" => {
            let profile_id = envelope
                .payload
                .get("profile_id")
                .and_then(serde_json::Value::as_str)
                .filter(|profile_id| !profile_id.trim().is_empty())
                .map(str::to_owned)
                .ok_or_else(|| {
                    WifiOperationError::new(
                        "wifi_invalid_request",
                        "The saved Wi-Fi network reference is invalid",
                    )
                });
            let result = profile_id.and_then(|profile_id| wifi.forget_profile(&profile_id));
            handle_wifi_operation(output, envelope.request_id, result, wifi)?;
        }
        "network.shutdown" | "worker.stop" => {
            runtime.shutdown();
            write_envelope(output, &stopped_result(envelope.request_id, "shutdown"))?;
            emit_pending_snapshots(output, runtime)?;
            write_envelope(output, &stopped_event("shutdown"))?;
            return Ok(LoopControl::Shutdown);
        }
        _ => {
            write_envelope(
                output,
                &WorkerEnvelope::error(
                    "network.error",
                    envelope.request_id,
                    "unsupported_command",
                    format!("unsupported command {}", envelope.message_type),
                ),
            )?;
        }
    }

    Ok(LoopControl::Continue)
}

fn handle_wifi_operation(
    output: &mut dyn Write,
    request_id: Option<String>,
    result: Result<crate::wifi::WifiState, WifiOperationError>,
    wifi: &mut dyn WifiController,
) -> Result<()> {
    match result {
        Ok(state) => {
            write_envelope(output, &wifi_state_result(request_id, &state))?;
            emit_wifi_state(output, state)
        }
        Err(error) => {
            write_envelope(
                output,
                &WorkerEnvelope::error("wifi_error", request_id, error.code, error.message),
            )?;
            emit_wifi_state(
                output,
                wifi.refresh()
                    .unwrap_or_else(|_| crate::wifi::WifiState::unavailable()),
            )
        }
    }
}

fn emit_wifi_state(output: &mut dyn Write, state: crate::wifi::WifiState) -> Result<()> {
    write_envelope(output, &wifi_state_event(&state))
}

fn emit_command_error(
    output: &mut dyn Write,
    request_id: Option<String>,
    error: RuntimeCommandError,
) -> Result<()> {
    write_envelope(
        output,
        &WorkerEnvelope::error("network.error", request_id, error.code, error.message),
    )
}

fn emit_startup_snapshots<C, W>(output: &mut W, runtime: &mut NetworkRuntime<C>) -> Result<()>
where
    C: ModemController,
    W: Write,
{
    let snapshots = runtime.drain_snapshot_events();
    if snapshots.is_empty() {
        write_envelope(output, &snapshot_event(runtime.snapshot()))?;
        return Ok(());
    }

    for snapshot in snapshots {
        write_envelope(output, &snapshot_event(&snapshot))?;
    }
    Ok(())
}

fn emit_pending_snapshots<C, W>(output: &mut W, runtime: &mut NetworkRuntime<C>) -> Result<()>
where
    C: ModemController,
    W: Write,
{
    for snapshot in runtime.drain_snapshot_events() {
        write_envelope(output, &snapshot_event(&snapshot))?;
    }
    Ok(())
}

fn shutdown_for_implicit_exit<C, W>(
    output: &mut W,
    runtime: &mut NetworkRuntime<C>,
    reason: &str,
) -> Result<()>
where
    C: ModemController,
    W: Write,
{
    runtime.shutdown();
    emit_pending_snapshots(output, runtime)?;
    write_envelope(output, &stopped_event(reason))
}

fn write_envelope(output: &mut dyn Write, envelope: &WorkerEnvelope) -> Result<()> {
    writeln!(output, "{}", serde_json::to_string(envelope)?)?;
    output.flush()?;
    Ok(())
}

fn should_boot_runtime(snapshot: &crate::snapshot::NetworkRuntimeSnapshot) -> bool {
    !(snapshot.state == crate::snapshot::NetworkLifecycleState::Degraded
        && snapshot.error_code == "config_load_failed")
}

fn stdin_channel() -> mpsc::Receiver<io::Result<String>> {
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let stdin = io::stdin();
        for line in stdin.lock().lines() {
            if tx.send(line).is_err() {
                break;
            }
        }
    });
    rx
}

fn reader_channel<R>(input: R) -> mpsc::Receiver<io::Result<String>>
where
    R: Read + Send + 'static,
{
    let (tx, rx) = mpsc::channel();
    std::thread::spawn(move || {
        let reader = io::BufReader::new(input);
        for line in reader.lines() {
            if tx.send(line).is_err() {
                break;
            }
        }
    });
    rx
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::wifi::{
        WifiActiveNetwork, WifiNearbyNetwork, WifiSavedProfile, WifiSecurity, WifiState,
        WifiStateStatus,
    };
    use std::io::Cursor;

    struct FakeWifiController {
        state: WifiState,
        fail_scan: bool,
    }

    impl WifiController for FakeWifiController {
        fn refresh(&mut self) -> Result<WifiState, WifiOperationError> {
            Ok(self.state.clone())
        }

        fn scan(&mut self) -> Result<WifiState, WifiOperationError> {
            if self.fail_scan {
                Err(WifiOperationError::new(
                    "wifi_scan_failed",
                    "Nearby Wi-Fi networks could not be scanned",
                ))
            } else {
                Ok(self.state.clone())
            }
        }

        fn add_profile(
            &mut self,
            _request: WifiAddProfileRequest,
        ) -> Result<WifiState, WifiOperationError> {
            Ok(self.state.clone())
        }

        fn update_profile(
            &mut self,
            _request: WifiUpdateProfileRequest,
        ) -> Result<WifiState, WifiOperationError> {
            Ok(self.state.clone())
        }

        fn forget_profile(&mut self, _profile_id: &str) -> Result<WifiState, WifiOperationError> {
            Ok(self.state.clone())
        }
    }

    fn fake_state() -> WifiState {
        WifiState {
            schema_version: 1,
            status: WifiStateStatus::Ready,
            radio_enabled: true,
            active_network: Some(WifiActiveNetwork {
                profile_id: "11111111-1111-4111-8111-111111111111".to_string(),
                ssid: "Family WiFi".to_string(),
                security: WifiSecurity::Wpa2Personal,
                signal_percent: 82,
            }),
            saved_profiles: vec![WifiSavedProfile {
                profile_id: "11111111-1111-4111-8111-111111111111".to_string(),
                ssid: "Family WiFi".to_string(),
                security: WifiSecurity::Wpa2Personal,
                hidden: false,
                active: true,
                autoconnect: true,
            }],
            nearby_networks: vec![WifiNearbyNetwork {
                ssid: "Guest".to_string(),
                security: WifiSecurity::Open,
                signal_percent: 55,
                saved: false,
                active: false,
            }],
            scanned_at: Some(1_700_000_000),
            reported_at: 1_700_000_001,
        }
    }

    fn run_wifi_command(command: WorkerEnvelope, fail_scan: bool) -> Vec<WorkerEnvelope> {
        let input = Cursor::new(command.encode().expect("command should encode"));
        let mut output = Vec::new();
        run_with_runtime_io_and_wifi(
            NetworkRuntime::degraded_config("config", "test configuration"),
            input,
            &mut output,
            Duration::from_millis(1),
            Box::new(FakeWifiController {
                state: fake_state(),
                fail_scan,
            }),
        )
        .expect("worker run should succeed");
        String::from_utf8(output)
            .expect("worker output should be UTF-8")
            .lines()
            .map(|line| WorkerEnvelope::decode(line.as_bytes()).expect("valid worker envelope"))
            .collect()
    }

    #[test]
    fn profile_password_is_not_echoed_in_results_or_state_events() {
        let envelopes = run_wifi_command(
            WorkerEnvelope::command(
                "wifi_add_profile",
                Some("request-1".to_string()),
                serde_json::json!({
                    "ssid": "Family WiFi",
                    "security": "wpa2_personal",
                    "password": "never-publish-this",
                    "hidden": false
                }),
            ),
            false,
        );

        assert!(envelopes.iter().any(|envelope| {
            envelope.kind == EnvelopeKind::Result
                && envelope.request_id.as_deref() == Some("request-1")
                && envelope.message_type == "wifi_state"
        }));
        let encoded = serde_json::to_string(&envelopes).expect("output should serialize");
        assert!(!encoded.contains("never-publish-this"));
        assert!(!encoded.contains("password"));
    }

    #[test]
    fn failed_operation_emits_error_and_a_fresh_sanitized_state() {
        let envelopes = run_wifi_command(
            WorkerEnvelope::command(
                "wifi_scan",
                Some("request-2".to_string()),
                serde_json::json!({}),
            ),
            true,
        );

        let error_index = envelopes
            .iter()
            .position(|envelope| {
                envelope.kind == EnvelopeKind::Error
                    && envelope.request_id.as_deref() == Some("request-2")
            })
            .expect("failed scan should return an error");
        assert!(envelopes.iter().skip(error_index + 1).any(|envelope| {
            envelope.kind == EnvelopeKind::Event && envelope.message_type == "wifi_state"
        }));
    }
}
