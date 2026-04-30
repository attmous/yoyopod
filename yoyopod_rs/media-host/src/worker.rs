use std::io::{BufRead, BufReader, Read, Write};

use anyhow::Result;
use serde_json::json;

use crate::config::MediaConfig;
use crate::host::MediaHost;
use crate::protocol::{EnvelopeKind, WorkerEnvelope};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LoopAction {
    Continue,
    Shutdown,
}

#[derive(Debug, Clone, PartialEq)]
pub struct CommandOutcome {
    pub action: LoopAction,
    pub envelopes: Vec<WorkerEnvelope>,
}

impl CommandOutcome {
    fn continue_with(envelopes: Vec<WorkerEnvelope>) -> Self {
        Self {
            action: LoopAction::Continue,
            envelopes,
        }
    }

    fn shutdown_with(envelopes: Vec<WorkerEnvelope>) -> Self {
        Self {
            action: LoopAction::Shutdown,
            envelopes,
        }
    }
}

pub fn run() -> Result<()> {
    let stdin = std::io::stdin();
    let mut stdout = std::io::stdout();
    let mut stderr = std::io::stderr();
    run_io(stdin, &mut stdout, &mut stderr)
}

pub fn run_io<R, W, E>(input: R, output: &mut W, errors: &mut E) -> Result<()>
where
    R: Read,
    W: Write,
    E: Write,
{
    let mut host = MediaHost::default();
    emit(
        output,
        &WorkerEnvelope::event(
            "media.ready",
            json!({"capabilities":["configure", "health"]}),
        ),
    )?;

    let reader = BufReader::new(input);
    for line in reader.lines() {
        let line = line?;
        if line.trim().is_empty() {
            continue;
        }

        match WorkerEnvelope::decode(line.as_bytes()) {
            Ok(envelope) => {
                if envelope.kind != EnvelopeKind::Command {
                    writeln!(
                        errors,
                        "invalid media worker envelope kind: {:?}",
                        envelope.kind
                    )?;
                    emit(
                        output,
                        &WorkerEnvelope::error(
                            "media.error",
                            envelope.request_id.clone(),
                            "invalid_kind",
                            "media worker accepts commands only",
                        ),
                    )?;
                    continue;
                }

                match handle_command(envelope, &mut host) {
                    Ok(outcome) => {
                        for envelope in &outcome.envelopes {
                            emit(output, envelope)?;
                        }
                        if matches!(outcome.action, LoopAction::Shutdown) {
                            break;
                        }
                    }
                    Err(error) => {
                        writeln!(errors, "media worker command failed: {error}")?;
                        emit(
                            output,
                            &WorkerEnvelope::error(
                                "media.error",
                                None,
                                "command_failed",
                                error.to_string(),
                            ),
                        )?;
                    }
                }
            }
            Err(error) => {
                writeln!(errors, "media protocol decode error: {error}")?;
                emit(
                    output,
                    &WorkerEnvelope::error(
                        "media.error",
                        None,
                        "protocol_error",
                        error.to_string(),
                    ),
                )?;
            }
        }
    }

    Ok(())
}

pub fn handle_command(envelope: WorkerEnvelope, host: &mut MediaHost) -> Result<CommandOutcome> {
    host.record_command();

    let request_id = envelope.request_id.clone();
    match envelope.message_type.as_str() {
        "media.configure" => {
            let config = MediaConfig::from_payload(&envelope.payload)?;
            host.configure(config);
            Ok(CommandOutcome::continue_with(vec![
                WorkerEnvelope::result("media.configure", request_id, json!({"configured": true})),
                WorkerEnvelope::event("media.snapshot", host.snapshot_payload()),
            ]))
        }
        "media.health" => Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::result(
            "media.health",
            request_id,
            host.health_payload(),
        )])),
        "media.shutdown" | "worker.stop" => {
            Ok(CommandOutcome::shutdown_with(vec![WorkerEnvelope::result(
                envelope.message_type,
                request_id,
                json!({"shutdown": true}),
            )]))
        }
        _ => Ok(CommandOutcome::continue_with(vec![WorkerEnvelope::error(
            "media.error",
            request_id,
            "unsupported_command",
            format!("unsupported command {}", envelope.message_type),
        )])),
    }
}

fn emit<W: Write>(output: &mut W, envelope: &WorkerEnvelope) -> Result<()> {
    output.write_all(&envelope.encode()?)?;
    output.flush()?;
    Ok(())
}
