use std::collections::HashMap;
use std::io::{self, BufRead, Read, Write};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use anyhow::Result;

use crate::audio::{AppliedAudio, AudioManager, AudioSettings};
use crate::bluetooth::{
    BluetoothController, BluetoothOperationError, BluetoothState, RecoveringBluetoothController,
    UnavailableBluetoothController,
};
use crate::config::NetworkHostConfig;
use crate::modem::{ModemController, Sim7600ModemController};
use crate::protocol::{
    audio_route_local_event, audio_state_event, audio_state_result, bluetooth_state_event,
    bluetooth_state_result, health_result, ready_event, snapshot_event, snapshot_result,
    stopped_event, stopped_result, wifi_change_candidate_event, wifi_provisioning_state_event,
    wifi_state_event, wifi_state_result, EnvelopeKind, WorkerEnvelope,
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
const BLUETOOTH_AUTO_CONNECT_MIN_BACKOFF: Duration = Duration::from_secs(15);
const BLUETOOTH_AUTO_CONNECT_MAX_BACKOFF: Duration = Duration::from_secs(5 * 60);

#[derive(Debug)]
struct PendingWifiChange {
    request_id: String,
    profile_id: String,
    operation: WifiChangeOperation,
    deadline: Instant,
    next_candidate_at: Instant,
    candidate_attempt: u8,
}

#[derive(Debug, Default)]
struct BluetoothAutoConnectRetry {
    failed_attempts: u32,
    retry_at: Option<Instant>,
}

#[derive(Debug, Default)]
struct BluetoothAutoConnectBackoff {
    retries: HashMap<String, BluetoothAutoConnectRetry>,
}

impl BluetoothAutoConnectBackoff {
    fn candidate(&mut self, state: &BluetoothState, now: Instant) -> Option<String> {
        if !state.radio_enabled {
            self.reset();
            return None;
        }
        self.retries.retain(|accessory_id, _| {
            state.accessories.iter().any(|accessory| {
                accessory.accessory_id == *accessory_id
                    && accessory.paired
                    && accessory.auto_connect
                    && !accessory.connected
            })
        });
        state
            .accessories
            .iter()
            .filter(|accessory| accessory.paired && accessory.auto_connect && !accessory.connected)
            .find(|accessory| {
                self.retries
                    .get(&accessory.accessory_id)
                    .and_then(|retry| retry.retry_at)
                    .map(|retry_at| now >= retry_at)
                    .unwrap_or(true)
            })
            .map(|accessory| accessory.accessory_id.clone())
    }

    fn record_failure(&mut self, accessory_id: String, now: Instant) {
        let retry = self.retries.entry(accessory_id).or_default();
        retry.failed_attempts = retry.failed_attempts.saturating_add(1);
        let exponent = retry.failed_attempts.saturating_sub(1).min(5);
        let multiplier = 1_u32 << exponent;
        let delay = BLUETOOTH_AUTO_CONNECT_MIN_BACKOFF
            .saturating_mul(multiplier)
            .min(BLUETOOTH_AUTO_CONNECT_MAX_BACKOFF);
        retry.retry_at = now.checked_add(delay);
    }

    fn record_success(&mut self, accessory_id: &str) {
        self.retries.remove(accessory_id);
    }

    fn reset(&mut self) {
        self.retries.clear();
    }
}

pub fn run(config_dir: &str) -> Result<()> {
    let mut stdout = io::stdout().lock();
    // A previous run that died ungracefully (crash / SIGKILL / power loss) while
    // the setup hotspot was up can leave the "yoyopod Setup" AP profile behind in
    // NetworkManager, keeping the device broadcasting and holding the radio. Clear
    // any such stale profile on startup, before the runtime loop begins.
    crate::provisioning::cleanup_stale_setup_ap();
    let wifi: Box<dyn WifiController> = NetworkManagerWifiController::connect()
        .map(|controller| Box::new(controller) as Box<dyn WifiController>)
        .unwrap_or_else(|_| Box::new(UnavailableWifiController));
    let bluetooth: Box<dyn BluetoothController> = Box::new(RecoveringBluetoothController::new());
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
            bluetooth,
            AudioManager::open(config_dir),
        ),
        Err(error) => run_with_runtime_loop(
            NetworkRuntime::degraded_config(config_dir, error.to_string()),
            stdin_channel(),
            &mut stdout,
            DEFAULT_POLL_INTERVAL,
            wifi,
            bluetooth,
            AudioManager::open(config_dir),
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
    let config_dir = runtime.snapshot().config_dir.clone();
    run_with_runtime_loop(
        runtime,
        reader_channel(input),
        output,
        poll_interval,
        Box::new(UnavailableWifiController),
        Box::new(UnavailableBluetoothController),
        AudioManager::open(&config_dir),
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
    let config_dir = runtime.snapshot().config_dir.clone();
    run_with_runtime_loop(
        runtime,
        reader_channel(input),
        output,
        poll_interval,
        wifi,
        Box::new(UnavailableBluetoothController),
        AudioManager::open(&config_dir),
    )
}

fn run_with_runtime_loop<C, W>(
    mut runtime: NetworkRuntime<C>,
    input_rx: mpsc::Receiver<io::Result<String>>,
    output: &mut W,
    poll_interval: Duration,
    mut wifi: Box<dyn WifiController>,
    mut bluetooth: Box<dyn BluetoothController>,
    mut audio: AudioManager,
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
    let mut bluetooth_state = bluetooth
        .refresh()
        .unwrap_or_else(|_| BluetoothState::unavailable());
    let mut bluetooth_auto_connect = BluetoothAutoConnectBackoff::default();
    bluetooth_state = auto_connect_saved_accessory(
        bluetooth.as_mut(),
        bluetooth_state,
        &mut bluetooth_auto_connect,
        Instant::now(),
    );
    emit_bluetooth_state(output, &bluetooth_state)?;
    if let Ok(applied) = audio.current(bluetooth.as_ref(), &bluetooth_state) {
        emit_applied_audio(output, &applied)?;
    }
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
                    bluetooth.as_mut(),
                    &mut bluetooth_state,
                    &mut audio,
                    envelope,
                    output,
                )? {
                    LoopControl::Continue => {}
                    LoopControl::Shutdown => break,
                }
                service_pending_wifi_change(output, wifi.as_mut(), &mut pending_wifi_change)?;
                service_provisioning(output, &mut provisioning)?;
                service_bluetooth_and_audio(
                    output,
                    bluetooth.as_mut(),
                    &mut bluetooth_state,
                    &mut bluetooth_auto_connect,
                    &mut audio,
                )?;
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
                service_bluetooth_and_audio(
                    output,
                    bluetooth.as_mut(),
                    &mut bluetooth_state,
                    &mut bluetooth_auto_connect,
                    &mut audio,
                )?;
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
    bluetooth: &mut dyn BluetoothController,
    bluetooth_state: &mut BluetoothState,
    audio: &mut AudioManager,
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
        && envelope.message_type.starts_with("wifi_")
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
        "bluetooth_refresh" => {
            handle_bluetooth_operation(
                output,
                envelope.request_id,
                bluetooth.refresh(),
                bluetooth,
                bluetooth_state,
                audio,
            )?;
        }
        "bluetooth_set_radio" => {
            let enabled = envelope
                .payload
                .get("enabled")
                .and_then(serde_json::Value::as_bool)
                .ok_or_else(|| BluetoothOperationError {
                    code: "bluetooth_invalid_request",
                    message: "Bluetooth power setting is invalid".to_string(),
                });
            let result = enabled.and_then(|enabled| bluetooth.set_radio(enabled));
            handle_bluetooth_operation(
                output,
                envelope.request_id,
                result,
                bluetooth,
                bluetooth_state,
                audio,
            )?;
        }
        "bluetooth_scan_start" => {
            let result = bluetooth.start_scan();
            handle_bluetooth_operation(
                output,
                envelope.request_id,
                result,
                bluetooth,
                bluetooth_state,
                audio,
            )?;
        }
        "bluetooth_scan_stop" => {
            let result = bluetooth.stop_scan();
            handle_bluetooth_operation(
                output,
                envelope.request_id,
                result,
                bluetooth,
                bluetooth_state,
                audio,
            )?;
        }
        "bluetooth_pair" | "bluetooth_connect" | "bluetooth_disconnect" | "bluetooth_forget" => {
            let accessory_id = envelope
                .payload
                .get("accessory_id")
                .and_then(serde_json::Value::as_str)
                .filter(|value| !value.trim().is_empty())
                .map(str::to_owned)
                .ok_or_else(|| BluetoothOperationError {
                    code: "bluetooth_invalid_request",
                    message: "Bluetooth accessory reference is invalid".to_string(),
                });
            let result =
                accessory_id.and_then(|accessory_id| match envelope.message_type.as_str() {
                    "bluetooth_pair" => bluetooth.pair(&accessory_id),
                    "bluetooth_connect" => bluetooth.connect(&accessory_id),
                    "bluetooth_disconnect" => bluetooth.disconnect(&accessory_id),
                    _ => bluetooth.forget(&accessory_id),
                });
            handle_bluetooth_operation(
                output,
                envelope.request_id,
                result,
                bluetooth,
                bluetooth_state,
                audio,
            )?;
        }
        "bluetooth_update_accessory" => {
            let accessory_id = envelope
                .payload
                .get("accessory_id")
                .and_then(serde_json::Value::as_str)
                .filter(|value| !value.trim().is_empty())
                .map(str::to_owned)
                .ok_or_else(|| BluetoothOperationError {
                    code: "bluetooth_invalid_request",
                    message: "Bluetooth accessory reference is invalid".to_string(),
                });
            let alias = envelope
                .payload
                .get("alias")
                .and_then(serde_json::Value::as_str)
                .map(str::to_owned);
            let auto_connect = envelope
                .payload
                .get("auto_connect")
                .and_then(serde_json::Value::as_bool);
            let result = accessory_id.and_then(|accessory_id| {
                bluetooth.update_accessory(&accessory_id, alias.as_deref(), auto_connect)
            });
            handle_bluetooth_operation(
                output,
                envelope.request_id,
                result,
                bluetooth,
                bluetooth_state,
                audio,
            )?;
        }
        "audio_set_output_level" => {
            let cycle = envelope
                .payload
                .get("cycle")
                .and_then(serde_json::Value::as_bool)
                == Some(true);
            let level = envelope
                .payload
                .get("level")
                .and_then(serde_json::Value::as_u64)
                .filter(|level| *level <= 100)
                .map(|level| level as u8);
            let result = if cycle && level.is_none() {
                Some(audio.step_output_level(bluetooth, bluetooth_state))
            } else {
                level.map(|level| audio.set_output_level(level, bluetooth, bluetooth_state))
            };
            match result {
                Some(result) => match result {
                    Ok(applied) => {
                        write_envelope(
                            output,
                            &audio_state_result(envelope.request_id, &applied.state),
                        )?;
                        emit_applied_audio(output, &applied)?;
                    }
                    Err(error) => emit_audio_error(output, envelope.request_id, error)?,
                },
                None => emit_audio_error(
                    output,
                    envelope.request_id,
                    crate::audio::AudioOperationError {
                        code: "audio_invalid_settings",
                        message: "Audio output level must be a 0 to 100 value or a cycle request"
                            .to_string(),
                    },
                )?,
            }
        }
        "audio_apply_settings" => {
            let revision = envelope
                .payload
                .get("revision")
                .and_then(serde_json::Value::as_u64);
            let settings = envelope
                .payload
                .get("settings")
                .cloned()
                .and_then(|value| serde_json::from_value::<AudioSettings>(value).ok());
            match revision.zip(settings) {
                Some((revision, settings)) => {
                    match audio.apply(revision, settings, bluetooth, bluetooth_state) {
                        Ok(applied) => {
                            write_envelope(
                                output,
                                &audio_state_result(envelope.request_id, &applied.state),
                            )?;
                            emit_applied_audio(output, &applied)?;
                        }
                        Err(error) => emit_audio_error(output, envelope.request_id, error)?,
                    }
                }
                None => emit_audio_error(
                    output,
                    envelope.request_id,
                    crate::audio::AudioOperationError {
                        code: "audio_invalid_settings",
                        message: "Audio settings payload is invalid".to_string(),
                    },
                )?,
            }
        }
        "audio_test_output" => {
            let target = envelope
                .payload
                .get("target")
                .and_then(serde_json::Value::as_str)
                .unwrap_or("");
            match audio
                .current(bluetooth, bluetooth_state)
                .and_then(|applied| {
                    audio.test_output(target, &applied.route)?;
                    Ok(applied)
                }) {
                Ok(applied) => {
                    write_envelope(
                        output,
                        &audio_state_result(envelope.request_id, &applied.state),
                    )?;
                    emit_applied_audio(output, &applied)?;
                }
                Err(error) => emit_audio_error(output, envelope.request_id, error)?,
            }
        }
        "audio_test_input" => {
            let duration = envelope
                .payload
                .get("duration_seconds")
                .and_then(serde_json::Value::as_u64)
                .unwrap_or(10);
            let result = audio
                .current(bluetooth, bluetooth_state)
                .and_then(|applied| {
                    audio.test_input(&applied.route, duration)?;
                    audio.current(bluetooth, bluetooth_state)
                });
            match result {
                Ok(applied) => {
                    write_envelope(
                        output,
                        &audio_state_result(envelope.request_id, &applied.state),
                    )?;
                    emit_applied_audio(output, &applied)?;
                }
                Err(error) => emit_audio_error(output, envelope.request_id, error)?,
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

fn handle_bluetooth_operation(
    output: &mut dyn Write,
    request_id: Option<String>,
    result: Result<BluetoothState, BluetoothOperationError>,
    bluetooth: &dyn BluetoothController,
    bluetooth_state: &mut BluetoothState,
    audio: &mut AudioManager,
) -> Result<()> {
    match result {
        Ok(state) => {
            *bluetooth_state = state;
            write_envelope(output, &bluetooth_state_result(request_id, bluetooth_state))?;
            emit_bluetooth_state(output, bluetooth_state)?;
            if let Ok(applied) = audio.current(bluetooth, bluetooth_state) {
                emit_applied_audio(output, &applied)?;
            }
        }
        Err(error) => {
            write_envelope(
                output,
                &WorkerEnvelope::error("bluetooth_error", request_id, error.code, error.message),
            )?;
        }
    }
    Ok(())
}

fn service_bluetooth_and_audio(
    output: &mut dyn Write,
    bluetooth: &mut dyn BluetoothController,
    bluetooth_state: &mut BluetoothState,
    bluetooth_auto_connect: &mut BluetoothAutoConnectBackoff,
    audio: &mut AudioManager,
) -> Result<()> {
    let Some(state) = bluetooth.tick() else {
        return Ok(());
    };
    *bluetooth_state =
        auto_connect_saved_accessory(bluetooth, state, bluetooth_auto_connect, Instant::now());
    emit_bluetooth_state(output, bluetooth_state)?;
    if let Ok(Some(applied)) = audio.current_if_changed(bluetooth, bluetooth_state) {
        emit_applied_audio(output, &applied)?;
    }
    Ok(())
}

fn auto_connect_saved_accessory(
    bluetooth: &mut dyn BluetoothController,
    state: BluetoothState,
    backoff: &mut BluetoothAutoConnectBackoff,
    now: Instant,
) -> BluetoothState {
    let Some(accessory_id) = backoff.candidate(&state, now) else {
        return state;
    };
    match bluetooth.connect(&accessory_id) {
        Ok(connected) => {
            backoff.record_success(&accessory_id);
            connected
        }
        Err(_) => {
            backoff.record_failure(accessory_id, now);
            state
        }
    }
}

fn emit_bluetooth_state(output: &mut dyn Write, state: &BluetoothState) -> Result<()> {
    write_envelope(output, &bluetooth_state_event(state))
}

fn emit_applied_audio(output: &mut dyn Write, applied: &AppliedAudio) -> Result<()> {
    write_envelope(output, &audio_state_event(&applied.state))?;
    write_envelope(output, &audio_route_local_event(&applied.route))
}

fn emit_audio_error(
    output: &mut dyn Write,
    request_id: Option<String>,
    error: crate::audio::AudioOperationError,
) -> Result<()> {
    write_envelope(
        output,
        &WorkerEnvelope::error("audio_error", request_id, error.code, error.message),
    )
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
    use crate::bluetooth::{BluetoothAccessory, BluetoothCapabilities};
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

    fn auto_connect_state(accessory_id: &str) -> BluetoothState {
        BluetoothState {
            schema_version: 1,
            status: "ready".to_string(),
            radio_enabled: true,
            scanning: false,
            accessories: vec![BluetoothAccessory {
                accessory_id: accessory_id.to_string(),
                name: "Family headset".to_string(),
                kind: "headset".to_string(),
                paired: true,
                connected: false,
                trusted: true,
                auto_connect: true,
                capabilities: BluetoothCapabilities {
                    output: true,
                    microphone: true,
                    stereo: true,
                    hands_free: true,
                },
                battery_percent: None,
                signal_percent: None,
                last_seen_at: 1,
            }],
            scanned_at: None,
            reported_at: 1,
        }
    }

    #[test]
    fn failed_bluetooth_auto_connects_back_off_per_accessory() {
        let mut bluetooth = UnavailableBluetoothController;
        let mut backoff = BluetoothAutoConnectBackoff::default();
        let first_attempt_at = Instant::now();
        let state = auto_connect_state("accessory-a");

        let retained = auto_connect_saved_accessory(
            &mut bluetooth,
            state.clone(),
            &mut backoff,
            first_attempt_at,
        );
        assert_eq!(retained, state);
        let retry = backoff.retries.get("accessory-a").expect("retry state");
        assert_eq!(retry.failed_attempts, 1);
        let first_retry_at = retry.retry_at.expect("retry deadline");
        assert_eq!(
            first_retry_at.duration_since(first_attempt_at),
            BLUETOOTH_AUTO_CONNECT_MIN_BACKOFF
        );

        auto_connect_saved_accessory(
            &mut bluetooth,
            state.clone(),
            &mut backoff,
            first_retry_at - Duration::from_millis(1),
        );
        assert_eq!(backoff.retries["accessory-a"].failed_attempts, 1);

        auto_connect_saved_accessory(&mut bluetooth, state, &mut backoff, first_retry_at);
        assert_eq!(backoff.retries["accessory-a"].failed_attempts, 2);
        assert_eq!(
            backoff.retries["accessory-a"]
                .retry_at
                .expect("second retry deadline")
                .duration_since(first_retry_at),
            BLUETOOTH_AUTO_CONNECT_MIN_BACKOFF.saturating_mul(2)
        );

        let mut multiple = auto_connect_state("accessory-a");
        let mut second = multiple.accessories[0].clone();
        second.accessory_id = "accessory-b".to_string();
        second.name = "Second headset".to_string();
        multiple.accessories.push(second);
        auto_connect_saved_accessory(&mut bluetooth, multiple, &mut backoff, first_retry_at);
        assert_eq!(backoff.retries["accessory-a"].failed_attempts, 2);
        assert_eq!(backoff.retries["accessory-b"].failed_attempts, 1);
    }

    #[test]
    fn connected_auto_connect_accessories_do_not_block_remaining_routes() {
        let now = Instant::now();
        let mut state = auto_connect_state("accessory-a");
        state.accessories[0].connected = true;
        let mut second = state.accessories[0].clone();
        second.accessory_id = "accessory-b".to_string();
        second.name = "Second headset".to_string();
        second.connected = false;
        state.accessories.push(second);

        let mut backoff = BluetoothAutoConnectBackoff::default();
        backoff.record_failure("accessory-a".to_string(), now);

        assert_eq!(
            backoff.candidate(&state, now),
            Some("accessory-b".to_string())
        );
        assert!(!backoff.retries.contains_key("accessory-a"));
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
    fn bluetooth_commands_continue_during_pending_wifi_changes() {
        let activation_id = "77777777-7777-4777-8777-777777777777";
        let bluetooth_id = "88888888-8888-4888-8888-888888888888";
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
                    "bluetooth_refresh",
                    Some(bluetooth_id.to_string()),
                    serde_json::json!({}),
                ),
            ],
            false,
        );

        assert!(!envelopes.iter().any(|envelope| {
            envelope.request_id.as_deref() == Some(bluetooth_id)
                && envelope.payload["code"] == "wifi_change_in_progress"
        }));
        assert!(envelopes.iter().any(|envelope| {
            envelope.request_id.as_deref() == Some(bluetooth_id)
                && envelope.kind == EnvelopeKind::Result
                && envelope.message_type == "bluetooth_state"
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
