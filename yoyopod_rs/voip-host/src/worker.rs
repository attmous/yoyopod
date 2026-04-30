use anyhow::{anyhow, Result};
use serde_json::json;
use std::io::{BufRead, Write};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::thread;
use std::time::Duration;

use crate::config::VoipConfig;
use crate::host::{self, VoipHost, VoipRuntimeBackend};
use crate::protocol::WorkerEnvelope;

pub fn run_worker<R, W, E, B>(
    input: R,
    output: &mut W,
    _errors: &mut E,
    host: &mut VoipHost,
    backend: &mut B,
) -> Result<()>
where
    R: BufRead + Send + 'static,
    W: Write + ?Sized,
    E: Write + ?Sized,
    B: VoipRuntimeBackend,
{
    let mut backend_state = AttachedBackend::new(backend);
    let input = spawn_input_reader(input);
    write_envelope_to(
        output,
        &WorkerEnvelope::event(
            "voip.ready",
            json!({"capabilities":["calls", "text_messages", "voice_notes"]}),
        ),
    )?;

    loop {
        let poll_interval = Duration::from_millis(host.iterate_interval_ms().max(1));
        let line = match input.recv_timeout(poll_interval) {
            Ok(InputLine::Line(line)) => line,
            Ok(InputLine::ReadError(error)) => return Err(anyhow!(error)),
            Ok(InputLine::Eof) => break,
            Err(RecvTimeoutError::Timeout) => {
                poll_worker_backend(host, &mut backend_state, output)?;
                continue;
            }
            Err(RecvTimeoutError::Disconnected) => break,
        };
        if line.trim().is_empty() {
            poll_worker_backend(host, &mut backend_state, output)?;
            continue;
        }
        let envelope = match WorkerEnvelope::decode(line.as_bytes()) {
            Ok(envelope) => envelope,
            Err(error) => {
                write_envelope_to(
                    output,
                    &WorkerEnvelope::error("voip.error", None, "protocol_error", error.to_string()),
                )?;
                poll_worker_backend(host, &mut backend_state, output)?;
                continue;
            }
        };

        let request_id = envelope.request_id.clone();
        match handle_worker_command(envelope, host, &mut backend_state, output) {
            Ok(LoopAction::Continue) => {}
            Ok(LoopAction::Shutdown) => break,
            Err(error) => {
                write_envelope_to(
                    output,
                    &WorkerEnvelope::error(
                        "voip.error",
                        request_id,
                        "command_failed",
                        error.to_string(),
                    ),
                )?;
            }
        }
        poll_worker_backend(host, &mut backend_state, output)?;
    }
    Ok(())
}

enum InputLine {
    Line(String),
    ReadError(String),
    Eof,
}

fn spawn_input_reader<R>(input: R) -> Receiver<InputLine>
where
    R: BufRead + Send + 'static,
{
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        for line in input.lines() {
            let message = match line {
                Ok(line) => InputLine::Line(line),
                Err(error) => InputLine::ReadError(error.to_string()),
            };
            let terminal = matches!(message, InputLine::ReadError(_));
            if sender.send(message).is_err() || terminal {
                return;
            }
        }
        let _ = sender.send(InputLine::Eof);
    });
    receiver
}

pub enum LoopAction {
    Continue,
    Shutdown,
}

pub trait WorkerBackendState {
    fn is_running(&self) -> bool;
    fn register(&mut self, host: &mut VoipHost) -> Result<()>;
    fn unregister(&mut self, host: &mut VoipHost);
    fn with_backend<T>(
        &mut self,
        operation: impl FnOnce(&mut dyn VoipRuntimeBackend) -> Result<T, String>,
    ) -> Result<T>;
}

struct AttachedBackend<'a, B: VoipRuntimeBackend> {
    backend: &'a mut B,
    running: bool,
}

impl<'a, B: VoipRuntimeBackend> AttachedBackend<'a, B> {
    fn new(backend: &'a mut B) -> Self {
        Self {
            backend,
            running: false,
        }
    }
}

