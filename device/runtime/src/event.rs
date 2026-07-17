use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};
use yoyopod_protocol::ui::{
    CallIntent, ContactAction, InputAction, ListItemAction, MusicIntent, PowerIntent,
    RuntimeIntent, UiCommand, UiEvent, UiInputEvent, UiIntent, UiScreen, UiScreenshotCaptured,
    VoiceFileAction, VoiceIntent, VoiceRecipientAction,
};

use crate::protocol::{EnvelopeKind, WorkerEnvelope};
use crate::state::{CallState, PowerSafetyAction, RuntimeState, WorkerDomain, WorkerState};
use crate::voice::{
    route_voice_transcript, VoiceCommandIntent, VoiceConfirmationResponse, VoiceRouteKind,
};

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
    PowerSnapshot(Value),
    VoiceTranscript(Value),
    VoiceAskResult(Value),
    VoiceSpeakResult(Value),
    UiInput(UiInputEvent),
    UiIntent(UiIntent),
    UiScreenChanged {
        screen: UiScreen,
    },
    UiScreenshotCaptured(UiScreenshotCaptured),
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
#[allow(clippy::large_enum_variant)]
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
    AppendAppLog {
        line: String,
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
            Self::PowerSnapshot(snapshot) => state.apply_power_snapshot(snapshot),
            Self::VoiceTranscript(snapshot) => state.apply_voice_transcript(snapshot),
            Self::VoiceAskResult(snapshot) => state.apply_voice_ask_result(snapshot),
            Self::VoiceSpeakResult(_) => {}
            Self::UiScreenChanged { screen } => {
                state.current_screen = *screen;
            }
            Self::WorkerError { domain, message } => {
                state.mark_worker(*domain, WorkerState::Degraded, message.clone());
            }
            Self::WorkerExited { domain, reason } => {
                state.mark_worker(*domain, WorkerState::Stopped, reason.clone());
            }
            Self::UiIntent(intent) => state.apply_ui_intent(intent),
            Self::UiInput(_) | Self::UiScreenshotCaptured(_) | Self::Shutdown | Self::Ignored => {}
        }
    }
}

pub fn runtime_event_from_worker(
    domain: WorkerDomain,
    envelope: WorkerEnvelope,
) -> Option<RuntimeEvent> {
    if domain == WorkerDomain::Ui {
        return Some(runtime_event_from_ui_envelope(envelope));
    }

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
        EnvelopeKind::Result
            if domain == WorkerDomain::Power
                && matches!(message_type.as_str(), "power.snapshot" | "power.health") =>
        {
            Some(RuntimeEvent::PowerSnapshot(payload))
        }
        EnvelopeKind::Result if domain == WorkerDomain::Voice => {
            Some(voice_event_from_message(&message_type, payload))
        }
        EnvelopeKind::Command | EnvelopeKind::Result | EnvelopeKind::Heartbeat => {
            Some(RuntimeEvent::Ignored)
        }
    }
}

fn runtime_event_from_ui_envelope(envelope: WorkerEnvelope) -> RuntimeEvent {
    if envelope.kind == EnvelopeKind::Error {
        return RuntimeEvent::WorkerError {
            domain: WorkerDomain::Ui,
            message: worker_error_message(&envelope.message_type, &envelope.payload),
        };
    }

    if envelope.kind != EnvelopeKind::Event {
        return RuntimeEvent::Ignored;
    }

    match UiEvent::from_envelope(envelope) {
        Ok(UiEvent::Ready(_)) => RuntimeEvent::WorkerReady {
            domain: WorkerDomain::Ui,
        },
        Ok(UiEvent::Input(input)) => RuntimeEvent::UiInput(input),
        Ok(UiEvent::Intent(intent)) => {
            if matches!(intent, UiIntent::Runtime(RuntimeIntent::Shutdown)) {
                RuntimeEvent::Shutdown
            } else {
                RuntimeEvent::UiIntent(intent)
            }
        }
        Ok(UiEvent::ScreenChanged(changed)) => RuntimeEvent::UiScreenChanged {
            screen: changed.screen,
        },
        Ok(UiEvent::ScreenshotCaptured(captured)) => RuntimeEvent::UiScreenshotCaptured(captured),
        Ok(UiEvent::Health(_)) => RuntimeEvent::Ignored,
        Ok(UiEvent::Error(error)) => RuntimeEvent::WorkerError {
            domain: WorkerDomain::Ui,
            message: error.message,
        },
        Ok(UiEvent::ShutdownComplete) => RuntimeEvent::WorkerExited {
            domain: WorkerDomain::Ui,
            reason: "shutdown_complete".to_string(),
        },
        Err(error) => RuntimeEvent::WorkerError {
            domain: WorkerDomain::Ui,
            message: error.to_string(),
        },
    }
}

