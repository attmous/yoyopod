use anyhow::{anyhow, Result};
use serde_json::json;
use std::io::{self, BufRead, Write};
use std::sync::mpsc::{self, RecvTimeoutError};
use std::sync::{Mutex, OnceLock};
use std::time::Duration;

#[cfg(unix)]
use std::fs::File;
#[cfg(unix)]
use std::os::fd::FromRawFd;
#[cfg(unix)]
use std::os::raw::c_int;

use crate::config::VoipConfig;
use crate::host::{self, VoipHost};
use crate::protocol::WorkerEnvelope;
use crate::shim;

pub fn run(explicit_shim_path: Option<&str>) -> Result<()> {
    init_protocol_stdout()?;
    let mut host = VoipHost::default();
    let mut backend: Option<shim::ShimBackend> = None;

    write_envelope(&WorkerEnvelope::event(
        "voip.ready",
        json!({"capabilities":["calls", "text_messages", "voice_notes"]}),
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
                    match handle_command(envelope, &mut host, &mut backend, explicit_shim_path) {
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

pub enum LoopAction {
    Continue,
    Shutdown,
}

pub fn handle_command(
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
            write_lifecycle_events(host)?;
            write_session_snapshot(host)?;
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
            if let Err(error) = host.register(backend_ref) {
                write_lifecycle_events(host)?;
                write_session_snapshot(host)?;
                return Err(anyhow!(error));
            }
            write_envelope(&WorkerEnvelope::result(
                "voip.register",
                envelope.request_id,
                json!({"registered": true}),
            ))?;
            write_lifecycle_events(host)?;
            write_session_snapshot(host)?;
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
            write_lifecycle_events(host)?;
            write_session_snapshot(host)?;
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
                write_session_snapshot(host)?;
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
            write_session_snapshot(host)?;
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
            write_session_snapshot(host)?;
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
            write_session_snapshot(host)?;
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
            write_session_snapshot(host)?;
        }
        "voip.send_text_message" => {
            let uri = envelope.payload["uri"].as_str().unwrap_or("").trim();
            let text = envelope.payload["text"].as_str().unwrap_or("");
            let client_id = envelope.payload["client_id"].as_str().unwrap_or("").trim();
            if uri.is_empty() || text.is_empty() || client_id.is_empty() {
                write_envelope(&WorkerEnvelope::error(
                    "voip.error",
                    envelope.request_id,
                    "invalid_command",
                    "voip.send_text_message requires uri, text, and client_id",
                ))?;
            } else {
                let backend_ref = backend
                    .as_mut()
                    .ok_or_else(|| anyhow!("voip host is not registered"))?;
                let message_id = host
                    .send_text_message(backend_ref, uri, text, client_id)
                    .map_err(|error| anyhow!(error))?;
                write_envelope(&WorkerEnvelope::result(
                    "voip.send_text_message",
                    envelope.request_id,
                    json!({"message_id": message_id}),
                ))?;
                write_session_snapshot(host)?;
            }
        }
        "voip.start_voice_note_recording" => {
            let file_path = envelope.payload["file_path"].as_str().unwrap_or("").trim();
            if file_path.is_empty() {
                write_envelope(&WorkerEnvelope::error(
                    "voip.error",
                    envelope.request_id,
                    "invalid_command",
                    "voip.start_voice_note_recording requires file_path",
                ))?;
            } else {
                let backend_ref = backend
                    .as_mut()
                    .ok_or_else(|| anyhow!("voip host is not registered"))?;
                host.start_voice_recording(backend_ref, file_path)
                    .map_err(|error| anyhow!(error))?;
                write_envelope(&WorkerEnvelope::result(
                    "voip.start_voice_note_recording",
                    envelope.request_id,
                    json!({"recording": true}),
                ))?;
                write_session_snapshot(host)?;
            }
        }
        "voip.stop_voice_note_recording" => {
            let backend_ref = backend
                .as_mut()
                .ok_or_else(|| anyhow!("voip host is not registered"))?;
            let duration_ms = host
                .stop_voice_recording(backend_ref)
                .map_err(|error| anyhow!(error))?;
            write_envelope(&WorkerEnvelope::result(
                "voip.stop_voice_note_recording",
                envelope.request_id,
                json!({"duration_ms": duration_ms}),
            ))?;
            write_session_snapshot(host)?;
        }
        "voip.cancel_voice_note_recording" => {
            let backend_ref = backend
                .as_mut()
                .ok_or_else(|| anyhow!("voip host is not registered"))?;
            host.cancel_voice_recording(backend_ref)
                .map_err(|error| anyhow!(error))?;
            write_envelope(&WorkerEnvelope::result(
                "voip.cancel_voice_note_recording",
                envelope.request_id,
                json!({"cancelled": true}),
            ))?;
            write_session_snapshot(host)?;
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
                write_envelope(&WorkerEnvelope::error(
                    "voip.error",
                    envelope.request_id,
                    "invalid_command",
                    "voip.send_voice_note requires uri, file_path, duration_ms, mime_type, and client_id",
                ))?;
            } else {
                let backend_ref = backend
                    .as_mut()
                    .ok_or_else(|| anyhow!("voip host is not registered"))?;
                let message_id = host
                    .send_voice_note(
                        backend_ref,
                        uri,
                        file_path,
                        duration_ms as i32,
                        mime_type,
                        client_id,
                    )
                    .map_err(|error| anyhow!(error))?;
                write_envelope(&WorkerEnvelope::result(
                    "voip.send_voice_note",
                    envelope.request_id,
                    json!({"message_id": message_id}),
                ))?;
                write_session_snapshot(host)?;
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
                write_envelope(&WorkerEnvelope::error(
                    "voip.error",
                    envelope.request_id,
                    "invalid_command",
                    "voip.mark_voice_notes_seen requires uri",
                ))?;
            } else {
                host.mark_voice_notes_seen(uri)
                    .map_err(|error| anyhow!(error))?;
                write_envelope(&WorkerEnvelope::result(
                    "voip.mark_voice_notes_seen",
                    envelope.request_id,
                    json!({"marked_seen": true}),
                ))?;
                write_session_snapshot(host)?;
            }
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
            write_lifecycle_events(host)?;
            write_session_snapshot(host)?;
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
        let events = host
            .poll_backend_events(backend_ref)
            .map_err(|error| anyhow!(error))?;
        let lifecycle_events = host.take_lifecycle_events();
        emit_backend_events(events, lifecycle_events, host)?;
    }
    Ok(())
}

fn emit_backend_events(
    events: Vec<host::BackendEvent>,
    lifecycle_events: Vec<host::LifecycleEvent>,
    host: &VoipHost,
) -> Result<()> {
    for envelope in backend_event_envelopes(events, lifecycle_events, host) {
        write_envelope(&envelope)?;
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

fn write_lifecycle_events(host: &mut VoipHost) -> Result<()> {
    for event in host.take_lifecycle_events() {
        write_envelope(&lifecycle_event_envelope(event))?;
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

fn write_session_snapshot(host: &VoipHost) -> Result<()> {
    write_envelope(&session_snapshot_envelope(host))
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

fn write_envelope(envelope: &WorkerEnvelope) -> Result<()> {
    let encoded = envelope.encode()?;
    let output = protocol_stdout();
    let mut output = output
        .lock()
        .map_err(|_| anyhow!("protocol stdout lock poisoned"))?;
    output.write_all(&encoded)?;
    output.flush()?;
    Ok(())
}

static PROTOCOL_STDOUT: OnceLock<Mutex<Box<dyn Write + Send>>> = OnceLock::new();

fn init_protocol_stdout() -> Result<()> {
    PROTOCOL_STDOUT
        .set(Mutex::new(capture_protocol_stdout()?))
        .map_err(|_| anyhow!("protocol stdout already initialized"))?;
    Ok(())
}

fn protocol_stdout() -> &'static Mutex<Box<dyn Write + Send>> {
    PROTOCOL_STDOUT.get_or_init(|| Mutex::new(default_protocol_stdout()))
}

fn default_protocol_stdout() -> Box<dyn Write + Send> {
    Box::new(io::stdout())
}

#[cfg(unix)]
fn capture_protocol_stdout() -> io::Result<Box<dyn Write + Send>> {
    const STDOUT_FILENO: c_int = 1;
    const STDERR_FILENO: c_int = 2;

    extern "C" {
        fn close(fd: c_int) -> c_int;
        fn dup(fd: c_int) -> c_int;
        fn dup2(oldfd: c_int, newfd: c_int) -> c_int;
    }

    let protocol_fd = unsafe { dup(STDOUT_FILENO) };
    if protocol_fd < 0 {
        return Err(io::Error::last_os_error());
    }

    if unsafe { dup2(STDERR_FILENO, STDOUT_FILENO) } < 0 {
        let error = io::Error::last_os_error();
        unsafe {
            close(protocol_fd);
        }
        return Err(error);
    }

    let protocol_file = unsafe { File::from_raw_fd(protocol_fd) };
    Ok(Box::new(protocol_file))
}

#[cfg(not(unix))]
fn capture_protocol_stdout() -> io::Result<Box<dyn Write + Send>> {
    Ok(default_protocol_stdout())
}
