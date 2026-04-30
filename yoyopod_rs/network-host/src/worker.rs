use std::io::{self, BufRead, Read, Write};

use anyhow::Result;
use serde_json::json;

use crate::config::NetworkHostConfig;
use crate::modem::{ModemController, Sim7600ModemController};
use crate::protocol::{
    ready_event, snapshot_event, snapshot_result, stopped_event, EnvelopeKind, WorkerEnvelope,
};
use crate::runtime::NetworkRuntime;

pub fn run(config_dir: &str) -> Result<()> {
    let stdin = io::stdin();
    let mut stdout = io::stdout().lock();
    run_with_io(config_dir, stdin.lock(), &mut stdout)
}

pub fn run_with_io<R, W>(config_dir: &str, input: R, output: &mut W) -> Result<()>
where
    R: Read,
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
    mut runtime: NetworkRuntime<C>,
    input: R,
    output: &mut W,
) -> Result<()>
where
    C: ModemController,
    R: Read,
    W: Write,
{
    write_envelope(output, &ready_event(&runtime.snapshot().config_dir))?;
    if should_boot_runtime(runtime.snapshot()) {
        runtime.start();
    }
    write_envelope(output, &snapshot_event(runtime.snapshot()))?;

    let reader = io::BufReader::new(input);
    for line in reader.lines() {
        let line = line?;
        if line.trim().is_empty() {
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

        let before = runtime.snapshot().clone();
        match envelope.message_type.as_str() {
            "network.health" => {
                runtime.health();
                write_envelope(
                    output,
                    &snapshot_result("network.health", envelope.request_id, runtime.snapshot()),
                )?;
                if snapshot_changed(&before, runtime.snapshot()) {
                    write_envelope(output, &snapshot_event(runtime.snapshot()))?;
                }
            }
            "network.query_gps" => {
                runtime.query_gps();
                write_envelope(
                    output,
                    &snapshot_result("network.query_gps", envelope.request_id, runtime.snapshot()),
                )?;
                if snapshot_changed(&before, runtime.snapshot()) {
                    write_envelope(output, &snapshot_event(runtime.snapshot()))?;
                }
            }
            "network.reset_modem" => {
                runtime.reset_modem();
                write_envelope(
                    output,
                    &snapshot_result(
                        "network.reset_modem",
                        envelope.request_id,
                        runtime.snapshot(),
                    ),
                )?;
                if snapshot_changed(&before, runtime.snapshot()) {
                    write_envelope(output, &snapshot_event(runtime.snapshot()))?;
                }
            }
            "network.shutdown" | "worker.stop" => {
                runtime.shutdown();
                write_envelope(
                    output,
                    &WorkerEnvelope::result(
                        envelope.message_type,
                        envelope.request_id,
                        json!({"shutdown": true}),
                    ),
                )?;
                write_envelope(output, &snapshot_event(runtime.snapshot()))?;
                write_envelope(output, &stopped_event("shutdown"))?;
                break;
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
    }

    Ok(())
}

fn write_envelope(output: &mut dyn Write, envelope: &WorkerEnvelope) -> Result<()> {
    writeln!(output, "{}", serde_json::to_string(envelope)?)?;
    output.flush()?;
    Ok(())
}

fn snapshot_changed(
    previous: &crate::snapshot::NetworkRuntimeSnapshot,
    current: &crate::snapshot::NetworkRuntimeSnapshot,
) -> bool {
    let mut previous = previous.clone();
    let mut current = current.clone();
    previous.updated_at_ms = 0;
    current.updated_at_ms = 0;
    previous != current
}

fn should_boot_runtime(snapshot: &crate::snapshot::NetworkRuntimeSnapshot) -> bool {
    !(snapshot.state == crate::snapshot::NetworkLifecycleState::Degraded
        && snapshot.error_code == "config_load_failed")
}
