use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use crate::protocol::{EnvelopeKind, WorkerEnvelope};
use crate::state::{CallState, RuntimeState, WorkerDomain, WorkerState};

#[derive(Debug, Clone, PartialEq)]
pub enum RuntimeEvent {
    WorkerReady {
        domain: WorkerDomain,
    },
    CloudSnapshot(Value),
    CloudCommand(Value),
    MediaSnapshot(Value),
    VoipSnapshot(Value),
    NetworkSnapshot(Value),
    UiInput(Value),
    UiIntent {
        domain: String,
        action: String,
        payload: Value,
    },
    UiScreenChanged {
        screen: String,
    },
    WorkerError {
        domain: WorkerDomain,
        message: String,
    },
    WorkerExited {
        domain: WorkerDomain,
        reason: String,
    },
    Shutdown,
    Ignored,
}

#[derive(Debug, Clone, PartialEq)]
pub enum RuntimeCommand {
    WorkerCommand {
        domain: WorkerDomain,
        envelope: WorkerEnvelope,
    },
    WorkerCommandWithAck {
        domain: WorkerDomain,
        envelope: WorkerEnvelope,
        success_ack: WorkerEnvelope,
        failure_ack: WorkerEnvelope,
    },
    Shutdown,
}

impl RuntimeEvent {
    pub fn apply(&self, state: &mut RuntimeState) {
        match self {
            Self::WorkerReady { domain } => {
                state.mark_worker(*domain, WorkerState::Running, "ready");
            }
            Self::CloudSnapshot(snapshot) => state.apply_cloud_snapshot(snapshot),
            Self::CloudCommand(_) => {}
            Self::MediaSnapshot(snapshot) => state.apply_media_snapshot(snapshot),
            Self::VoipSnapshot(snapshot) => state.apply_voip_snapshot(snapshot),
            Self::NetworkSnapshot(snapshot) => state.apply_network_snapshot(snapshot),
            Self::UiScreenChanged { screen } => {
                state.current_screen = screen.clone();
            }
            Self::WorkerError { domain, message } => {
                state.mark_worker(*domain, WorkerState::Degraded, message.clone());
            }
            Self::WorkerExited { domain, reason } => {
                state.mark_worker(*domain, WorkerState::Stopped, reason.clone());
            }
            Self::UiIntent {
                domain,
                action,
                payload,
            } => state.apply_ui_intent(domain, action, payload),
            Self::UiInput(_) | Self::Shutdown | Self::Ignored => {}
        }
    }
}

pub fn runtime_event_from_worker(
    domain: WorkerDomain,
    envelope: WorkerEnvelope,
) -> Option<RuntimeEvent> {
    let WorkerEnvelope {
        kind,
        message_type,
        payload,
        ..
    } = envelope;

    match kind {
        EnvelopeKind::Error => Some(RuntimeEvent::WorkerError {
            domain,
            message: worker_error_message(&message_type, &payload),
        }),
        EnvelopeKind::Event => Some(runtime_event_from_message(domain, &message_type, payload)),
        EnvelopeKind::Result
            if domain == WorkerDomain::Network
                && matches!(message_type.as_str(), "network.snapshot" | "network.health") =>
        {
            Some(RuntimeEvent::NetworkSnapshot(payload))
        }
        EnvelopeKind::Command | EnvelopeKind::Result | EnvelopeKind::Heartbeat => {
            Some(RuntimeEvent::Ignored)
        }
    }
}

pub fn commands_for_event(state: &RuntimeState, event: &RuntimeEvent) -> Vec<RuntimeCommand> {
    match event {
        RuntimeEvent::UiIntent {
            domain,
            action,
            payload,
        } => commands_for_ui_intent(state, domain, action, payload),
        RuntimeEvent::UiInput(payload) => commands_for_ui_input(state, payload),
        RuntimeEvent::CloudCommand(command) => commands_for_cloud_command(command),
        RuntimeEvent::MediaSnapshot(snapshot) => commands_for_media_snapshot(snapshot),
        RuntimeEvent::VoipSnapshot(snapshot) => commands_for_voip_snapshot(state, snapshot),
        RuntimeEvent::NetworkSnapshot(snapshot) => commands_for_network_snapshot(snapshot),
        RuntimeEvent::Shutdown => vec![RuntimeCommand::Shutdown],
        RuntimeEvent::WorkerReady { .. }
        | RuntimeEvent::CloudSnapshot(_)
        | RuntimeEvent::UiScreenChanged { .. }
        | RuntimeEvent::WorkerError { .. }
        | RuntimeEvent::WorkerExited { .. }
        | RuntimeEvent::Ignored => Vec::new(),
    }
}