impl<B: VoipRuntimeBackend> WorkerBackendState for AttachedBackend<'_, B> {
    fn is_running(&self) -> bool {
        self.running
    }

    fn register(&mut self, host: &mut VoipHost) -> Result<()> {
        if !self.running {
            host.register(self.backend)
                .map_err(|error| anyhow!(error))?;
            self.running = true;
        }
        Ok(())
    }

    fn unregister(&mut self, host: &mut VoipHost) {
        if self.running {
            host.unregister(self.backend);
            self.running = false;
        }
    }

    fn with_backend<T>(
        &mut self,
        operation: impl FnOnce(&mut dyn VoipRuntimeBackend) -> Result<T, String>,
    ) -> Result<T> {
        if !self.running {
            return Err(anyhow!("voip host is not registered"));
        }
        operation(self.backend).map_err(|error| anyhow!(error))
    }
}

fn handle_worker_command<S, W>(
    envelope: WorkerEnvelope,
    host: &mut VoipHost,
    backend: &mut S,
    output: &mut W,
) -> Result<LoopAction>
where
    S: WorkerBackendState,
    W: Write + ?Sized,
{
    match envelope.message_type.as_str() {
        "voip.configure" => {
            let config = VoipConfig::from_payload(&envelope.payload)?;
            host.configure(config);
            write_envelope_to(
                output,
                &WorkerEnvelope::result(
                    "voip.configure",
                    envelope.request_id,
                    json!({"configured": true}),
                ),
            )?;
            write_lifecycle_events(host, output)?;
            write_session_snapshot(host, output)?;
        }
        "voip.health" => {
            let mut payload = host.health_payload();
            payload["ready"] = json!(true);
            write_envelope_to(
                output,
                &WorkerEnvelope::result("voip.health", envelope.request_id, payload),
            )?;
        }
        "voip.register" => {
            if let Err(error) = backend.register(host) {
                write_lifecycle_events(host, output)?;
                write_session_snapshot(host, output)?;
                return Err(error);
            }
            write_envelope_to(
                output,
                &WorkerEnvelope::result(
                    "voip.register",
                    envelope.request_id,
                    json!({"registered": true}),
                ),
            )?;
            write_lifecycle_events(host, output)?;
            write_session_snapshot(host, output)?;
        }
        "voip.unregister" => {
            backend.unregister(host);
            write_envelope_to(
                output,
                &WorkerEnvelope::result(
                    "voip.unregister",
                    envelope.request_id,
                    json!({"registered": false}),
                ),
            )?;
            write_lifecycle_events(host, output)?;
            write_session_snapshot(host, output)?;
        }
        "voip.dial" => {
            let uri = envelope.payload["uri"].as_str().unwrap_or("").trim();
            if uri.is_empty() {
                write_envelope_to(
                    output,
                    &WorkerEnvelope::error(
                        "voip.error",
                        envelope.request_id,
                        "invalid_command",
                        "voip.dial requires uri",
                    ),
                )?;
            } else {
                backend.with_backend(|backend_ref| host.dial(backend_ref, uri))?;
                write_envelope_to(
                    output,
                    &WorkerEnvelope::result(
                        "voip.dial",
                        envelope.request_id,
                        host.health_payload(),
                    ),
                )?;
                write_session_snapshot(host, output)?;
            }
        }
        "voip.answer" => {
            backend.with_backend(|backend_ref| host.answer(backend_ref))?;
            write_envelope_to(
                output,
                &WorkerEnvelope::result(
                    "voip.answer",
                    envelope.request_id,
                    json!({"accepted": true}),
                ),
            )?;
            write_session_snapshot(host, output)?;
        }
        "voip.reject" => {
            backend.with_backend(|backend_ref| host.reject(backend_ref))?;
            write_envelope_to(
                output,
                &WorkerEnvelope::result(
                    "voip.reject",
                    envelope.request_id,
                    json!({"rejected": true}),
                ),
            )?;
            write_session_snapshot(host, output)?;
        }
        "voip.hangup" => {
            backend.with_backend(|backend_ref| host.hangup(backend_ref))?;
            write_envelope_to(
                output,
                &WorkerEnvelope::result(
                    "voip.hangup",
                    envelope.request_id,
                    json!({"hung_up": true}),
                ),
            )?;
            write_session_snapshot(host, output)?;
        }
        "voip.set_mute" => {
            let muted = envelope.payload["muted"].as_bool().unwrap_or(false);
            backend.with_backend(|backend_ref| host.set_muted(backend_ref, muted))?;
            write_envelope_to(
                output,
                &WorkerEnvelope::result(
                    "voip.set_mute",
                    envelope.request_id,
                    json!({"muted": muted}),
                ),
            )?;
            write_session_snapshot(host, output)?;
        }
        "voip.send_text_message" => {
            let uri = envelope.payload["uri"].as_str().unwrap_or("").trim();
            let text = envelope.payload["text"].as_str().unwrap_or("");
            let client_id = envelope.payload["client_id"].as_str().unwrap_or("").trim();
            if uri.is_empty() || text.is_empty() || client_id.is_empty() {
                write_envelope_to(
                    output,
                    &WorkerEnvelope::error(
                        "voip.error",
                        envelope.request_id,
                        "invalid_command",
                        "voip.send_text_message requires uri, text, and client_id",
                    ),
                )?;
            } else {
                let message_id = backend.with_backend(|backend_ref| {
                    host.send_text_message(backend_ref, uri, text, client_id)
                })?;
                write_envelope_to(
                    output,
                    &WorkerEnvelope::result(
                        "voip.send_text_message",
                        envelope.request_id,
                        json!({"message_id": message_id}),
                    ),
                )?;
                write_session_snapshot(host, output)?;
            }
        }
        "voip.start_voice_note_recording" => {
            let file_path = envelope.payload["file_path"].as_str().unwrap_or("").trim();
            if file_path.is_empty() {
                write_envelope_to(
                    output,
                    &WorkerEnvelope::error(
                        "voip.error",
                        envelope.request_id,
                        "invalid_command",
                        "voip.start_voice_note_recording requires file_path",
                    ),
                )?;
            } else {
                backend.with_backend(|backend_ref| {
                    host.start_voice_recording(backend_ref, file_path)
                })?;
                write_envelope_to(
                    output,
                    &WorkerEnvelope::result(
                        "voip.start_voice_note_recording",
                        envelope.request_id,
                        json!({"recording": true}),
                    ),
                )?;
                write_session_snapshot(host, output)?;
            }
        }
        "voip.stop_voice_note_recording" => {
            let duration_ms =
                backend.with_backend(|backend_ref| host.stop_voice_recording(backend_ref))?;
            write_envelope_to(
                output,
                &WorkerEnvelope::result(
                    "voip.stop_voice_note_recording",
                    envelope.request_id,
                    json!({"duration_ms": duration_ms}),
                ),
            )?;
            write_session_snapshot(host, output)?;
        }
        "voip.cancel_voice_note_recording" => {
            backend.with_backend(|backend_ref| host.cancel_voice_recording(backend_ref))?;
            write_envelope_to(
                output,
                &WorkerEnvelope::result(
                    "voip.cancel_voice_note_recording",
                    envelope.request_id,
                    json!({"cancelled": true}),
                ),
            )?;
            write_session_snapshot(host, output)?;
        }
        "voip.send_voice_note" => {
            let uri = envelope.payload["uri"].as_str().unwrap_or("").trim();
            let file_path = envelope.payload["file_path"].as_str().unwrap_or("").trim();
            let mime_type = envelope.payload["mime_type"].as_str().unwrap_or("").trim();
            let client_id = envelope.payload["client_id"].as_str().unwrap_or("").trim();
            let duration_ms = envelope.payload["duration_ms"].as_i64().unwrap_or(-1);
            if uri.is_empty()
                || file_path.is_empty()
                || mime_type.is_empty()
                || client_id.is_empty()
                || duration_ms < 0
                || duration_ms > i32::MAX as i64
            {
                write_envelope_to(output, &WorkerEnvelope::error(
                    "voip.error",
                    envelope.request_id,
                    "invalid_command",
                    "voip.send_voice_note requires uri, file_path, duration_ms, mime_type, and client_id",
                ))?;
            } else {
                let message_id = backend.with_backend(|backend_ref| {
                    host.send_voice_note(
                        backend_ref,
                        uri,
                        file_path,
                        duration_ms as i32,
                        mime_type,
                        client_id,
                    )
                })?;
                write_envelope_to(
                    output,
                    &WorkerEnvelope::result(
                        "voip.send_voice_note",
                        envelope.request_id,
                        json!({"message_id": message_id}),
                    ),
                )?;
                write_session_snapshot(host, output)?;
            }
        }
        "voip.mark_voice_notes_seen" => {
            let uri = envelope
                .payload
                .get("uri")
                .or_else(|| envelope.payload.get("sip_address"))
                .and_then(|value| value.as_str())
                .unwrap_or("")
                .trim();
            if uri.is_empty() {
                write_envelope_to(
                    output,
                    &WorkerEnvelope::error(
                        "voip.error",
                        envelope.request_id,
                        "invalid_command",
                        "voip.mark_voice_notes_seen requires uri",
                    ),
                )?;
            } else {
                host.mark_voice_notes_seen(uri)
                    .map_err(|error| anyhow!(error))?;
                write_envelope_to(
                    output,
                    &WorkerEnvelope::result(
                        "voip.mark_voice_notes_seen",
                        envelope.request_id,
                        json!({"marked_seen": true}),
                    ),
                )?;
                write_session_snapshot(host, output)?;
            }
        }
        "voip.mark_call_history_seen" => {
            let uri = envelope
                .payload
                .get("uri")
                .or_else(|| envelope.payload.get("sip_address"))
                .and_then(|value| value.as_str())
                .unwrap_or("")
                .trim();
            host.mark_call_history_seen(uri);
            write_envelope_to(
                output,
                &WorkerEnvelope::result(
                    "voip.mark_call_history_seen",
                    envelope.request_id,
                    json!({"marked_seen": true}),
                ),
            )?;
            write_session_snapshot(host, output)?;
        }
        "voip.play_voice_note" => {
            let file_path = envelope.payload["file_path"].as_str().unwrap_or("").trim();
            if file_path.is_empty() {
                write_envelope_to(
                    output,
                    &WorkerEnvelope::error(
                        "voip.error",
                        envelope.request_id,
                        "invalid_command",
                        "voip.play_voice_note requires file_path",
                    ),
                )?;
            } else {
                host.play_voice_note(file_path)
                    .map_err(|error| anyhow!(error))?;
                write_envelope_to(
                    output,
                    &WorkerEnvelope::result(
                        "voip.play_voice_note",
                        envelope.request_id,
                        json!({"playing": true}),
                    ),
                )?;
                write_session_snapshot(host, output)?;
            }
        }
        "voip.stop_voice_note_playback" => {
            host.stop_voice_note_playback();
            write_envelope_to(
                output,
                &WorkerEnvelope::result(
                    "voip.stop_voice_note_playback",
                    envelope.request_id,
                    json!({"stopped": true}),
                ),
            )?;
            write_session_snapshot(host, output)?;
        }
        "voip.shutdown" | "worker.stop" => {
            backend.unregister(host);
            write_envelope_to(
                output,
                &WorkerEnvelope::result(
                    envelope.message_type,
                    envelope.request_id,
                    json!({"shutdown": true}),
                ),
            )?;
            write_lifecycle_events(host, output)?;
            write_session_snapshot(host, output)?;
            return Ok(LoopAction::Shutdown);
        }
        _ => {
            write_envelope_to(
                output,
                &WorkerEnvelope::error(
                    "voip.error",
                    envelope.request_id,
                    "unsupported_command",
                    format!("unsupported command {}", envelope.message_type),
                ),
            )?;
        }
    }

    Ok(LoopAction::Continue)
}

