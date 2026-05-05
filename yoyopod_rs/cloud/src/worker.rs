use std::io::{self, BufRead, BufReader, Read, Write};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::time::Duration;

use anyhow::{anyhow, Result};
use serde_json::{json, Value};

use crate::config::CloudHostConfig;
use crate::host::{CloudHost, CloudRuntimeEvent};
use crate::mqtt::{CloudMqttBackend, RumqttBackend};
use crate::protocol::{
    ready_event, snapshot_event, snapshot_result, stopped_event, stopped_result, EnvelopeKind,
    WorkerEnvelope,
};

const DEFAULT_POLL_INTERVAL: Duration = Duration::from_millis(100);

pub fn run(config_dir: &str) -> Result<()> {
    let stdin = io::stdin();
    let mut stdout = io::stdout();
    run_with_backend(config_dir, stdin, &mut stdout, RumqttBackend::default())
}

pub fn run_with_io<R, W>(config_dir: &str, input: R, output: &mut W) -> Result<()>
where
    R: Read + Send + 'static,
    W: Write,
{
    run_with_backend(config_dir, input, output, RumqttBackend::default())
}

pub fn run_with_backend<R, W, B>(
    config_dir: &str,
    input: R,
    output: &mut W,
    backend: B,
) -> Result<()>
where
    R: Read + Send + 'static,
    W: Write,
    B: CloudMqttBackend,
{
    let (config, load_error) = match CloudHostConfig::load(config_dir) {
        Ok(config) => (config, None),
        Err(error) => (
            CloudHostConfig::default_for_config_dir(config_dir),
            Some(error.to_string()),
        ),
    };
    let mut host = CloudHost::new(config_dir, config, backend);
    if let Some(error) = load_error {
        host.mark_config_load_failed(error);
    }
    run_host_loop(host, input, output, DEFAULT_POLL_INTERVAL)
}

pub fn run_host_loop<R, W, B>(
    mut host: CloudHost<B>,
    input: R,
    output: &mut W,
    poll_interval: Duration,
) -> Result<()>
where
    R: Read + Send + 'static,
    W: Write,
    B: CloudMqttBackend,
{
    let started = match host.start() {
        Ok(()) => true,
        Err(error) => {
            emit(
                output,
                &WorkerEnvelope::error("cloud.error", None, "startup_failed", error.to_string()),
            )?;
            false
        }
    };
    if started {
        emit(output, &ready_event(host.config_dir()))?;
    } else {
        emit(
            output,
            &WorkerEnvelope::error(
                "cloud.error",
                None,
                "not_ready",
                "cloud MQTT startup failed before ready",
            ),
        )?;
    }
    emit(output, &snapshot_event(host.snapshot()))?;

    let (stdin_tx, stdin_rx) = mpsc::channel();
    std::thread::spawn(move || {
        let reader = BufReader::new(input);
        for line in reader.lines() {
            if stdin_tx.send(line).is_err() {
                break;
            }
        }
    });

    loop {
        match stdin_rx.recv_timeout(poll_interval) {
            Ok(Ok(line)) => {
                if line.trim().is_empty() {
                    emit_runtime_events(output, &mut host)?;
                    continue;
                }
                let envelope = match WorkerEnvelope::decode(line.as_bytes()) {
                    Ok(envelope) => envelope,
                    Err(error) => {
                        emit(
                            output,
                            &WorkerEnvelope::error(
                                "cloud.error",
                                None,
                                "protocol_error",
                                error.to_string(),
                            ),
                        )?;
                        continue;
                    }
                };
                if envelope.kind != EnvelopeKind::Command {
                    emit(
                        output,
                        &WorkerEnvelope::error(
                            "cloud.error",
                            envelope.request_id,
                            "invalid_kind",
                            "cloud worker accepts commands only",
                        ),
                    )?;
                    continue;
                }

                match handle_command(&mut host, envelope)? {
                    LoopControl::Continue(envelopes) => {
                        for envelope in envelopes {
                            emit(output, &envelope)?;
                        }
                        emit_runtime_events(output, &mut host)?;
                    }
                    LoopControl::Shutdown(envelopes) => {
                        for envelope in envelopes {
                            emit(output, &envelope)?;
                        }
                        emit_runtime_events(output, &mut host)?;
                        emit(output, &stopped_event("shutdown"))?;
                        break;
                    }
                }
            }
            Ok(Err(error)) => {
                host.stop();
                emit(output, &stopped_event("input_error"))?;
                return Err(error.into());
            }
            Err(RecvTimeoutError::Timeout) => {
                emit_runtime_events(output, &mut host)?;
            }
            Err(RecvTimeoutError::Disconnected) => {
                host.stop();
                emit(output, &stopped_event("input_closed"))?;
                break;
            }
        }
    }

    Ok(())
}

enum LoopControl {
    Continue(Vec<WorkerEnvelope>),
    Shutdown(Vec<WorkerEnvelope>),
}

