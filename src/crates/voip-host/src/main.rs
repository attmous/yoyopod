use anyhow::{anyhow, Result};
use clap::Parser;
use serde_json::json;
use std::io::{self, BufRead, Write};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::time::Duration;

mod config;
mod events;
mod host;
mod protocol;
mod shim;

use config::VoipConfig;
use host::VoipHost;
use protocol::WorkerEnvelope;

#[derive(Debug, Parser)]
#[command(name = "yoyopod-voip-host")]
#[command(about = "YoYoPod Rust VoIP host")]
struct Args {
    #[arg(long, default_value = "")]
    shim_path: String,
}

fn main() -> Result<()> {
    let args = Args::parse();
    let explicit_shim_path = if args.shim_path.trim().is_empty() {
        None
    } else {
        Some(args.shim_path.clone())
    };
    let mut host = VoipHost::default();
    let mut backend: Option<shim::ShimBackend> = None;

    write_envelope(&WorkerEnvelope::event(
        "voip.ready",
        json!({"capabilities":["calls"]}),
    ))?;

    let (stdin_tx, stdin_rx) = mpsc::channel();
    std::thread::spawn(move || {
        let stdin = io::stdin();
        for line in stdin.lock().lines() {
            if stdin_tx.send(line).is_err() {
                break;
            }
        }
    });

    loop {
        match stdin_rx.recv_timeout(next_loop_timeout(&host, backend.is_some())) {
            Ok(Ok(line)) => {
                if !line.trim().is_empty() {
                    let envelope = match WorkerEnvelope::decode(line.as_bytes()) {
                        Ok(envelope) => envelope,
                        Err(error) => {
                            write_envelope(&WorkerEnvelope::error(
                                "voip.error",
                                None,
                                "protocol_error",
                                error.to_string(),
                            ))?;
                            poll_backend(&mut host, &mut backend)?;
                            continue;
                        }
                    };

                    let request_id = envelope.request_id.clone();
                    match handle_command(
                        envelope,
                        &mut host,
                        &mut backend,
                        explicit_shim_path.as_deref(),
                    ) {
                        Ok(LoopAction::Continue) => {}
                        Ok(LoopAction::Shutdown) => break,
                        Err(error) => {
                            write_envelope(&WorkerEnvelope::error(
                                "voip.error",
                                request_id,
                                "command_failed",
                                error.to_string(),
                            ))?;
                        }
                    }
                }
                poll_backend(&mut host, &mut backend)?;
            }
            Ok(Err(error)) => return Err(error.into()),
            Err(RecvTimeoutError::Timeout) => {
                poll_backend(&mut host, &mut backend)?;
            }
            Err(RecvTimeoutError::Disconnected) => break,
        }
    }
    Ok(())
}

enum LoopAction {
    Continue,
    Shutdown,
}

fn handle_command(
    envelope: WorkerEnvelope,
    host: &mut VoipHost,
    backend: &mut Option<shim::ShimBackend>,
    explicit_shim_path: Option<&str>,
) -> Result<LoopAction> {
    match envelope.message_type.as_str() {
        "voip.configure" => {
            let config = VoipConfig::from_payload(&envelope.payload)?;
            host.configure(config);
            write_envelope(&WorkerEnvelope::result(
                "voip.configure",
                envelope.request_id,
                json!({"configured": true}),
            ))?;
        }
        "voip.health" => {
            let mut payload = host.health_payload();
            payload["ready"] = json!(true);
            write_envelope(&WorkerEnvelope::result(
                "voip.health",
                envelope.request_id,
                payload,
            ))?;
        }
        "voip.register" => {
            if backend.is_none() {
                let path = shim::resolve_shim_path(explicit_shim_path)?;
                *backend = Some(unsafe { shim::ShimBackend::load(&path) }?);
            }
            let backend_ref = backend.as_mut().expect("backend was just created");
            host.register(backend_ref).map_err(|error| anyhow!(error))?;
            write_envelope(&WorkerEnvelope::result(
                "voip.register",
                envelope.request_id,
                json!({"registered": true}),
            ))?;
        }
        "voip.unregister" => {
            if let Some(mut backend_ref) = backend.take() {
                host.unregister(&mut backend_ref);
            }
            write_envelope(&WorkerEnvelope::result(
                "voip.unregister",
                envelope.request_id,
                json!({"registered": false}),
            ))?;
        }
        "voip.dial" => {
            let uri = envelope.payload["uri"].as_str().unwrap_or("").trim();
            if uri.is_empty() {
                write_envelope(&WorkerEnvelope::error(
                    "voip.error",
                    envelope.request_id,
                    "invalid_command",
                    "voip.dial requires uri",
                ))?;
            } else {
                let backend_ref = backend
                    .as_mut()
                    .ok_or_else(|| anyhow!("voip host is not registered"))?;
                host.dial(backend_ref, uri)
                    .map_err(|error| anyhow!(error))?;
                write_envelope(&WorkerEnvelope::result(
                    "voip.dial",
                    envelope.request_id,
                    host.health_payload(),
                ))?;
            }
        }
        "voip.answer" => {
            let backend_ref = backend
                .as_mut()
                .ok_or_else(|| anyhow!("voip host is not registered"))?;
            host.answer(backend_ref).map_err(|error| anyhow!(error))?;
            write_envelope(&WorkerEnvelope::result(
                "voip.answer",
                envelope.request_id,
                json!({"accepted": true}),
            ))?;
        }
        "voip.reject" => {
            let backend_ref = backend
                .as_mut()
                .ok_or_else(|| anyhow!("voip host is not registered"))?;
            host.reject(backend_ref).map_err(|error| anyhow!(error))?;
            write_envelope(&WorkerEnvelope::result(
                "voip.reject",
                envelope.request_id,
                json!({"rejected": true}),
            ))?;
        }
        "voip.hangup" => {
            let backend_ref = backend
                .as_mut()
                .ok_or_else(|| anyhow!("voip host is not registered"))?;
            host.hangup(backend_ref).map_err(|error| anyhow!(error))?;
            write_envelope(&WorkerEnvelope::result(
                "voip.hangup",
                envelope.request_id,
                json!({"hung_up": true}),
            ))?;
        }
        "voip.set_mute" => {
            let muted = envelope.payload["muted"].as_bool().unwrap_or(false);
            let backend_ref = backend
                .as_mut()
                .ok_or_else(|| anyhow!("voip host is not registered"))?;
            host.set_muted(backend_ref, muted)
                .map_err(|error| anyhow!(error))?;
            write_envelope(&WorkerEnvelope::result(
                "voip.set_mute",
                envelope.request_id,
                json!({"muted": muted}),
            ))?;
        }
        "voip.shutdown" | "worker.stop" => {
            if let Some(mut backend_ref) = backend.take() {
                host.unregister(&mut backend_ref);
            }
            write_envelope(&WorkerEnvelope::result(
                envelope.message_type,
                envelope.request_id,
                json!({"shutdown": true}),
            ))?;
            return Ok(LoopAction::Shutdown);
        }
        _ => {
            write_envelope(&WorkerEnvelope::error(
                "voip.error",
                envelope.request_id,
                "unsupported_command",
                format!("unsupported command {}", envelope.message_type),
            ))?;
        }
    }

    Ok(LoopAction::Continue)
}