fn runtime_event_from_message(
    domain: WorkerDomain,
    message_type: &str,
    payload: Value,
) -> RuntimeEvent {
    if message_type == "worker.exited" {
        return RuntimeEvent::WorkerExited {
            domain,
            reason: worker_exit_reason(&payload),
        };
    }

    match domain {
        WorkerDomain::Ui => ui_event_from_message(message_type, payload),
        WorkerDomain::Cloud => cloud_event_from_message(message_type, payload),
        WorkerDomain::Media => media_event_from_message(message_type, payload),
        WorkerDomain::Voip => voip_event_from_message(message_type, payload),
        WorkerDomain::Network => network_event_from_message(message_type, payload),
        WorkerDomain::Power => health_only_event_from_message(
            domain,
            message_type,
            &payload,
            "power.ready",
            "power.error",
        ),
        WorkerDomain::Voice => health_only_event_from_message(
            domain,
            message_type,
            &payload,
            "voice.ready",
            "voice.error",
        ),
    }
}

fn cloud_event_from_message(message_type: &str, payload: Value) -> RuntimeEvent {
    match message_type {
        "cloud.ready" => RuntimeEvent::WorkerReady {
            domain: WorkerDomain::Cloud,
        },
        "cloud.snapshot" | "cloud.health" => RuntimeEvent::CloudSnapshot(payload),
        "cloud.command" => payload
            .get("command")
            .cloned()
            .map(RuntimeEvent::CloudCommand)
            .unwrap_or(RuntimeEvent::Ignored),
        "cloud.error" => RuntimeEvent::WorkerError {
            domain: WorkerDomain::Cloud,
            message: worker_error_message(message_type, &payload),
        },
        _ => RuntimeEvent::Ignored,
    }
}

fn ui_event_from_message(message_type: &str, payload: Value) -> RuntimeEvent {
    match message_type {
        "ui.ready" => RuntimeEvent::WorkerReady {
            domain: WorkerDomain::Ui,
        },
        "ui.input" => RuntimeEvent::UiInput(payload),
        "ui.intent" => runtime_intent_from_payload(payload),
        "ui.screen_changed" => string_field(&payload, "screen")
            .map(|screen| RuntimeEvent::UiScreenChanged { screen })
            .unwrap_or(RuntimeEvent::Ignored),
        "ui.error" => RuntimeEvent::WorkerError {
            domain: WorkerDomain::Ui,
            message: worker_error_message(message_type, &payload),
        },
        _ => RuntimeEvent::Ignored,
    }
}

fn media_event_from_message(message_type: &str, payload: Value) -> RuntimeEvent {
    match message_type {
        "media.ready" => RuntimeEvent::WorkerReady {
            domain: WorkerDomain::Media,
        },
        "media.snapshot" => RuntimeEvent::MediaSnapshot(payload),
        "media.error" => RuntimeEvent::WorkerError {
            domain: WorkerDomain::Media,
            message: worker_error_message(message_type, &payload),
        },
        _ => RuntimeEvent::Ignored,
    }
}

fn voip_event_from_message(message_type: &str, payload: Value) -> RuntimeEvent {
    match message_type {
        "voip.ready" => RuntimeEvent::WorkerReady {
            domain: WorkerDomain::Voip,
        },
        "voip.snapshot" => RuntimeEvent::VoipSnapshot(payload),
        "voip.error" => RuntimeEvent::WorkerError {
            domain: WorkerDomain::Voip,
            message: worker_error_message(message_type, &payload),
        },
        _ => RuntimeEvent::Ignored,
    }
}