fn poll_worker_backend<S, W>(host: &mut VoipHost, backend: &mut S, output: &mut W) -> Result<()>
where
    S: WorkerBackendState,
    W: Write + ?Sized,
{
    if backend.is_running() {
        let events = backend.with_backend(|backend_ref| host.poll_backend_events(backend_ref))?;
        let lifecycle_events = host.take_lifecycle_events();
        emit_backend_events(events, lifecycle_events, host, output)?;
    }
    Ok(())
}

fn emit_backend_events<W: Write + ?Sized>(
    events: Vec<host::BackendEvent>,
    lifecycle_events: Vec<host::LifecycleEvent>,
    host: &VoipHost,
    output: &mut W,
) -> Result<()> {
    for envelope in backend_event_envelopes(events, lifecycle_events, host) {
        write_envelope_to(output, &envelope)?;
    }
    Ok(())
}

pub fn backend_event_envelopes(
    events: Vec<host::BackendEvent>,
    lifecycle_events: Vec<host::LifecycleEvent>,
    host: &VoipHost,
) -> Vec<WorkerEnvelope> {
    if events.is_empty() && lifecycle_events.is_empty() {
        return Vec::new();
    }
    let mut envelopes: Vec<WorkerEnvelope> =
        events.into_iter().map(backend_event_envelope).collect();
    envelopes.extend(lifecycle_events.into_iter().map(lifecycle_event_envelope));
    envelopes.push(session_snapshot_envelope(host));
    envelopes
}