fn next_loop_timeout(host: &VoipHost, backend_running: bool) -> Duration {
    if backend_running {
        Duration::from_millis(host.iterate_interval_ms())
    } else {
        Duration::from_secs(60)
    }
}

fn poll_backend(host: &mut VoipHost, backend: &mut Option<shim::ShimBackend>) -> Result<()> {
    if let Some(backend_ref) = backend.as_mut() {
        emit_backend_events(
            host.poll_backend_events(backend_ref)
                .map_err(|error| anyhow!(error))?,
        )?;
    }
    Ok(())
}

fn emit_backend_events(events: Vec<host::BackendEvent>) -> Result<()> {
    for event in events {
        write_envelope(&backend_event_envelope(event))?;
    }
    Ok(())
}

fn backend_event_envelope(event: host::BackendEvent) -> WorkerEnvelope {
    match event {
        host::BackendEvent::RegistrationChanged { state, reason } => WorkerEnvelope::event(
            "voip.registration_changed",
            json!({"state": state, "reason": reason}),
        ),
        host::BackendEvent::IncomingCall { call_id, from_uri } => WorkerEnvelope::event(
            "voip.incoming_call",
            json!({"call_id": call_id, "from_uri": from_uri}),
        ),
        host::BackendEvent::CallStateChanged { call_id, state } => WorkerEnvelope::event(
            "voip.call_state_changed",
            json!({"call_id": call_id, "state": state}),
        ),
        host::BackendEvent::BackendStopped { reason } => {
            WorkerEnvelope::event("voip.backend_stopped", json!({"reason": reason}))
        }
    }
}

fn write_envelope(envelope: &WorkerEnvelope) -> Result<()> {
    let encoded = envelope.encode()?;
    let mut stdout = io::stdout().lock();
    stdout.write_all(&encoded)?;
    stdout.flush()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn backend_events_map_to_worker_envelopes() {
        let envelope = backend_event_envelope(host::BackendEvent::IncomingCall {
            call_id: "call-1".to_string(),
            from_uri: "sip:bob@example.com".to_string(),
        });

        assert_eq!(envelope.message_type, "voip.incoming_call");
        assert_eq!(envelope.payload["call_id"], "call-1");
        assert_eq!(envelope.payload["from_uri"], "sip:bob@example.com");
    }

    #[test]
    fn worker_stop_uses_shutdown_path() {
        let mut host = VoipHost::default();
        let mut backend = None;
        let action = handle_command(
            WorkerEnvelope {
                schema_version: protocol::SUPPORTED_SCHEMA_VERSION,
                kind: protocol::EnvelopeKind::Command,
                message_type: "worker.stop".to_string(),
                request_id: Some("stop-1".to_string()),
                timestamp_ms: 0,
                deadline_ms: 0,
                payload: json!({}),
            },
            &mut host,
            &mut backend,
            None,
        )
        .expect("worker.stop should be handled");

        assert!(matches!(action, LoopAction::Shutdown));
    }
}