fn network_event_from_message(message_type: &str, payload: Value) -> RuntimeEvent {
    match message_type {
        "network.ready" => RuntimeEvent::WorkerReady {
            domain: WorkerDomain::Network,
        },
        "network.snapshot" | "network.health" => RuntimeEvent::NetworkSnapshot(payload),
        "network.error" => RuntimeEvent::WorkerError {
            domain: WorkerDomain::Network,
            message: worker_error_message(message_type, &payload),
        },
        _ => RuntimeEvent::Ignored,
    }
}

fn health_only_event_from_message(
    domain: WorkerDomain,
    message_type: &str,
    payload: &Value,
    ready_type: &str,
    error_type: &str,
) -> RuntimeEvent {
    if message_type == ready_type {
        return RuntimeEvent::WorkerReady { domain };
    }
    if message_type == error_type {
        return RuntimeEvent::WorkerError {
            domain,
            message: worker_error_message(message_type, payload),
        };
    }

    RuntimeEvent::Ignored
}

fn runtime_intent_from_payload(payload: Value) -> RuntimeEvent {
    let Some(domain) = string_field(&payload, "domain") else {
        return RuntimeEvent::Ignored;
    };
    let Some(action) = string_field(&payload, "action") else {
        return RuntimeEvent::Ignored;
    };
    if normalized(&domain) == "runtime" && normalized(&action) == "shutdown" {
        return RuntimeEvent::Shutdown;
    }
    let payload = payload
        .get("payload")
        .cloned()
        .unwrap_or_else(empty_payload);

    RuntimeEvent::UiIntent {
        domain,
        action,
        payload,
    }
}

fn commands_for_ui_intent(
    state: &RuntimeState,
    domain: &str,
    action: &str,
    payload: &Value,
) -> Vec<RuntimeCommand> {
    let domain = normalized(domain);
    let action = normalized(action);

    match domain.as_str() {
        "music" => commands_for_music_intent(state, &action, payload),
        "call" => commands_for_call_intent(state, &action, payload),
        "voice" => commands_for_voice_intent(state, &action, payload),
        _ => Vec::new(),
    }
}

fn commands_for_music_intent(
    state: &RuntimeState,
    action: &str,
    payload: &Value,
) -> Vec<RuntimeCommand> {
    match action {
        "play_pause" => {
            let message_type = match normalized(&state.media.playback_state).as_str() {
                "playing" => "media.pause",
                "paused" => "media.resume",
                _ => "media.play",
            };
            vec![worker_command(
                WorkerDomain::Media,
                message_type,
                empty_payload(),
            )]
        }
        "next" | "next_track" => vec![worker_command(
            WorkerDomain::Media,
            "media.next_track",
            empty_payload(),
        )],
        "previous" | "previous_track" => vec![worker_command(
            WorkerDomain::Media,
            "media.previous_track",
            empty_payload(),
        )],
        "shuffle_all" => vec![worker_command(
            WorkerDomain::Media,
            "media.shuffle_all",
            empty_payload(),
        )],
        "load_playlist" => string_field(payload, "id")
            .or_else(|| string_field(payload, "path"))
            .map(|path| {
                vec![worker_command(
                    WorkerDomain::Media,
                    "media.load_playlist",
                    json!({ "path": path }),
                )]
            })
            .unwrap_or_default(),
        "play_recent_track" => string_field(payload, "id")
            .or_else(|| string_field(payload, "track_uri"))
            .map(|track_uri| {
                vec![worker_command(
                    WorkerDomain::Media,
                    "media.play_recent_track",
                    json!({ "track_uri": track_uri }),
                )]
            })
            .unwrap_or_default(),
        _ => Vec::new(),
    }
}

fn commands_for_call_intent(
    state: &RuntimeState,
    action: &str,
    payload: &Value,
) -> Vec<RuntimeCommand> {
    match action {
        "answer" => vec![worker_command(
            WorkerDomain::Voip,
            "voip.answer",
            empty_payload(),
        )],
        "hangup" => vec![worker_command(
            WorkerDomain::Voip,
            "voip.hangup",
            empty_payload(),
        )],
        "reject" => vec![worker_command(
            WorkerDomain::Voip,
            "voip.reject",
            empty_payload(),
        )],
        "toggle_mute" => vec![worker_command(
            WorkerDomain::Voip,
            "voip.set_mute",
            json!({ "muted": !state.call.muted }),
        )],
        "start" => string_field(payload, "id")
            .or_else(|| string_field(payload, "sip_address"))
            .or_else(|| string_field(payload, "uri"))
            .map(|uri| {
                vec![worker_command(
                    WorkerDomain::Voip,
                    "voip.dial",
                    json!({ "uri": uri }),
                )]
            })
            .unwrap_or_default(),
        _ => Vec::new(),
    }
}

