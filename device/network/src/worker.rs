use std::io::{self, BufRead, Read, Write};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use anyhow::Result;

use crate::config::NetworkHostConfig;
use crate::modem::{ModemController, Sim7600ModemController};
use crate::protocol::{
    health_result, ready_event, snapshot_event, snapshot_result, stopped_event, stopped_result,
    wifi_change_candidate_event, wifi_provisioning_state_event, wifi_state_event,
    wifi_state_result, EnvelopeKind, WorkerEnvelope,
};
use crate::provisioning::{WifiProvisioner, WifiProvisioningState};
use crate::runtime::{NetworkRuntime, RuntimeCommandError};
use crate::wifi::{
    NetworkManagerWifiController, UnavailableWifiController, WifiActivateProfileRequest,
    WifiAddProfileRequest, WifiChangeOperation, WifiChangeStart, WifiController,
    WifiOperationError, WifiUpdateIpv4Request, WifiUpdateProfileRequest,
};

const DEFAULT_POLL_INTERVAL: Duration = Duration::from_millis(100);
// NetworkManager starts the 90-second checkpoint before the local activation
// wait. Keep the cloud-confirmation phase below the remaining checkpoint time.
const WIFI_CHANGE_TIMEOUT: Duration = Duration::from_secs(60);
const WIFI_CANDIDATE_INTERVAL: Duration = Duration::from_secs(5);

#[derive(Debug)]
struct PendingWifiChange {
    request_id: String,
    profile_id: String,
    operation: WifiChangeOperation,
    deadline: Instant,
    next_candidate_at: Instant,
    candidate_attempt: u8,
}