fn write_lifecycle_events<W: Write + ?Sized>(host: &mut VoipHost, output: &mut W) -> Result<()> {
    for event in host.take_lifecycle_events() {
        write_envelope_to(output, &lifecycle_event_envelope(event))?;
    }
    Ok(())
}

fn lifecycle_event_envelope(event: host::LifecycleEvent) -> WorkerEnvelope {
    WorkerEnvelope::event(
        "voip.lifecycle_changed",
        json!({
            "state": event.state,
            "previous_state": event.previous_state,
            "reason": event.reason,
            "recovered": event.recovered,
        }),
    )
}

fn write_session_snapshot<W: Write + ?Sized>(host: &VoipHost, output: &mut W) -> Result<()> {
    write_envelope_to(output, &session_snapshot_envelope(host))
}

fn session_snapshot_envelope(host: &VoipHost) -> WorkerEnvelope {
    WorkerEnvelope::event("voip.snapshot", host.session_snapshot_payload())
}

pub fn backend_event_envelope(event: host::BackendEvent) -> WorkerEnvelope {
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
        host::BackendEvent::MessageReceived { message } => WorkerEnvelope::event(
            "voip.message_received",
            json!({
                "message_id": message.message_id,
                "peer_sip_address": message.peer_sip_address,
                "sender_sip_address": message.sender_sip_address,
                "recipient_sip_address": message.recipient_sip_address,
                "kind": message.kind,
                "direction": message.direction,
                "delivery_state": message.delivery_state,
                "text": message.text,
                "local_file_path": message.local_file_path,
                "mime_type": message.mime_type,
                "duration_ms": message.duration_ms,
                "unread": message.unread,
                "display_name": "",
            }),
        ),
        host::BackendEvent::MessageDeliveryChanged {
            message_id,
            delivery_state,
            local_file_path,
            error,
        } => WorkerEnvelope::event(
            "voip.message_delivery_changed",
            json!({
                "message_id": message_id,
                "delivery_state": delivery_state,
                "local_file_path": local_file_path,
                "error": error,
            }),
        ),
        host::BackendEvent::MessageDownloadCompleted {
            message_id,
            local_file_path,
            mime_type,
        } => WorkerEnvelope::event(
            "voip.message_download_completed",
            json!({
                "message_id": message_id,
                "local_file_path": local_file_path,
                "mime_type": mime_type,
            }),
        ),
        host::BackendEvent::MessageFailed { message_id, reason } => WorkerEnvelope::event(
            "voip.message_failed",
            json!({"message_id": message_id, "reason": reason}),
        ),
    }
}

fn write_envelope_to<W: Write + ?Sized>(output: &mut W, envelope: &WorkerEnvelope) -> Result<()> {
    let encoded = envelope.encode()?;
    output.write_all(&encoded)?;
    output.flush()?;
    Ok(())
}