fn commands_for_voice_intent(
    state: &RuntimeState,
    action: &str,
    payload: &Value,
) -> Vec<RuntimeCommand> {
    match action {
        "capture_start" | "start_recording" => {
            let file_path = state.voice.recording_file_path();
            vec![worker_command(
                WorkerDomain::Voip,
                "voip.start_voice_note_recording",
                json!({ "file_path": file_path }),
            )]
        }
        "capture_stop" | "stop_recording" => vec![worker_command(
            WorkerDomain::Voip,
            "voip.stop_voice_note_recording",
            empty_payload(),
        )],
        "capture_cancel" | "cancel_recording" => vec![worker_command(
            WorkerDomain::Voip,
            "voip.cancel_voice_note_recording",
            empty_payload(),
        )],
        "capture_toggle" => {
            if state.voice.phase == "recording" {
                commands_for_voice_intent(state, "capture_stop", payload)
            } else {
                commands_for_voice_intent(state, "capture_start", payload)
            }
        }
        "send" | "send_voice_note" => {
            let uri = string_field(payload, "recipient_address")
                .or_else(|| string_field(payload, "sip_address"))
                .or_else(|| string_field(payload, "id"))
                .or_else(|| string_field(payload, "uri"));
            let file_path = string_field(payload, "file_path")
                .or_else(|| non_empty_string(&state.voice.file_path));
            let Some(uri) = uri else {
                return Vec::new();
            };
            let Some(file_path) = file_path else {
                return Vec::new();
            };
            vec![worker_command(
                WorkerDomain::Voip,
                "voip.send_voice_note",
                json!({
                    "uri": uri,
                    "file_path": file_path,
                    "duration_ms": state.voice.duration_ms.max(0),
                    "mime_type": non_empty_string(&state.voice.mime_type)
                        .unwrap_or_else(|| "audio/wav".to_string()),
                    "client_id": new_voice_note_client_id(),
                }),
            )]
        }
        "play" | "play_voice_note" => string_field(payload, "file_path")
            .or_else(|| non_empty_string(&state.voice.file_path))
            .map(|file_path| {
                vec![worker_command(
                    WorkerDomain::Voip,
                    "voip.play_voice_note",
                    json!({ "file_path": file_path }),
                )]
            })
            .unwrap_or_default(),
        "play_latest" => {
            let Some(file_path) = string_field(payload, "file_path") else {
                return Vec::new();
            };
            let mut commands = vec![worker_command(
                WorkerDomain::Voip,
                "voip.play_voice_note",
                json!({ "file_path": file_path }),
            )];
            if let Some(uri) = string_field(payload, "id")
                .or_else(|| string_field(payload, "uri"))
                .or_else(|| string_field(payload, "sip_address"))
            {
                commands.push(worker_command(
                    WorkerDomain::Voip,
                    "voip.mark_voice_notes_seen",
                    json!({ "uri": uri }),
                ));
            }
            commands
        }
        "stop_playback" => vec![worker_command(
            WorkerDomain::Voip,
            "voip.stop_voice_note_playback",
            empty_payload(),
        )],
        "mark_seen" => string_field(payload, "id")
            .or_else(|| string_field(payload, "uri"))
            .or_else(|| string_field(payload, "sip_address"))
            .map(|uri| {
                vec![worker_command(
                    WorkerDomain::Voip,
                    "voip.mark_voice_notes_seen",
                    json!({ "uri": uri }),
                )]
            })
            .unwrap_or_default(),
        "discard" | "again" | "reset" => Vec::new(),
        _ => Vec::new(),
    }
}