pub fn run(config_dir: &str) -> Result<()> {
    let mut stdout = io::stdout().lock();
    // A previous run that died ungracefully (crash / SIGKILL / power loss) while
    // the setup hotspot was up can leave the "YoYoPod Setup" AP profile behind in
    // NetworkManager, keeping the device broadcasting and holding the radio. Clear
    // any such stale profile on startup, before the runtime loop begins.
    crate::provisioning::cleanup_stale_setup_ap();
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
    let mut pending_wifi_change = None;
    let mut provisioning: Option<WifiProvisioner> = None;
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

                match handle_command(
                    &mut runtime,
                    wifi.as_mut(),
                    &mut pending_wifi_change,
                    &mut provisioning,
                    envelope,
                    output,
                )? {
                    LoopControl::Continue => {}
                    LoopControl::Shutdown => break,
                }
                service_pending_wifi_change(output, wifi.as_mut(), &mut pending_wifi_change)?;
                service_provisioning(output, &mut provisioning)?;
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
                service_pending_wifi_change(output, wifi.as_mut(), &mut pending_wifi_change)?;
                service_provisioning(output, &mut provisioning)?;
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
    pending_wifi_change: &mut Option<PendingWifiChange>,
    provisioning: &mut Option<WifiProvisioner>,
    envelope: WorkerEnvelope,
    output: &mut W,
) -> Result<LoopControl>
where
    C: ModemController,
    W: Write,
{
    // While the hotspot/onboarding flow owns the radio, station-mode Wi-Fi
    // commands would fight it; reject them until it stops.
    if provisioning.is_some()
        && envelope.message_type.starts_with("wifi_")
        && !matches!(
            envelope.message_type.as_str(),
            "wifi_provisioning_start" | "wifi_provisioning_stop"
        )
    {
        write_envelope(
            output,
            &WorkerEnvelope::error(
                "wifi_error",
                envelope.request_id,
                "wifi_provisioning_in_progress",
                "Wi-Fi setup is in progress on the device",
            ),
        )?;
        return Ok(LoopControl::Continue);
    }

    if pending_wifi_change.is_some()
        && !matches!(
            envelope.message_type.as_str(),
            "wifi_refresh" | "wifi_confirm_change" | "network.shutdown" | "worker.stop"
        )
    {
        write_envelope(
            output,
            &WorkerEnvelope::error(
                "wifi_error",
                envelope.request_id,
                "wifi_change_in_progress",
                "Another Wi-Fi connectivity change is already in progress",
            ),
        )?;
        // The runtime already applied WifiSetupStart locally (screen shows
        // "Starting...") and ignores the uncorrelated wifi_error above, so a
        // refused start would hang the screen. Clear it with an error state.
        if envelope.message_type == "wifi_provisioning_start" {
            emit_provisioning_state(
                output,
                &WifiProvisioningState::error("Wi-Fi is busy - try again in a moment."),
            )?;
        }
        return Ok(LoopControl::Continue);
    }

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
        "wifi_activate_profile" => {
            let Some(request_id) = envelope.request_id.clone() else {
                write_envelope(
                    output,
                    &WorkerEnvelope::error(
                        "wifi_error",
                        None,
                        "wifi_invalid_request",
                        "The Wi-Fi activation request is missing its correlation reference",
                    ),
                )?;
                emit_wifi_state(
                    output,
                    wifi.refresh()
                        .unwrap_or_else(|_| crate::wifi::WifiState::unavailable()),
                )?;
                return Ok(LoopControl::Continue);
            };
            let request = serde_json::from_value::<WifiActivateProfileRequest>(envelope.payload)
                .map_err(|_| {
                    WifiOperationError::new(
                        "wifi_invalid_request",
                        "The saved Wi-Fi activation request is invalid",
                    )
                });
            let result = request.and_then(|request| wifi.begin_activate_profile(request));
            handle_wifi_change_start(output, request_id, result, pending_wifi_change, wifi)?;
        }
        "wifi_update_ipv4" => {
            let Some(request_id) = envelope.request_id.clone() else {
                write_envelope(
                    output,
                    &WorkerEnvelope::error(
                        "wifi_error",
                        None,
                        "wifi_invalid_request",
                        "The IPv4 update request is missing its correlation reference",
                    ),
                )?;
                emit_wifi_state(
                    output,
                    wifi.refresh()
                        .unwrap_or_else(|_| crate::wifi::WifiState::unavailable()),
                )?;
                return Ok(LoopControl::Continue);
            };
            let request = serde_json::from_value::<WifiUpdateIpv4Request>(envelope.payload)
                .map_err(|_| {
                    WifiOperationError::new("wifi_invalid_request", "The IPv4 settings are invalid")
                });
            let result = request.and_then(|request| wifi.begin_update_ipv4(request));
            handle_wifi_change_start(output, request_id, result, pending_wifi_change, wifi)?;
        }
        "wifi_confirm_change" => {
            let activation_command_id = envelope
                .payload
                .get("activation_command_id")
                .and_then(serde_json::Value::as_str)
                .map(str::to_owned);
            let matches_pending = activation_command_id.as_deref()
                == pending_wifi_change
                    .as_ref()
                    .map(|pending| pending.request_id.as_str());
            if !matches_pending {
                write_envelope(
                    output,
                    &WorkerEnvelope::error(
                        "wifi_error",
                        envelope.request_id,
                        "wifi_confirmation_mismatch",
                        "The Wi-Fi confirmation did not match the pending change",
                    ),
                )?;
            } else if let Some(pending) = pending_wifi_change.take() {
                let result = wifi.confirm_pending_change();
                handle_wifi_operation(output, Some(pending.request_id), result, wifi)?;
            }
        }
        "wifi_provisioning_start" => {
            if provisioning.is_none() {
                let (worker, initial) = WifiProvisioner::start();
                *provisioning = Some(worker);
                emit_provisioning_state(output, &initial)?;
            }
        }
        "wifi_provisioning_stop" => {
            if let Some(worker) = provisioning.take() {
                let final_state = worker.stop();
                emit_provisioning_state(output, &final_state)?;
            } else {
                emit_provisioning_state(output, &WifiProvisioningState::idle())?;
            }
        }
        "network.shutdown" | "worker.stop" => {
            if let Some(worker) = provisioning.take() {
                let _ = worker.stop();
            }
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

fn handle_wifi_change_start(
    output: &mut dyn Write,
    request_id: String,
    result: Result<WifiChangeStart, WifiOperationError>,
    pending_wifi_change: &mut Option<PendingWifiChange>,
    wifi: &mut dyn WifiController,
) -> Result<()> {
    match result {
        Ok(WifiChangeStart::Immediate(state)) => {
            write_envelope(output, &wifi_state_result(Some(request_id), &state))?;
            emit_wifi_state(output, state)
        }
        Ok(WifiChangeStart::Pending {
            profile_id,
            operation,
        }) => {
            let now = Instant::now();
            *pending_wifi_change = Some(PendingWifiChange {
                request_id,
                profile_id,
                operation,
                deadline: now + WIFI_CHANGE_TIMEOUT,
                next_candidate_at: now,
                candidate_attempt: 0,
            });
            service_pending_wifi_change(output, wifi, pending_wifi_change)
        }
        Err(error) => {
            write_envelope(
                output,
                &WorkerEnvelope::error("wifi_error", Some(request_id), error.code, error.message),
            )?;
            emit_wifi_state(
                output,
                wifi.refresh()
                    .unwrap_or_else(|_| crate::wifi::WifiState::unavailable()),
            )
        }
    }
}

fn service_pending_wifi_change(
    output: &mut dyn Write,
    wifi: &mut dyn WifiController,
    pending_wifi_change: &mut Option<PendingWifiChange>,
) -> Result<()> {
    let now = Instant::now();
    let Some(pending) = pending_wifi_change.as_mut() else {
        return Ok(());
    };
    if now >= pending.deadline {
        let pending = pending_wifi_change
            .take()
            .expect("pending change should exist");
        let state = wifi
            .rollback_pending_change()
            .unwrap_or_else(|_| crate::wifi::WifiState::unavailable());
        write_envelope(
            output,
            &WorkerEnvelope::error(
                "wifi_error",
                Some(pending.request_id),
                "wifi_change_confirmation_timeout",
                "The previous Wi-Fi connection was restored because cloud confirmation timed out",
            ),
        )?;
        return emit_wifi_state(output, state);
    }
    if now < pending.next_candidate_at {
        return Ok(());
    }
    pending.candidate_attempt = pending.candidate_attempt.saturating_add(1);
    write_envelope(
        output,
        &wifi_change_candidate_event(
            &pending.request_id,
            &pending.profile_id,
            pending.operation,
            pending.candidate_attempt,
            epoch_seconds(),
        ),
    )?;
    pending.next_candidate_at = now + WIFI_CANDIDATE_INTERVAL;
    Ok(())
}

fn epoch_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default()
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

fn emit_provisioning_state(output: &mut dyn Write, state: &WifiProvisioningState) -> Result<()> {
    write_envelope(output, &wifi_provisioning_state_event(state))
}

/// Forward any onboarding status updates to the runtime and, once the flow's
/// background thread has finished on its own, reap it (its terminal state was
/// already emitted via `drain`).
fn service_provisioning(
    output: &mut dyn Write,
    provisioning: &mut Option<WifiProvisioner>,
) -> Result<()> {
    let mut finished = false;
    if let Some(worker) = provisioning.as_mut() {
        for state in worker.drain() {
            emit_provisioning_state(output, &state)?;
        }
        finished = worker.finished();
    }
    if finished {
        if let Some(mut worker) = provisioning.take() {
            // Drain once more before dropping the receiver: the thread may have
            // sent its terminal connected/error/idle update in the window between
            // the drain above and observing `finished`.
            for state in worker.drain() {
                emit_provisioning_state(output, &state)?;
            }
            worker.join();
        }
    }
    Ok(())
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
        WifiActivationPreference, WifiActiveNetwork, WifiNearbyNetwork, WifiSavedProfile,
        WifiSecurity, WifiState, WifiStateStatus,
    };
    use std::io::Cursor;

    struct FakeWifiController {
        state: WifiState,
        fail_scan: bool,
        pending_change: bool,
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

        fn begin_activate_profile(
            &mut self,
            request: WifiActivateProfileRequest,
        ) -> Result<WifiChangeStart, WifiOperationError> {
            self.pending_change = true;
            Ok(WifiChangeStart::Pending {
                profile_id: request.profile_id,
                operation: WifiChangeOperation::ActivateProfile,
            })
        }

        fn begin_update_ipv4(
            &mut self,
            request: WifiUpdateIpv4Request,
        ) -> Result<WifiChangeStart, WifiOperationError> {
            if self
                .state
                .active_network
                .as_ref()
                .is_some_and(|active| active.profile_id == request.profile_id)
            {
                self.pending_change = true;
                Ok(WifiChangeStart::Pending {
                    profile_id: request.profile_id,
                    operation: WifiChangeOperation::UpdateIpv4,
                })
            } else {
                Ok(WifiChangeStart::Immediate(self.state.clone()))
            }
        }

        fn confirm_pending_change(&mut self) -> Result<WifiState, WifiOperationError> {
            self.pending_change = false;
            Ok(self.state.clone())
        }

        fn rollback_pending_change(&mut self) -> Result<WifiState, WifiOperationError> {
            self.pending_change = false;
            Ok(self.state.clone())
        }
    }

    fn fake_state() -> WifiState {
        WifiState {
            schema_version: 2,
            status: WifiStateStatus::Ready,
            radio_enabled: true,
            active_network: Some(WifiActiveNetwork {
                profile_id: "11111111-1111-4111-8111-111111111111".to_string(),
                ssid: "Family WiFi".to_string(),
                security: WifiSecurity::Wpa2Personal,
                signal_percent: 82,
                ipv4: Some(crate::wifi::WifiIpv4Config {
                    mode: crate::wifi::WifiIpv4Mode::Dhcp,
                    address: Some("192.168.1.42".to_string()),
                    prefix_length: Some(24),
                    gateway: Some("192.168.1.1".to_string()),
                    dns_servers: vec!["192.168.1.1".to_string()],
                }),
            }),
            saved_profiles: vec![WifiSavedProfile {
                profile_id: "11111111-1111-4111-8111-111111111111".to_string(),
                ssid: "Family WiFi".to_string(),
                security: WifiSecurity::Wpa2Personal,
                hidden: false,
                active: true,
                autoconnect: true,
                ipv4_config: crate::wifi::WifiIpv4Config::dhcp(),
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
        run_wifi_commands(vec![command], fail_scan)
    }

    fn run_wifi_commands(commands: Vec<WorkerEnvelope>, fail_scan: bool) -> Vec<WorkerEnvelope> {
        let mut input_bytes = Vec::new();
        for command in commands {
            input_bytes.extend(command.encode().expect("command should encode"));
        }
        let input = Cursor::new(input_bytes);
        let mut output = Vec::new();
        run_with_runtime_io_and_wifi(
            NetworkRuntime::degraded_config("config", "test configuration"),
            input,
            &mut output,
            Duration::from_millis(1),
            Box::new(FakeWifiController {
                state: fake_state(),
                fail_scan,
                pending_change: false,
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

    #[test]
    fn activation_waits_for_cloud_confirmation_before_returning_result() {
        let envelopes = run_wifi_command(
            WorkerEnvelope::command(
                "wifi_activate_profile",
                Some("77777777-7777-4777-8777-777777777777".to_string()),
                serde_json::json!({
                    "profile_id": "22222222-2222-4222-8222-222222222222",
                    "preference": WifiActivationPreference::SessionOnly,
                }),
            ),
            false,
        );

        assert!(envelopes.iter().any(|envelope| {
            envelope.kind == EnvelopeKind::Event
                && envelope.message_type == "wifi_change_candidate"
                && envelope.payload["command_id"] == "77777777-7777-4777-8777-777777777777"
        }));
        assert!(!envelopes.iter().any(|envelope| {
            envelope.kind == EnvelopeKind::Result
                && envelope.request_id.as_deref() == Some("77777777-7777-4777-8777-777777777777")
        }));
    }

    #[test]
    fn matching_cloud_confirmation_completes_original_activation_request() {
        let activation_id = "77777777-7777-4777-8777-777777777777";
        let envelopes = run_wifi_commands(
            vec![
                WorkerEnvelope::command(
                    "wifi_activate_profile",
                    Some(activation_id.to_string()),
                    serde_json::json!({
                        "profile_id": "22222222-2222-4222-8222-222222222222",
                        "preference": "preferred",
                    }),
                ),
                WorkerEnvelope::command(
                    "wifi_confirm_change",
                    None,
                    serde_json::json!({"activation_command_id": activation_id}),
                ),
            ],
            false,
        );

        assert!(envelopes.iter().any(|envelope| {
            envelope.kind == EnvelopeKind::Result
                && envelope.message_type == "wifi_state"
                && envelope.request_id.as_deref() == Some(activation_id)
        }));
    }

    #[test]
    fn connectivity_confirmation_timeout_rolls_back_and_nacks_the_original_request() {
        let activation_id = "77777777-7777-4777-8777-777777777777";
        let mut pending = Some(PendingWifiChange {
            request_id: activation_id.to_string(),
            profile_id: "22222222-2222-4222-8222-222222222222".to_string(),
            operation: WifiChangeOperation::ActivateProfile,
            deadline: Instant::now() - Duration::from_millis(1),
            next_candidate_at: Instant::now(),
            candidate_attempt: 1,
        });
        let mut wifi = FakeWifiController {
            state: fake_state(),
            fail_scan: false,
            pending_change: true,
        };
        let mut output = Vec::new();

        service_pending_wifi_change(&mut output, &mut wifi, &mut pending)
            .expect("timeout handling should succeed");
        let envelopes: Vec<WorkerEnvelope> = String::from_utf8(output)
            .expect("worker output should be UTF-8")
            .lines()
            .map(|line| WorkerEnvelope::decode(line.as_bytes()).expect("valid worker envelope"))
            .collect();

        assert!(pending.is_none());
        assert!(!wifi.pending_change);
        assert!(envelopes.iter().any(|envelope| {
            envelope.kind == EnvelopeKind::Error
                && envelope.request_id.as_deref() == Some(activation_id)
                && envelope.payload["code"] == "wifi_change_confirmation_timeout"
        }));
        assert!(envelopes.iter().any(|envelope| {
            envelope.kind == EnvelopeKind::Event && envelope.message_type == "wifi_state"
        }));
    }

    #[test]
    fn missing_connectivity_correlation_is_rejected_without_stopping_the_worker() {
        let envelopes = run_wifi_commands(
            vec![
                WorkerEnvelope::command(
                    "wifi_activate_profile",
                    None,
                    serde_json::json!({
                        "profile_id": "22222222-2222-4222-8222-222222222222",
                        "preference": "preferred",
                    }),
                ),
                WorkerEnvelope::command(
                    "wifi_scan",
                    Some("request-after-invalid".to_string()),
                    serde_json::json!({}),
                ),
            ],
            false,
        );

        assert!(envelopes.iter().any(|envelope| {
            envelope.kind == EnvelopeKind::Error
                && envelope.payload["code"] == "wifi_invalid_request"
        }));
        assert!(envelopes.iter().any(|envelope| {
            envelope.kind == EnvelopeKind::Result
                && envelope.request_id.as_deref() == Some("request-after-invalid")
        }));
    }
}