pub fn commands_for_event(state: &RuntimeState, event: &RuntimeEvent) -> Vec<RuntimeCommand> {
    match event {
        RuntimeEvent::UiIntent(intent) => commands_for_ui_intent(state, intent),
        RuntimeEvent::UiInput(payload) => commands_for_ui_input(state, payload),
        RuntimeEvent::CloudCommand(command) => commands_for_cloud_command(command),
        RuntimeEvent::MediaSnapshot(snapshot) => commands_for_media_snapshot(snapshot),
        RuntimeEvent::VoipSnapshot(snapshot) => commands_for_voip_snapshot(state, snapshot),
        RuntimeEvent::NetworkSnapshot(snapshot) => commands_for_network_snapshot(snapshot),
        RuntimeEvent::PowerSnapshot(snapshot) => commands_for_power_snapshot(state, snapshot),
        RuntimeEvent::VoiceTranscript(snapshot) => commands_for_voice_transcript(state, snapshot),
        RuntimeEvent::VoiceAskResult(snapshot) => commands_for_voice_ask_result(state, snapshot),
        RuntimeEvent::VoiceSpeakResult(snapshot) => commands_for_voice_speak_result(snapshot),
        RuntimeEvent::UiScreenshotCaptured(captured) => vec![RuntimeCommand::AppendAppLog {
            line: screenshot_log_line(captured),
        }],
        RuntimeEvent::Shutdown => vec![RuntimeCommand::Shutdown],
        RuntimeEvent::WorkerReady { .. }
        | RuntimeEvent::CloudSnapshot(_)
        | RuntimeEvent::UiScreenChanged { .. }
        | RuntimeEvent::WorkerError { .. }
        | RuntimeEvent::WorkerExited { .. }
        | RuntimeEvent::Ignored => Vec::new(),
    }
}