fn commands_for_ui_input(state: &RuntimeState, payload: &Value) -> Vec<RuntimeCommand> {
    if state.call.state == CallState::Incoming
        && string_field(payload, "action")
            .as_deref()
            .is_some_and(|action| normalized(action) == "select")
    {
        return vec![worker_command(
            WorkerDomain::Voip,
            "voip.answer",
            empty_payload(),
        )];
    }

    Vec::new()
}

fn commands_for_cloud_command(command: &Value) -> Vec<RuntimeCommand> {
    let command_type = string_field(command, "command")
        .or_else(|| string_field(command, "type"))
        .unwrap_or_default();
    let command_id =
        string_field(command, "commandId").or_else(|| string_field(command, "command_id"));

    match normalized(&command_type).as_str() {
        "pause" => remote_media_control("media.pause", command_id, "pause"),
        "resume" => remote_media_control("media.resume", command_id, "resume"),
        "stop" => remote_media_control("media.stop_playback", command_id, "stop"),
        "fetch_config" => Vec::new(),
        "play_track" | "store_media" => command_id
            .map(|command_id| {
                vec![worker_command(
                    WorkerDomain::Cloud,
                    "cloud.ack",
                    json!({
                        "command_id": command_id,
                        "ok": false,
                        "reason": "unsupported_command",
                        "payload": {
                            "command": command_type.clone(),
                            "rust_runtime": true
                        }
                    }),
                )]
            })
            .unwrap_or_default(),
        _ if !command_type.trim().is_empty() => command_id
            .map(|command_id| {
                vec![worker_command(
                    WorkerDomain::Cloud,
                    "cloud.ack",
                    json!({
                        "command_id": command_id,
                        "ok": false,
                        "reason": "unsupported_command",
                        "payload": {"command": command_type.clone()}
                    }),
                )]
            })
            .unwrap_or_default(),
        _ => Vec::new(),
    }
}

fn remote_media_control(
    media_message_type: &str,
    command_id: Option<String>,
    command_type: &str,
) -> Vec<RuntimeCommand> {
    let media_command = WorkerEnvelope::command(media_message_type, None, empty_payload());
    let Some(command_id) = command_id else {
        return vec![RuntimeCommand::WorkerCommand {
            domain: WorkerDomain::Media,
            envelope: media_command,
        }];
    };

    vec![RuntimeCommand::WorkerCommandWithAck {
        domain: WorkerDomain::Media,
        envelope: media_command,
        success_ack: WorkerEnvelope::command(
            "cloud.ack",
            None,
            json!({
                "command_id": command_id,
                "ok": true,
                "payload": {"command": command_type}
            }),
        ),
        failure_ack: WorkerEnvelope::command(
            "cloud.ack",
            None,
            json!({
                "command_id": command_id,
                "ok": false,
                "reason": "media_dispatch_failed",
                "payload": {
                    "command": command_type,
                    "media_command": media_message_type
                }
            }),
        ),
    }]
}

fn commands_for_media_snapshot(snapshot: &Value) -> Vec<RuntimeCommand> {
    let playback_state =
        string_field(snapshot, "playback_state").unwrap_or_else(|| "stopped".to_string());
    let mut attrs = json!({
        "playback_state": playback_state.clone(),
    });
    if let Some(track) = snapshot.get("current_track") {
        attrs["track"] = track.clone();
    }
    vec![cloud_telemetry_command(
        "music.state",
        json!({
            "entity": "music.state",
            "value": playback_state,
            "attrs": attrs,
            "ts": current_epoch_seconds(),
        }),
    )]
}

fn commands_for_voip_snapshot(state: &RuntimeState, snapshot: &Value) -> Vec<RuntimeCommand> {
    let mut commands = Vec::new();
    let call_state = string_field(snapshot, "call_state").unwrap_or_else(|| "idle".to_string());
    commands.push(cloud_telemetry_command(
        "call.state",
        json!({
            "entity": "call.state",
            "value": call_state,
            "attrs": snapshot,
            "ts": current_epoch_seconds(),
        }),
    ));
    if !is_music_playing(state) {
        return commands;
    }

    let mut snapshot_state = RuntimeState::default();
    snapshot_state.apply_voip_snapshot(snapshot);
    if matches!(
        snapshot_state.call.state,
        CallState::Incoming | CallState::Outgoing | CallState::Active
    ) {
        commands.push(worker_command(
            WorkerDomain::Media,
            "media.pause",
            empty_payload(),
        ));
    }

    commands
}