fn handle_command<B: CloudMqttBackend>(
    host: &mut CloudHost<B>,
    envelope: WorkerEnvelope,
) -> Result<LoopControl> {
    let request_id = envelope.request_id.clone();
    let result = match envelope.message_type.as_str() {
        "cloud.health" => snapshot_result(request_id, host.snapshot()),
        "cloud.publish_heartbeat" => {
            let firmware_version = string_field(&envelope.payload, "firmware_version");
            let published = host.publish_heartbeat(firmware_version.as_deref())?;
            publish_result(envelope.message_type, request_id, published)
        }
        "cloud.publish_battery" => {
            let level = envelope
                .payload
                .get("level")
                .and_then(Value::as_i64)
                .ok_or_else(|| anyhow!("cloud.publish_battery requires level"))?;
            let charging = envelope
                .payload
                .get("charging")
                .and_then(Value::as_bool)
                .unwrap_or(false);
            let published = host.publish_battery(level, charging)?;
            publish_result(envelope.message_type, request_id, published)
        }
        "cloud.publish_connectivity" => {
            let connection_type = string_field(&envelope.payload, "connection_type")
                .or_else(|| string_field(&envelope.payload, "type"))
                .unwrap_or_else(|| "unknown".to_string());
            let published = host.publish_connectivity(&connection_type)?;
            publish_result(envelope.message_type, request_id, published)
        }
        "cloud.publish_playback_event" => {
            let payload = envelope
                .payload
                .get("payload")
                .cloned()
                .unwrap_or_else(|| json!({}));
            let published = host.publish_playback_event(payload)?;
            publish_result(envelope.message_type, request_id, published)
        }
        "cloud.publish_event" => {
            let event_type = string_field(&envelope.payload, "event_type")
                .or_else(|| string_field(&envelope.payload, "type"))
                .ok_or_else(|| anyhow!("cloud.publish_event requires event_type"))?;
            let payload = envelope
                .payload
                .get("payload")
                .cloned()
                .unwrap_or_else(|| json!({}));
            let published = host.publish_device_event(&event_type, payload)?;
            publish_result(envelope.message_type, request_id, published)
        }
        "cloud.publish_telemetry" => {
            let topic_suffix = string_field(&envelope.payload, "topic_suffix")
                .or_else(|| string_field(&envelope.payload, "entity"))
                .ok_or_else(|| anyhow!("cloud.publish_telemetry requires topic_suffix"))?;
            let payload = envelope
                .payload
                .get("payload")
                .cloned()
                .unwrap_or_else(|| json!({}));
            let qos = envelope
                .payload
                .get("qos")
                .and_then(Value::as_u64)
                .and_then(|value| u8::try_from(value).ok())
                .unwrap_or(0);
            let published = host.publish_telemetry(&topic_suffix, payload, qos)?;
            publish_result(envelope.message_type, request_id, published)
        }
        "cloud.ack" => {
            let command_id = string_field(&envelope.payload, "command_id")
                .or_else(|| string_field(&envelope.payload, "commandId"))
                .ok_or_else(|| anyhow!("cloud.ack requires command_id"))?;
            let ok = envelope
                .payload
                .get("ok")
                .and_then(Value::as_bool)
                .unwrap_or(true);
            let reason = string_field(&envelope.payload, "reason");
            let payload = envelope
                .payload
                .get("payload")
                .cloned()
                .unwrap_or_else(|| json!({}));
            let published = host.publish_ack(&command_id, ok, reason.as_deref(), payload)?;
            publish_result(envelope.message_type, request_id, published)
        }
        "cloud.shutdown" | "worker.stop" => {
            host.stop();
            return Ok(LoopControl::Shutdown(vec![stopped_result(
                request_id, "shutdown",
            )]));
        }
        _ => WorkerEnvelope::error(
            "cloud.error",
            request_id,
            "unsupported_command",
            format!("unsupported command {}", envelope.message_type),
        ),
    };

    Ok(LoopControl::Continue(vec![
        result,
        snapshot_event(host.snapshot()),
    ]))
}

fn emit_runtime_events<W: Write, B: CloudMqttBackend>(
    output: &mut W,
    host: &mut CloudHost<B>,
) -> Result<()> {
    for event in host.drain_runtime_events() {
        match event {
            CloudRuntimeEvent::Snapshot(snapshot) => emit(output, &snapshot_event(&snapshot))?,
            CloudRuntimeEvent::Command(command) => emit(
                output,
                &WorkerEnvelope::event(
                    "cloud.command",
                    json!({
                        "command": command,
                    }),
                ),
            )?,
            CloudRuntimeEvent::Error(message) => emit(
                output,
                &WorkerEnvelope::error("cloud.error", None, "mqtt_error", message),
            )?,
        }
    }
    Ok(())
}

fn publish_result(
    message_type: String,
    request_id: Option<String>,
    published: bool,
) -> WorkerEnvelope {
    WorkerEnvelope::result(
        message_type,
        request_id,
        json!({
            "published": published,
        }),
    )
}

fn emit(output: &mut dyn Write, envelope: &WorkerEnvelope) -> Result<()> {
    output.write_all(&envelope.encode()?)?;
    output.flush()?;
    Ok(())
}

fn string_field(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}
