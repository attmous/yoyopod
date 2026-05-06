use std::io::{self, BufRead, Read, Write};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::time::Duration;

use anyhow::Result;

use crate::config::NetworkHostConfig;
use crate::modem::{ModemController, Sim7600ModemController};
use crate::protocol::{
    health_result, ready_event, snapshot_event, snapshot_result, stopped_event, stopped_result,
    EnvelopeKind, WorkerEnvelope,
};
use crate::runtime::{NetworkRuntime, RuntimeCommandError};

const DEFAULT_POLL_INTERVAL: Duration = Duration::from_millis(100);

pub fn run(config_dir: &str) -> Result<()> {
    let mut stdout = io::stdout().lock();
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
        ),
        Err(error) => run_with_runtime_loop(
            NetworkRuntime::degraded_config(config_dir, error.to_string()),
            stdin_channel(),
            &mut stdout,
            DEFAULT_POLL_INTERVAL,
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
    run_with_runtime_loop(runtime, reader_channel(input), output, poll_interval)
}

fn run_with_runtime_loop<C, W>(
    mut runtime: NetworkRuntime<C>,
    input_rx: mpsc::Receiver<io::Result<String>>,
    output: &mut W,
    poll_interval: Duration,
) -> Result<()>
where
    C: ModemController,
    W: Write,
{
    write_envelope(output, &ready_event(&runtime.snapshot().config_dir))?;
    write_envelope(output, &snapshot_event(runtime.snapshot()))?;
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

                match handle_command(&mut runtime, envelope, output)? {
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