fn commands_for_network_snapshot(snapshot: &Value) -> Vec<RuntimeCommand> {
    let snapshot = snapshot.get("snapshot").unwrap_or(snapshot);
    let app_state = snapshot.get("app_state").unwrap_or(snapshot);
    let connected = app_state
        .get("connected")
        .or_else(|| snapshot.get("connected"))
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let connection_type = string_field(app_state, "connection_type")
        .or_else(|| string_field(snapshot, "connection_type"))
        .unwrap_or_else(|| "none".to_string());
    let signal_bars = app_state
        .get("signal_bars")
        .or_else(|| app_state.get("signal_strength"))
        .and_then(Value::as_i64)
        .or_else(|| {
            snapshot
                .get("signal")
                .and_then(|signal| signal.get("bars"))
                .and_then(Value::as_i64)
        })
        .unwrap_or(0)
        .clamp(0, 4);
    let gps_has_fix = app_state
        .get("gps_has_fix")
        .or_else(|| snapshot.get("gps_has_fix"))
        .and_then(Value::as_bool)
        .unwrap_or(false);

    let mut commands = vec![
        cloud_telemetry_command(
            "network.ppp_up",
            json!({
                "entity": "network.ppp_up",
                "value": connected,
                "attrs": {
                    "connection_type": connection_type.clone(),
                },
                "ts": current_epoch_seconds(),
            }),
        ),
        cloud_telemetry_command(
            "network.signal_bars",
            json!({
                "entity": "network.signal_bars",
                "value": signal_bars,
                "attrs": {
                    "connection_type": connection_type.clone(),
                },
                "ts": current_epoch_seconds(),
            }),
        ),
        cloud_telemetry_command(
            "location.fix",
            json!({
                "entity": "location.fix",
                "value": gps_has_fix,
                "attrs": snapshot.get("gps").cloned().unwrap_or_else(empty_payload),
                "ts": current_epoch_seconds(),
            }),
        ),
    ];
    if connected && connection_type != "none" {
        commands.push(worker_command(
            WorkerDomain::Cloud,
            "cloud.publish_connectivity",
            json!({
                "connection_type": connection_type,
            }),
        ));
    }
    commands
}

fn worker_command(
    domain: WorkerDomain,
    message_type: impl Into<String>,
    payload: Value,
) -> RuntimeCommand {
    RuntimeCommand::WorkerCommand {
        domain,
        envelope: WorkerEnvelope::command(message_type, None, payload),
    }
}

fn cloud_telemetry_command(topic_suffix: &str, payload: Value) -> RuntimeCommand {
    worker_command(
        WorkerDomain::Cloud,
        "cloud.publish_telemetry",
        json!({
            "topic_suffix": topic_suffix,
            "payload": payload,
            "qos": 0,
        }),
    )
}

fn is_music_playing(state: &RuntimeState) -> bool {
    normalized(&state.media.playback_state) == "playing"
}

fn worker_error_message(message_type: &str, payload: &Value) -> String {
    string_field(payload, "message")
        .or_else(|| string_field(payload, "error"))
        .or_else(|| string_field(payload, "code"))
        .unwrap_or_else(|| message_type.to_string())
}

fn worker_exit_reason(payload: &Value) -> String {
    string_field(payload, "reason")
        .or_else(|| string_field(payload, "message"))
        .unwrap_or_else(|| "exited".to_string())
}

fn string_field(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn non_empty_string(value: &str) -> Option<String> {
    let value = value.trim();
    if value.is_empty() {
        None
    } else {
        Some(value.to_string())
    }
}

fn new_voice_note_client_id() -> String {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default();
    format!("runtime-vn-{}-{millis}", std::process::id())
}

fn current_epoch_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default()
}

fn normalized(value: &str) -> String {
    value.trim().to_ascii_lowercase()
}

fn empty_payload() -> Value {
    json!({})
}