/// App log line for a UI screenshot capture result. The success wording is a
/// contract: skills/yoyopod-screenshot and rules/lvgl.md grep the app log for
/// `Saved screenshot via LVGL readback` / `Saved screenshot via shadow buffer`.
fn screenshot_log_line(captured: &UiScreenshotCaptured) -> String {
    if !captured.ok {
        let detail = if captured.detail.is_empty() {
            "unknown error"
        } else {
            captured.detail.as_str()
        };
        return format!("Screenshot capture failed: {detail}");
    }
    match captured.method {
        Some(method) => format!(
            "Saved screenshot via {} -> {}",
            method.label(),
            captured.path
        ),
        None => format!("Saved screenshot -> {}", captured.path),
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
        WorkerDomain::Ui => RuntimeEvent::Ignored,
        WorkerDomain::Cloud => cloud_event_from_message(message_type, payload),
        WorkerDomain::Media => media_event_from_message(message_type, payload),
        WorkerDomain::Voip => voip_event_from_message(message_type, payload),
        WorkerDomain::Network => network_event_from_message(message_type, payload),
        WorkerDomain::Power => power_event_from_message(message_type, payload),
        WorkerDomain::Voice => voice_event_from_message(message_type, payload),
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

fn power_event_from_message(message_type: &str, payload: Value) -> RuntimeEvent {
    match message_type {
        "power.ready" => RuntimeEvent::WorkerReady {
            domain: WorkerDomain::Power,
        },
        "power.snapshot" | "power.health" => RuntimeEvent::PowerSnapshot(payload),
        "power.error" => RuntimeEvent::WorkerError {
            domain: WorkerDomain::Power,
            message: worker_error_message(message_type, &payload),
        },
        _ => RuntimeEvent::Ignored,
    }
}

fn voice_event_from_message(message_type: &str, payload: Value) -> RuntimeEvent {
    match message_type {
        "voice.ready" => RuntimeEvent::WorkerReady {
            domain: WorkerDomain::Voice,
        },
        "voice.health.result" | "voice.health" => {
            if payload
                .get("healthy")
                .and_then(Value::as_bool)
                .unwrap_or(true)
            {
                RuntimeEvent::WorkerReady {
                    domain: WorkerDomain::Voice,
                }
            } else {
                RuntimeEvent::WorkerError {
                    domain: WorkerDomain::Voice,
                    message: worker_error_message(message_type, &payload),
                }
            }
        }
        "voice.transcribe.result" | "voice.transcript" => RuntimeEvent::VoiceTranscript(payload),
        "voice.ask.result" => RuntimeEvent::VoiceAskResult(payload),
        "voice.speak.result" => RuntimeEvent::VoiceSpeakResult(payload),
        "voice.error" => RuntimeEvent::WorkerError {
            domain: WorkerDomain::Voice,
            message: worker_error_message(message_type, &payload),
        },
        _ => RuntimeEvent::Ignored,
    }
}

fn commands_for_ui_intent(state: &RuntimeState, intent: &UiIntent) -> Vec<RuntimeCommand> {
    match intent {
        UiIntent::Music(intent) => commands_for_music_intent(state, intent),
        UiIntent::Call(intent) => commands_for_call_intent(state, intent),
        UiIntent::Voice(intent) => commands_for_voice_intent(state, intent),
        UiIntent::Power(intent) => commands_for_power_intent(intent),
        UiIntent::Navigation(_) => Vec::new(),
        UiIntent::Runtime(RuntimeIntent::Shutdown) => vec![RuntimeCommand::Shutdown],
    }
}

fn commands_for_music_intent(state: &RuntimeState, intent: &MusicIntent) -> Vec<RuntimeCommand> {
    match intent {
        MusicIntent::PlayPause => {
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
        MusicIntent::NextTrack => vec![worker_command(
            WorkerDomain::Media,
            "media.next_track",
            empty_payload(),
        )],
        MusicIntent::PreviousTrack => vec![worker_command(
            WorkerDomain::Media,
            "media.previous_track",
            empty_payload(),
        )],
        MusicIntent::ShuffleAll => vec![worker_command(
            WorkerDomain::Media,
            "media.shuffle_all",
            empty_payload(),
        )],
        MusicIntent::LoadPlaylist(action) => list_item_target(action)
            .map(|path| {
                vec![worker_command(
                    WorkerDomain::Media,
                    "media.load_playlist",
                    json!({ "path": path }),
                )]
            })
            .unwrap_or_default(),
        MusicIntent::PlayRecentTrack(action) => list_item_track_uri(action)
            .map(|track_uri| {
                vec![worker_command(
                    WorkerDomain::Media,
                    "media.play_recent_track",
                    json!({ "track_uri": track_uri }),
                )]
            })
            .unwrap_or_default(),
    }
}

fn commands_for_call_intent(state: &RuntimeState, intent: &CallIntent) -> Vec<RuntimeCommand> {
    match intent {
        CallIntent::Answer => vec![worker_command(
            WorkerDomain::Voip,
            "voip.answer",
            empty_payload(),
        )],
        CallIntent::Hangup => vec![worker_command(
            WorkerDomain::Voip,
            "voip.hangup",
            empty_payload(),
        )],
        CallIntent::Reject => vec![worker_command(
            WorkerDomain::Voip,
            "voip.reject",
            empty_payload(),
        )],
        CallIntent::ToggleMute => vec![worker_command(
            WorkerDomain::Voip,
            "voip.set_mute",
            json!({ "muted": !state.call.muted }),
        )],
        CallIntent::Start(action) => contact_uri(action)
            .map(|uri| {
                vec![worker_command(
                    WorkerDomain::Voip,
                    "voip.dial",
                    json!({ "uri": uri }),
                )]
            })
            .unwrap_or_default(),
    }
}

fn commands_for_voice_intent(state: &RuntimeState, intent: &VoiceIntent) -> Vec<RuntimeCommand> {
    match intent {
        VoiceIntent::AskStart => {
            let file_path = state.voice.ask_recording_file_path();
            vec![worker_command(
                WorkerDomain::Voip,
                "voip.start_voice_note_recording",
                json!({ "file_path": file_path }),
            )]
        }
        VoiceIntent::AskStop => vec![worker_command(
            WorkerDomain::Voip,
            "voip.stop_voice_note_recording",
            empty_payload(),
        )],
        VoiceIntent::AskCancel => vec![worker_command(
            WorkerDomain::Voip,
            "voip.cancel_voice_note_recording",
            empty_payload(),
        )],
        VoiceIntent::CaptureStart(_) => {
            let file_path = state.voice.recording_file_path();
            vec![worker_command(
                WorkerDomain::Voip,
                "voip.start_voice_note_recording",
                json!({ "file_path": file_path }),
            )]
        }
        VoiceIntent::CaptureStop => vec![worker_command(
            WorkerDomain::Voip,
            "voip.stop_voice_note_recording",
            empty_payload(),
        )],
        VoiceIntent::CaptureCancel => vec![worker_command(
            WorkerDomain::Voip,
            "voip.cancel_voice_note_recording",
            empty_payload(),
        )],
        VoiceIntent::CaptureToggle(_) => {
            if state.voice.phase == "recording" {
                commands_for_voice_intent(state, &VoiceIntent::CaptureStop)
            } else {
                commands_for_voice_intent(
                    state,
                    &VoiceIntent::CaptureStart(VoiceRecipientAction::default()),
                )
            }
        }
        VoiceIntent::Send(action) => {
            let uri = voice_recipient_uri(action);
            let file_path = non_empty_string(&action.file_path)
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
        VoiceIntent::Play(action) => action
            .as_ref()
            .and_then(voice_file_path)
            .or_else(|| non_empty_string(&state.voice.file_path))
            .map(|file_path| {
                vec![worker_command(
                    WorkerDomain::Voip,
                    "voip.play_voice_note",
                    json!({ "file_path": file_path }),
                )]
            })
            .unwrap_or_default(),
        VoiceIntent::PlayLatest(action) => {
            let Some(file_path) = voice_file_path(action) else {
                return Vec::new();
            };
            let mut commands = vec![worker_command(
                WorkerDomain::Voip,
                "voip.play_voice_note",
                json!({ "file_path": file_path }),
            )];
            if let Some(uri) = voice_file_uri(action) {
                commands.push(worker_command(
                    WorkerDomain::Voip,
                    "voip.mark_voice_notes_seen",
                    json!({ "uri": uri }),
                ));
            }
            commands
        }
        VoiceIntent::StopPlayback => vec![worker_command(
            WorkerDomain::Voip,
            "voip.stop_voice_note_playback",
            empty_payload(),
        )],
        VoiceIntent::MarkSeen(action) => contact_uri(action)
            .map(|uri| {
                vec![worker_command(
                    WorkerDomain::Voip,
                    "voip.mark_voice_notes_seen",
                    json!({ "uri": uri }),
                )]
            })
            .unwrap_or_default(),
        VoiceIntent::Discard => Vec::new(),
    }
}

fn commands_for_voice_transcript(state: &RuntimeState, payload: &Value) -> Vec<RuntimeCommand> {
    let transcript = string_field(payload, "text")
        .or_else(|| string_field(payload, "transcript"))
        .unwrap_or_default();
    if transcript.trim().is_empty() {
        return Vec::new();
    }

    if let Some(response) = state.pending_voice_call_confirmation_response(&transcript) {
        return match response {
            VoiceConfirmationResponse::Yes => state
                .pending_voice_call_confirmation_contact()
                .map(|contact| {
                    vec![worker_command(
                        WorkerDomain::Voip,
                        "voip.dial",
                        json!({ "uri": contact.id }),
                    )]
                })
                .unwrap_or_default(),
            VoiceConfirmationResponse::No => Vec::new(),
        };
    }

    let decision = route_voice_transcript(&transcript, &state.voice.command_settings);
    if decision.kind != VoiceRouteKind::Command
        && state.infer_voice_call_confirmation(&transcript).is_some()
    {
        return Vec::new();
    }
    match decision.kind {
        VoiceRouteKind::Command => decision
            .command
            .as_ref()
            .map(|command| commands_for_voice_command(state, command.intent, &command.contact_name))
            .unwrap_or_default(),
        VoiceRouteKind::AskFallback => vec![worker_command(
            WorkerDomain::Voice,
            "voice.ask",
            json!({
                "question": decision.normalized_text,
                "history": state.voice.ask_history_payload(),
                "model": state.voice.command_settings.ask_model,
                "instructions": state.voice.command_settings.ask_instructions,
                "max_output_chars": state.voice.command_settings.ask_max_response_chars,
            }),
        )],
        VoiceRouteKind::AskExit => vec![ui_command(UiCommand::InputAction(InputAction::Back))],
        VoiceRouteKind::Action => commands_for_voice_route_action(&decision.route_name),
        VoiceRouteKind::LocalHelp => Vec::new(),
    }
}

fn commands_for_voice_route_action(route_name: &str) -> Vec<RuntimeCommand> {
    match route_name {
        "back" => vec![ui_command(UiCommand::InputAction(InputAction::Back))],
        _ => Vec::new(),
    }
}

fn commands_for_voice_ask_result(state: &RuntimeState, payload: &Value) -> Vec<RuntimeCommand> {
    let Some(answer) = string_field(payload, "answer") else {
        return Vec::new();
    };
    let mut envelope =
        WorkerEnvelope::command("voice.speak", None, state.voice.speak_payload(&answer));
    envelope.deadline_ms = state.voice.speech_settings.request_timeout_ms;
    vec![RuntimeCommand::WorkerCommand {
        domain: WorkerDomain::Voice,
        envelope,
    }]
}

fn commands_for_voice_speak_result(payload: &Value) -> Vec<RuntimeCommand> {
    string_field(payload, "audio_path")
        .map(|file_path| {
            vec![worker_command(
                WorkerDomain::Voip,
                "voip.play_voice_note",
                json!({ "file_path": file_path }),
            )]
        })
        .unwrap_or_default()
}

fn commands_for_voice_command(
    state: &RuntimeState,
    intent: VoiceCommandIntent,
    contact_name: &str,
) -> Vec<RuntimeCommand> {
    match intent {
        VoiceCommandIntent::PlayMusic => vec![worker_command(
            WorkerDomain::Media,
            "media.shuffle_all",
            empty_payload(),
        )],
        VoiceCommandIntent::CallContact => state
            .contact_for_voice_label(contact_name)
            .map(|contact| {
                vec![worker_command(
                    WorkerDomain::Voip,
                    "voip.dial",
                    json!({ "uri": contact.id }),
                )]
            })
            .unwrap_or_default(),
        VoiceCommandIntent::VolumeUp => vec![worker_command(
            WorkerDomain::Media,
            "media.set_volume",
            json!({"volume": adjusted_volume(state, 10)}),
        )],
        VoiceCommandIntent::VolumeDown => vec![worker_command(
            WorkerDomain::Media,
            "media.set_volume",
            json!({"volume": adjusted_volume(state, -10)}),
        )],
        VoiceCommandIntent::ReadScreen
        | VoiceCommandIntent::MuteMic
        | VoiceCommandIntent::UnmuteMic
        | VoiceCommandIntent::Unknown => Vec::new(),
    }
}

fn adjusted_volume(state: &RuntimeState, delta: i32) -> i32 {
    (state.media.volume + delta).clamp(0, 100)
}

fn commands_for_power_intent(intent: &PowerIntent) -> Vec<RuntimeCommand> {
    match intent {
        PowerIntent::Refresh => vec![worker_command(
            WorkerDomain::Power,
            "power.refresh",
            empty_payload(),
        )],
        PowerIntent::SyncTimeToRtc => vec![worker_command(
            WorkerDomain::Power,
            "power.sync_time_to_rtc",
            empty_payload(),
        )],
        PowerIntent::SyncTimeFromRtc => vec![worker_command(
            WorkerDomain::Power,
            "power.sync_time_from_rtc",
            empty_payload(),
        )],
        PowerIntent::SetRtcAlarm(action) => {
            if action.when.trim().is_empty() {
                return Vec::new();
            }
            vec![worker_command(
                WorkerDomain::Power,
                "power.set_rtc_alarm",
                json!({
                    "when": action.when,
                    "repeat_mask": action.repeat_mask,
                }),
            )]
        }
        PowerIntent::DisableRtcAlarm => vec![worker_command(
            WorkerDomain::Power,
            "power.disable_rtc_alarm",
            empty_payload(),
        )],
    }
}

fn commands_for_ui_input(state: &RuntimeState, input: &UiInputEvent) -> Vec<RuntimeCommand> {
    let mut commands = vec![RuntimeCommand::AppendAppLog {
        line: format!(
            "UI input action={} method={} duration_ms={}",
            input.action.as_str(),
            input.method,
            input.duration_ms
        ),
    }];

    if state.call.state == CallState::Incoming && input.action == InputAction::Select {
        commands.push(worker_command(
            WorkerDomain::Voip,
            "voip.answer",
            empty_payload(),
        ));
    }

    commands
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
        if let Some(command) = ask_capture_transcribe_command(state, snapshot) {
            commands.push(command);
        }
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
    if let Some(command) = ask_capture_transcribe_command(state, snapshot) {
        commands.push(command);
    }

    commands
}

fn ask_capture_transcribe_command(
    state: &RuntimeState,
    snapshot: &Value,
) -> Option<RuntimeCommand> {
    if !state.voice.ask_capture_active || state.voice.ask_transcribe_requested {
        return None;
    }
    let voice_note = snapshot.get("voice_note")?;
    let raw_state = string_field(voice_note, "state").unwrap_or_default();
    if !matches!(normalized(&raw_state).as_str(), "recorded" | "review") {
        return None;
    }
    let file_path = string_field(voice_note, "file_path")?;
    let mut envelope = WorkerEnvelope::command(
        "voice.transcribe",
        None,
        state.voice.transcribe_payload(&file_path),
    );
    envelope.deadline_ms = state.voice.capture_settings.request_timeout_ms;
    Some(RuntimeCommand::WorkerCommand {
        domain: WorkerDomain::Voice,
        envelope,
    })
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

fn commands_for_power_snapshot(state: &RuntimeState, snapshot: &Value) -> Vec<RuntimeCommand> {
    let snapshot = snapshot.get("snapshot").unwrap_or(snapshot);
    let mut commands = Vec::new();
    let Some(battery) = snapshot
        .get("battery")
        .filter(|battery| battery.is_object())
    else {
        return commands;
    };
    if let Some(level) = f64_field(battery, "level_percent").filter(|level| level.is_finite()) {
        let charging = battery
            .get("charging")
            .and_then(Value::as_bool)
            .unwrap_or(false);
        let level = (level.round() as i64).clamp(0, 100);

        commands.push(worker_command(
            WorkerDomain::Cloud,
            "cloud.publish_battery",
            json!({
                "level": level,
                "charging": charging,
            }),
        ));
    }
    for action in state.power_safety_actions(snapshot, current_epoch_seconds()) {
        commands.push(power_safety_event_command(action));
    }
    commands
}

fn power_safety_event_command(action: PowerSafetyAction) -> RuntimeCommand {
    match action {
        PowerSafetyAction::LowBatteryWarning {
            threshold_percent,
            battery_percent,
            ..
        } => worker_command(
            WorkerDomain::Cloud,
            "cloud.publish_event",
            json!({
                "event_type": "power.low_battery_warning",
                "payload": {
                    "threshold_percent": threshold_percent,
                    "battery_percent": battery_percent,
                },
            }),
        ),
        PowerSafetyAction::GracefulShutdownRequested {
            reason,
            delay_seconds,
            battery_percent,
            ..
        } => worker_command(
            WorkerDomain::Cloud,
            "cloud.publish_event",
            json!({
                "event_type": "power.graceful_shutdown_requested",
                "payload": {
                    "reason": reason,
                    "delay_seconds": delay_seconds,
                    "battery_percent": battery_percent,
                },
            }),
        ),
        PowerSafetyAction::GracefulShutdownCancelled { reason } => worker_command(
            WorkerDomain::Cloud,
            "cloud.publish_event",
            json!({
                "event_type": "power.graceful_shutdown_cancelled",
                "payload": {
                    "reason": reason,
                },
            }),
        ),
    }
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

fn ui_command(command: UiCommand) -> RuntimeCommand {
    RuntimeCommand::WorkerCommand {
        domain: WorkerDomain::Ui,
        envelope: command.into_envelope(),
    }
}

fn list_item_target(action: &ListItemAction) -> Option<String> {
    non_empty_string(&action.id).or_else(|| non_empty_string(&action.path))
}

fn list_item_track_uri(action: &ListItemAction) -> Option<String> {
    non_empty_string(&action.id).or_else(|| non_empty_string(&action.track_uri))
}

fn contact_uri(action: &ContactAction) -> Option<String> {
    non_empty_string(&action.id)
        .or_else(|| non_empty_string(&action.sip_address))
        .or_else(|| non_empty_string(&action.uri))
}

fn voice_recipient_uri(action: &VoiceRecipientAction) -> Option<String> {
    non_empty_string(&action.recipient_address).or_else(|| non_empty_string(&action.id))
}

fn voice_file_path(action: &VoiceFileAction) -> Option<String> {
    non_empty_string(&action.file_path)
}

fn voice_file_uri(action: &VoiceFileAction) -> Option<String> {
    non_empty_string(&action.id)
        .or_else(|| non_empty_string(&action.uri))
        .or_else(|| non_empty_string(&action.sip_address))
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

fn f64_field(value: &Value, key: &str) -> Option<f64> {
    let value = value.get(key)?;
    value
        .as_f64()
        .or_else(|| value.as_str()?.trim().parse::<f64>().ok())
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

#[cfg(test)]
mod tests {
    use super::*;
    use yoyopod_protocol::ui::{ListItemAction, MusicIntent, UiEvent};

    #[test]
    fn typed_music_intent_routes_to_media_command() {
        let envelope =
            UiEvent::Intent(UiIntent::Music(MusicIntent::LoadPlaylist(ListItemAction {
                id: "favorites.m3u".to_string(),
                title: "Favorites".to_string(),
                ..ListItemAction::default()
            })))
            .into_envelope();

        let event = runtime_event_from_worker(WorkerDomain::Ui, envelope).unwrap();
        let commands = commands_for_event(&RuntimeState::default(), &event);

        assert_eq!(commands.len(), 1);
        let RuntimeCommand::WorkerCommand { domain, envelope } = &commands[0] else {
            panic!("expected worker command");
        };
        assert_eq!(*domain, WorkerDomain::Media);
        assert_eq!(envelope.message_type, "media.load_playlist");
        assert_eq!(envelope.payload["path"], "favorites.m3u");
    }

    #[test]
    fn malformed_ui_intent_becomes_worker_error() {
        let envelope = WorkerEnvelope::event("ui.intent", json!({"domain": "music"}));
        let event = runtime_event_from_worker(WorkerDomain::Ui, envelope).unwrap();

        let RuntimeEvent::WorkerError { domain, message } = event else {
            panic!("expected worker error");
        };
        assert_eq!(domain, WorkerDomain::Ui);
        assert!(message.contains("missing UI field action"));
    }

    #[test]
    fn typed_ui_input_event_routes_to_runtime_input() {
        let input = UiInputEvent {
            action: InputAction::PttPress,
            method: "button".to_string(),
            timestamp_ms: 10,
            duration_ms: 0,
        };
        let envelope = UiEvent::Input(input.clone()).into_envelope();

        let event = runtime_event_from_worker(WorkerDomain::Ui, envelope).unwrap();

        assert_eq!(event, RuntimeEvent::UiInput(input));
    }

    #[test]
    fn ui_input_is_written_to_the_app_log() {
        let input = UiInputEvent {
            action: InputAction::Advance,
            method: "single_tap".to_string(),
            timestamp_ms: 10,
            duration_ms: 0,
        };

        let commands = commands_for_ui_input(&RuntimeState::default(), &input);

        assert_eq!(commands.len(), 1);
        assert!(matches!(
            &commands[0],
            RuntimeCommand::AppendAppLog { line }
                if line == "UI input action=advance method=single_tap duration_ms=0"
        ));
    }

    #[test]
    fn unknown_ui_event_type_becomes_worker_error() {
        let envelope = WorkerEnvelope::event("ui.nope", json!({}));

        let event = runtime_event_from_worker(WorkerDomain::Ui, envelope).unwrap();

        let RuntimeEvent::WorkerError { domain, message } = event else {
            panic!("expected worker error");
        };
        assert_eq!(domain, WorkerDomain::Ui);
        assert!(message.contains("unknown UI event type ui.nope"));
    }
}
