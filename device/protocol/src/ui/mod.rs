mod snapshot;

use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::BTreeMap;

pub use snapshot::{
    CallRuntimeSnapshot, HubCardSnapshot, HubRuntimeSnapshot, ListItemSnapshot,
    MusicRuntimeSnapshot, NetworkRuntimeSnapshot, OverlayRuntimeSnapshot, PowerPageSnapshot,
    PowerRuntimeSnapshot, RuntimeSnapshot, RuntimeSnapshotDomain, RuntimeSnapshotPatch,
    VoiceNoteSummarySnapshot, VoiceRuntimeSnapshot,
};

use crate::{EnvelopeKind, ProtocolError, WorkerEnvelope};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum UiScreen {
    Hub,
    Listen,
    Playlists,
    PlaylistTracks,
    RecentTracks,
    NowPlaying,
    Ask,
    Talk,
    Contacts,
    CallHistory,
    TalkContact,
    Replay,
    VoiceNote,
    IncomingCall,
    OutgoingCall,
    InCall,
    Power,
    Loading,
    Error,
}

impl UiScreen {
    pub const ALL: [Self; 19] = [
        Self::Hub,
        Self::Listen,
        Self::Playlists,
        Self::PlaylistTracks,
        Self::RecentTracks,
        Self::NowPlaying,
        Self::Ask,
        Self::Talk,
        Self::Contacts,
        Self::CallHistory,
        Self::TalkContact,
        Self::Replay,
        Self::VoiceNote,
        Self::IncomingCall,
        Self::OutgoingCall,
        Self::InCall,
        Self::Power,
        Self::Loading,
        Self::Error,
    ];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Hub => "hub",
            Self::Listen => "listen",
            Self::Playlists => "playlists",
            Self::PlaylistTracks => "playlist_tracks",
            Self::RecentTracks => "recent_tracks",
            Self::NowPlaying => "now_playing",
            Self::Ask => "ask",
            Self::Talk => "talk",
            Self::Contacts => "contacts",
            Self::CallHistory => "call_history",
            Self::TalkContact => "talk_contact",
            Self::Replay => "replay",
            Self::VoiceNote => "voice_note",
            Self::IncomingCall => "incoming_call",
            Self::OutgoingCall => "outgoing_call",
            Self::InCall => "in_call",
            Self::Power => "power",
            Self::Loading => "loading",
            Self::Error => "error",
        }
    }
}

impl Default for UiScreen {
    fn default() -> Self {
        Self::Hub
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InputAction {
    Advance,
    Select,
    Home,
    Back,
    PttPress,
    PttRelease,
}

impl InputAction {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Advance => "advance",
            Self::Select => "select",
            Self::Home => "home",
            Self::Back => "back",
            Self::PttPress => "ptt_press",
            Self::PttRelease => "ptt_release",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub enum UiCommand {
    SetBacklight { brightness: f32 },
    RuntimeSnapshot(RuntimeSnapshot),
    RuntimePatch(RuntimeSnapshotPatch),
    InputAction(InputAction),
    Tick,
    PollInput,
    Health,
    Animate(AnimationRequest),
    Screenshot { path: String, prefer_readback: bool },
    Shutdown,
    WorkerStop,
}

impl UiCommand {
    pub fn from_envelope(envelope: WorkerEnvelope) -> Result<Self, ProtocolError> {
        if envelope.kind != EnvelopeKind::Command {
            return Err(ProtocolError::InvalidEnvelope(format!(
                "expected UI command envelope, got {:?}",
                envelope.kind
            )));
        }

        match envelope.message_type.as_str() {
            "ui.set_backlight" => {
                let payload: SetBacklightPayload = decode_payload(envelope.payload)?;
                Ok(Self::SetBacklight {
                    brightness: payload.brightness.clamp(0.0, 1.0),
                })
            }
            "ui.runtime_snapshot" => Ok(Self::RuntimeSnapshot(RuntimeSnapshot::from_payload(
                &envelope.payload,
            )?)),
            "ui.runtime_patch" => Ok(Self::RuntimePatch(RuntimeSnapshotPatch::from_payload(
                &envelope.payload,
            )?)),
            "ui.input_action" => {
                let payload: InputActionPayload = decode_payload(envelope.payload)?;
                Ok(Self::InputAction(payload.action))
            }
            "ui.tick" => Ok(Self::Tick),
            "ui.poll_input" => Ok(Self::PollInput),
            "ui.health" => Ok(Self::Health),
            "ui.animate" => Ok(Self::Animate(decode_payload(envelope.payload)?)),
            "ui.screenshot" => {
                let payload: ScreenshotPayload = decode_payload(envelope.payload)?;
                Ok(Self::Screenshot {
                    path: payload.path,
                    prefer_readback: payload.prefer_readback,
                })
            }
            "ui.shutdown" => Ok(Self::Shutdown),
            "worker.stop" => Ok(Self::WorkerStop),
            other => Err(ProtocolError::InvalidEnvelope(format!(
                "unknown UI command type {other}"
            ))),
        }
    }

    pub fn into_envelope(self) -> WorkerEnvelope {
        match self {
            Self::SetBacklight { brightness } => WorkerEnvelope::command(
                "ui.set_backlight",
                None,
                json!({ "brightness": brightness.clamp(0.0, 1.0) }),
            ),
            Self::RuntimeSnapshot(snapshot) => WorkerEnvelope::command(
                "ui.runtime_snapshot",
                None,
                serde_json::to_value(snapshot).expect("serializing UI runtime snapshot"),
            ),
            Self::RuntimePatch(patch) => WorkerEnvelope::command(
                "ui.runtime_patch",
                None,
                serde_json::to_value(patch).expect("serializing UI runtime patch"),
            ),
            Self::InputAction(action) => {
                WorkerEnvelope::command("ui.input_action", None, json!({ "action": action }))
            }
            Self::Tick => WorkerEnvelope::command("ui.tick", None, json!({})),
            Self::PollInput => WorkerEnvelope::command("ui.poll_input", None, json!({})),
            Self::Health => WorkerEnvelope::command("ui.health", None, json!({})),
            Self::Animate(request) => WorkerEnvelope::command(
                "ui.animate",
                None,
                serde_json::to_value(request).expect("serializing UI animation request"),
            ),
            Self::Screenshot {
                path,
                prefer_readback,
            } => WorkerEnvelope::command(
                "ui.screenshot",
                None,
                json!({ "path": path, "prefer_readback": prefer_readback }),
            ),
            Self::Shutdown => WorkerEnvelope::command("ui.shutdown", None, json!({})),
            Self::WorkerStop => WorkerEnvelope::command("worker.stop", None, json!({})),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AnimationRequest {
    pub id: String,
    pub target: AnimationTarget,
    pub property: AnimationProperty,
    pub easing: AnimationEasing,
    pub from: i32,
    pub to: i32,
    pub duration_ms: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AnimationTarget {
    ActiveScreen,
    FocusedSelection,
    Runtime,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AnimationProperty {
    Opacity,
    OffsetY,
    ScalePermille,
    SelectionOffset,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AnimationEasing {
    Linear,
    EaseIn,
    EaseOut,
    EaseInOut,
    Bounce,
    Spring,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UiInputEvent {
    pub action: InputAction,
    pub method: String,
    pub timestamp_ms: u64,
    pub duration_ms: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UiReady {
    pub display: DisplayInfo,
    #[serde(default = "default_ui_schema_version")]
    pub schema_version: u16,
    #[serde(default)]
    pub screens: Vec<ScreenCapabilities>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DisplayInfo {
    pub width: usize,
    pub height: usize,
}

pub const UI_SCHEMA_VERSION: u16 = 3;

fn default_ui_schema_version() -> u16 {
    UI_SCHEMA_VERSION
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ScreenCapabilities {
    pub screen: UiScreen,
    #[serde(default)]
    pub supported_intents: Vec<IntentKind>,
    #[serde(default)]
    pub passthrough: Option<InputAction>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct IntentKind {
    pub domain: String,
    pub action: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UiScreenChanged {
    pub screen: UiScreen,
    #[serde(default)]
    pub title: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UiHealth {
    pub frames: usize,
    pub button_events: usize,
    #[serde(default)]
    pub last_ui_renderer: String,
    #[serde(default)]
    pub active_screen: UiScreen,
    #[serde(default)]
    pub full_snapshots: u64,
    #[serde(default)]
    pub patches_per_domain: BTreeMap<RuntimeSnapshotDomain, u64>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UiError {
    pub code: String,
    pub message: String,
}

impl UiError {
    pub fn new(code: UiErrorCode, message: impl Into<String>) -> Self {
        Self {
            code: code.as_str().to_string(),
            message: message.into(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UiErrorCode {
    DecodeError,
    InvalidCommand,
    ManagerTimeout,
    RuntimeStalled,
    WorkerError,
}

impl UiErrorCode {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::DecodeError => "decode_error",
            Self::InvalidCommand => "invalid_command",
            Self::ManagerTimeout => "manager_timeout",
            Self::RuntimeStalled => "runtime_stalled",
            Self::WorkerError => "worker_error",
        }
    }
}

/// How a screenshot was (or was requested to be) captured on the device.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ScreenshotMethod {
    LvglReadback,
    ShadowBuffer,
}

impl ScreenshotMethod {
    /// Human-readable label used in app log lines, e.g.
    /// `Saved screenshot via LVGL readback -> /tmp/yoyopod_screenshot.png`.
    pub const fn label(self) -> &'static str {
        match self {
            Self::LvglReadback => "LVGL readback",
            Self::ShadowBuffer => "shadow buffer",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct UiScreenshotCaptured {
    pub path: String,
    pub ok: bool,
    #[serde(default)]
    pub method: Option<ScreenshotMethod>,
    #[serde(default)]
    pub detail: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UiEvent {
    Ready(UiReady),
    Input(UiInputEvent),
    Intent(UiIntent),
    ScreenChanged(UiScreenChanged),
    Health(UiHealth),
    ScreenshotCaptured(UiScreenshotCaptured),
    Error(UiError),
    ShutdownComplete,
}

impl UiEvent {
    pub fn from_envelope(envelope: WorkerEnvelope) -> Result<Self, ProtocolError> {
        if !matches!(envelope.kind, EnvelopeKind::Event | EnvelopeKind::Error) {
            return Err(ProtocolError::InvalidEnvelope(format!(
                "expected UI event envelope, got {:?}",
                envelope.kind
            )));
        }

        if envelope.kind == EnvelopeKind::Error {
            return Ok(Self::Error(error_from_payload(
                envelope.message_type,
                &envelope.payload,
            )));
        }

        match envelope.message_type.as_str() {
            "ui.ready" => Ok(Self::Ready(decode_payload(envelope.payload)?)),
            "ui.input" => Ok(Self::Input(decode_payload(envelope.payload)?)),
            "ui.intent" => Ok(Self::Intent(UiIntent::from_event_payload(
                &envelope.payload,
            )?)),
            "ui.screen_changed" => Ok(Self::ScreenChanged(decode_payload(envelope.payload)?)),
            "ui.health" => Ok(Self::Health(decode_payload(envelope.payload)?)),
            "ui.screenshot_captured" => {
                Ok(Self::ScreenshotCaptured(decode_payload(envelope.payload)?))
            }
            "ui.error" => Ok(Self::Error(decode_payload(envelope.payload)?)),
            "ui.shutdown_complete" => Ok(Self::ShutdownComplete),
            other => Err(ProtocolError::InvalidEnvelope(format!(
                "unknown UI event type {other}"
            ))),
        }
    }

    pub fn into_envelope(self) -> WorkerEnvelope {
        match self {
            Self::Ready(ready) => event("ui.ready", ready),
            Self::Input(input) => event("ui.input", input),
            Self::Intent(intent) => WorkerEnvelope::event("ui.intent", intent.to_event_payload()),
            Self::ScreenChanged(changed) => event("ui.screen_changed", changed),
            Self::Health(health) => event("ui.health", health),
            Self::ScreenshotCaptured(captured) => event("ui.screenshot_captured", captured),
            Self::Error(error) => event("ui.error", error),
            Self::ShutdownComplete => WorkerEnvelope::event("ui.shutdown_complete", json!({})),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UiIntent {
    Music(MusicIntent),
    Call(CallIntent),
    Voice(VoiceIntent),
    Power(PowerIntent),
    Navigation(NavigationIntent),
    Runtime(RuntimeIntent),
}

impl UiIntent {
    pub fn from_event_payload(payload: &Value) -> Result<Self, ProtocolError> {
        let domain = required_string(payload, "domain")?;
        let action = required_string(payload, "action")?;
        let intent_payload = payload
            .get("payload")
            .cloned()
            .unwrap_or_else(empty_payload);

        match normalized(&domain).as_str() {
            "music" => Ok(Self::Music(MusicIntent::from_parts(
                &action,
                &intent_payload,
            )?)),
            "call" => Ok(Self::Call(CallIntent::from_parts(
                &action,
                &intent_payload,
            )?)),
            "voice" => Ok(Self::Voice(VoiceIntent::from_parts(
                &action,
                &intent_payload,
            )?)),
            "power" => Ok(Self::Power(PowerIntent::from_parts(
                &action,
                &intent_payload,
            )?)),
            "navigation" => Ok(Self::Navigation(NavigationIntent::from_parts(&action)?)),
            "runtime" => Ok(Self::Runtime(RuntimeIntent::from_parts(&action)?)),
            other => Err(ProtocolError::InvalidEnvelope(format!(
                "unknown UI intent domain {other}"
            ))),
        }
    }

    pub fn to_event_payload(&self) -> Value {
        let (domain, action, payload) = match self {
            Self::Music(intent) => ("music", intent.action_name(), intent.payload()),
            Self::Call(intent) => ("call", intent.action_name(), intent.payload()),
            Self::Voice(intent) => ("voice", intent.action_name(), intent.payload()),
            Self::Power(intent) => ("power", intent.action_name(), intent.payload()),
            Self::Navigation(intent) => ("navigation", intent.action_name(), empty_payload()),
            Self::Runtime(intent) => ("runtime", intent.action_name(), empty_payload()),
        };
        json!({
            "domain": domain,
            "action": action,
            "payload": payload,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum MusicIntent {
    PlayPause,
    NextTrack,
    PreviousTrack,
    ShuffleAll,
    LoadPlaylist(ListItemAction),
    PlayPlaylistTrack(PlaylistTrackAction),
    PlayRecentTrack(ListItemAction),
}

impl MusicIntent {
    fn from_parts(action: &str, payload: &Value) -> Result<Self, ProtocolError> {
        match normalized(action).as_str() {
            "play_pause" => Ok(Self::PlayPause),
            "next" | "next_track" => Ok(Self::NextTrack),
            "previous" | "previous_track" => Ok(Self::PreviousTrack),
            "shuffle_all" => Ok(Self::ShuffleAll),
            "load_playlist" => Ok(Self::LoadPlaylist(decode_payload(payload.clone())?)),
            "play_playlist_track" => Ok(Self::PlayPlaylistTrack(decode_payload(payload.clone())?)),
            "play_recent_track" => Ok(Self::PlayRecentTrack(decode_payload(payload.clone())?)),
            other => Err(ProtocolError::InvalidEnvelope(format!(
                "unknown music intent action {other}"
            ))),
        }
    }

    fn action_name(&self) -> &'static str {
        match self {
            Self::PlayPause => "play_pause",
            Self::NextTrack => "next_track",
            Self::PreviousTrack => "previous_track",
            Self::ShuffleAll => "shuffle_all",
            Self::LoadPlaylist(_) => "load_playlist",
            Self::PlayPlaylistTrack(_) => "play_playlist_track",
            Self::PlayRecentTrack(_) => "play_recent_track",
        }
    }

    fn payload(&self) -> Value {
        match self {
            Self::LoadPlaylist(action) | Self::PlayRecentTrack(action) => payload(action),
            Self::PlayPlaylistTrack(action) => payload(action),
            _ => empty_payload(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CallIntent {
    Answer,
    Reject,
    Hangup,
    ToggleMute,
    Start(ContactAction),
}

impl CallIntent {
    fn from_parts(action: &str, payload: &Value) -> Result<Self, ProtocolError> {
        match normalized(action).as_str() {
            "answer" => Ok(Self::Answer),
            "reject" => Ok(Self::Reject),
            "hangup" => Ok(Self::Hangup),
            "toggle_mute" => Ok(Self::ToggleMute),
            "start" => Ok(Self::Start(decode_payload(payload.clone())?)),
            other => Err(ProtocolError::InvalidEnvelope(format!(
                "unknown call intent action {other}"
            ))),
        }
    }

    fn action_name(&self) -> &'static str {
        match self {
            Self::Answer => "answer",
            Self::Reject => "reject",
            Self::Hangup => "hangup",
            Self::ToggleMute => "toggle_mute",
            Self::Start(_) => "start",
        }
    }

    fn payload(&self) -> Value {
        match self {
            Self::Start(action) => payload(action),
            _ => empty_payload(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VoiceIntent {
    AskStart,
    AskStop,
    AskCancel,
    CaptureStart(VoiceRecipientAction),
    CaptureStartAndSend(VoiceRecipientAction),
    CaptureStop,
    CaptureCancel,
    CaptureToggle(Option<VoiceRecipientAction>),
    Send(VoiceRecipientAction),
    Play(Option<VoiceFileAction>),
    PlayLatest(VoiceFileAction),
    PausePlayback,
    ResumePlayback,
    StopPlayback,
    Delete(VoiceFileAction),
    MarkSeen(ContactAction),
    Discard,
}

impl VoiceIntent {
    fn from_parts(action: &str, payload: &Value) -> Result<Self, ProtocolError> {
        match normalized(action).as_str() {
            "ask_start" | "begin_ask" => Ok(Self::AskStart),
            "ask_stop" | "finish_ask" => Ok(Self::AskStop),
            "ask_cancel" => Ok(Self::AskCancel),
            "capture_start" | "start_recording" => {
                Ok(Self::CaptureStart(decode_payload(payload.clone())?))
            }
            "capture_start_and_send" | "start_recording_and_send" => {
                Ok(Self::CaptureStartAndSend(decode_payload(payload.clone())?))
            }
            "capture_stop" | "stop_recording" => Ok(Self::CaptureStop),
            "capture_cancel" | "cancel_recording" => Ok(Self::CaptureCancel),
            "capture_toggle" => Ok(Self::CaptureToggle(optional_payload(payload)?)),
            "send" | "send_voice_note" => Ok(Self::Send(decode_payload(payload.clone())?)),
            "play" | "play_voice_note" => Ok(Self::Play(optional_payload(payload)?)),
            "play_latest" => Ok(Self::PlayLatest(decode_payload(payload.clone())?)),
            "pause_playback" => Ok(Self::PausePlayback),
            "resume_playback" => Ok(Self::ResumePlayback),
            "stop_playback" => Ok(Self::StopPlayback),
            "delete" | "delete_voice_note" => Ok(Self::Delete(decode_payload(payload.clone())?)),
            "mark_seen" => Ok(Self::MarkSeen(decode_payload(payload.clone())?)),
            "discard" | "again" | "reset" => Ok(Self::Discard),
            other => Err(ProtocolError::InvalidEnvelope(format!(
                "unknown voice intent action {other}"
            ))),
        }
    }

    fn action_name(&self) -> &'static str {
        match self {
            Self::AskStart => "ask_start",
            Self::AskStop => "ask_stop",
            Self::AskCancel => "ask_cancel",
            Self::CaptureStart(_) => "capture_start",
            Self::CaptureStartAndSend(_) => "capture_start_and_send",
            Self::CaptureStop => "capture_stop",
            Self::CaptureCancel => "capture_cancel",
            Self::CaptureToggle(_) => "capture_toggle",
            Self::Send(_) => "send",
            Self::Play(_) => "play",
            Self::PlayLatest(_) => "play_latest",
            Self::PausePlayback => "pause_playback",
            Self::ResumePlayback => "resume_playback",
            Self::StopPlayback => "stop_playback",
            Self::Delete(_) => "delete",
            Self::MarkSeen(_) => "mark_seen",
            Self::Discard => "discard",
        }
    }

    fn payload(&self) -> Value {
        match self {
            Self::CaptureStart(action) | Self::CaptureStartAndSend(action) | Self::Send(action) => {
                payload(action)
            }
            Self::CaptureToggle(Some(action)) => payload(action),
            Self::Play(Some(action)) | Self::PlayLatest(action) | Self::Delete(action) => {
                payload(action)
            }
            Self::MarkSeen(action) => payload(action),
            _ => empty_payload(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PowerIntent {
    Refresh,
    SyncTimeToRtc,
    SyncTimeFromRtc,
    SetRtcAlarm(RtcAlarmAction),
    DisableRtcAlarm,
}

impl PowerIntent {
    fn from_parts(action: &str, payload: &Value) -> Result<Self, ProtocolError> {
        match normalized(action).as_str() {
            "refresh" | "refresh_snapshot" => Ok(Self::Refresh),
            "sync_time_to_rtc" | "sync_to_rtc" => Ok(Self::SyncTimeToRtc),
            "sync_time_from_rtc" | "sync_from_rtc" => Ok(Self::SyncTimeFromRtc),
            "set_rtc_alarm" | "set_alarm" => {
                Ok(Self::SetRtcAlarm(decode_payload(payload.clone())?))
            }
            "disable_rtc_alarm" | "disable_alarm" => Ok(Self::DisableRtcAlarm),
            other => Err(ProtocolError::InvalidEnvelope(format!(
                "unknown power intent action {other}"
            ))),
        }
    }

    fn action_name(&self) -> &'static str {
        match self {
            Self::Refresh => "refresh",
            Self::SyncTimeToRtc => "sync_time_to_rtc",
            Self::SyncTimeFromRtc => "sync_time_from_rtc",
            Self::SetRtcAlarm(_) => "set_rtc_alarm",
            Self::DisableRtcAlarm => "disable_rtc_alarm",
        }
    }

    fn payload(&self) -> Value {
        match self {
            Self::SetRtcAlarm(action) => payload(action),
            _ => empty_payload(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NavigationIntent {
    Back,
}

impl NavigationIntent {
    fn from_parts(action: &str) -> Result<Self, ProtocolError> {
        match normalized(action).as_str() {
            "back" => Ok(Self::Back),
            other => Err(ProtocolError::InvalidEnvelope(format!(
                "unknown navigation intent action {other}"
            ))),
        }
    }

    fn action_name(self) -> &'static str {
        match self {
            Self::Back => "back",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuntimeIntent {
    Shutdown,
}

impl RuntimeIntent {
    fn from_parts(action: &str) -> Result<Self, ProtocolError> {
        match normalized(action).as_str() {
            "shutdown" => Ok(Self::Shutdown),
            other => Err(ProtocolError::InvalidEnvelope(format!(
                "unknown runtime intent action {other}"
            ))),
        }
    }

    fn action_name(self) -> &'static str {
        match self {
            Self::Shutdown => "shutdown",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ListItemAction {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub title: String,
    #[serde(default)]
    pub path: String,
    #[serde(default)]
    pub track_uri: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PlaylistTrackAction {
    pub playlist_path: String,
    pub track_uri: String,
    pub track_index: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct ContactAction {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub name: String,
    #[serde(default)]
    pub sip_address: String,
    #[serde(default)]
    pub uri: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct VoiceRecipientAction {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub recipient_address: String,
    #[serde(default)]
    pub recipient_name: String,
    #[serde(default)]
    pub file_path: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct VoiceFileAction {
    #[serde(default)]
    pub id: String,
    #[serde(default)]
    pub recipient_name: String,
    #[serde(default)]
    pub file_path: String,
    #[serde(default)]
    pub uri: String,
    #[serde(default)]
    pub sip_address: String,
    #[serde(default)]
    pub message_id: String,
    #[serde(default)]
    pub duration_ms: i32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RtcAlarmAction {
    pub when: String,
    #[serde(default = "default_repeat_mask")]
    pub repeat_mask: i64,
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
struct SetBacklightPayload {
    #[serde(default = "default_brightness")]
    brightness: f32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
struct ScreenshotPayload {
    path: String,
    #[serde(default)]
    prefer_readback: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
struct InputActionPayload {
    action: InputAction,
}

fn event(message_type: &'static str, payload: impl Serialize) -> WorkerEnvelope {
    WorkerEnvelope::event(
        message_type,
        serde_json::to_value(payload).expect("serializing UI event payload"),
    )
}

fn decode_payload<T: for<'de> Deserialize<'de>>(payload: Value) -> Result<T, ProtocolError> {
    serde_json::from_value(payload)
        .map_err(|error| ProtocolError::InvalidEnvelope(format!("invalid UI payload: {error}")))
}

fn optional_payload<T: for<'de> Deserialize<'de> + Default>(
    payload: &Value,
) -> Result<Option<T>, ProtocolError> {
    if payload.as_object().is_none_or(|object| object.is_empty()) {
        return Ok(None);
    }
    Ok(Some(decode_payload(payload.clone())?))
}

fn payload(value: impl Serialize) -> Value {
    serde_json::to_value(value).expect("serializing UI intent payload")
}

fn required_string(payload: &Value, field: &str) -> Result<String, ProtocolError> {
    payload
        .get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
        .ok_or_else(|| ProtocolError::InvalidEnvelope(format!("missing UI field {field}")))
}

fn error_from_payload(message_type: String, payload: &Value) -> UiError {
    let raw_code = string_field(payload, "code").unwrap_or_else(|| message_type.clone());
    UiError {
        code: normalize_error_code(&raw_code),
        message: string_field(payload, "message")
            .or_else(|| string_field(payload, "error"))
            .unwrap_or(message_type),
    }
}

fn normalize_error_code(value: &str) -> String {
    let mut normalized = String::new();
    let mut previous_was_separator = false;
    for character in value.trim().chars() {
        if character.is_ascii_alphanumeric() {
            normalized.push(character.to_ascii_lowercase());
            previous_was_separator = false;
        } else if !previous_was_separator && !normalized.is_empty() {
            normalized.push('_');
            previous_was_separator = true;
        }
    }
    while normalized.ends_with('_') {
        normalized.pop();
    }
    if normalized.is_empty() {
        UiErrorCode::WorkerError.as_str().to_string()
    } else {
        normalized
    }
}

fn string_field(payload: &Value, field: &str) -> Option<String> {
    payload
        .get(field)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .map(str::to_string)
}

fn normalized(value: &str) -> String {
    value.trim().to_ascii_lowercase()
}

fn empty_payload() -> Value {
    json!({})
}

fn default_brightness() -> f32 {
    0.8
}

fn default_repeat_mask() -> i64 {
    127
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn command_round_trip_decodes_typed_input_action() {
        let envelope = UiCommand::InputAction(InputAction::Back).into_envelope();
        let decoded = UiCommand::from_envelope(envelope).unwrap();
        assert_eq!(decoded, UiCommand::InputAction(InputAction::Back));
    }

    #[test]
    fn every_ui_command_round_trips_through_worker_envelope() {
        let commands = vec![
            UiCommand::SetBacklight { brightness: 0.5 },
            UiCommand::RuntimeSnapshot(RuntimeSnapshot::default()),
            UiCommand::RuntimePatch(RuntimeSnapshotPatch::Music(MusicRuntimeSnapshot::default())),
            UiCommand::InputAction(InputAction::Select),
            UiCommand::Tick,
            UiCommand::PollInput,
            UiCommand::Health,
            UiCommand::Animate(AnimationRequest {
                id: "screen_enter".to_string(),
                target: AnimationTarget::ActiveScreen,
                property: AnimationProperty::OffsetY,
                easing: AnimationEasing::EaseOut,
                from: 8,
                to: 0,
                duration_ms: 180,
            }),
            UiCommand::Screenshot {
                path: "/tmp/yoyopod_screenshot.png".to_string(),
                prefer_readback: true,
            },
            UiCommand::Shutdown,
            UiCommand::WorkerStop,
        ];

        for command in commands {
            let decoded = UiCommand::from_envelope(command.clone().into_envelope()).unwrap();
            assert_eq!(decoded, command);
        }
    }

    #[test]
    fn event_round_trip_decodes_typed_intent() {
        let intent = UiIntent::Music(MusicIntent::LoadPlaylist(ListItemAction {
            id: "mix".to_string(),
            title: "Mix".to_string(),
            ..ListItemAction::default()
        }));
        let envelope = UiEvent::Intent(intent.clone()).into_envelope();
        let decoded = UiEvent::from_envelope(envelope).unwrap();
        assert_eq!(decoded, UiEvent::Intent(intent));
    }

    #[test]
    fn playlist_track_intent_round_trips_with_its_queue_position() {
        let intent = UiIntent::Music(MusicIntent::PlayPlaylistTrack(PlaylistTrackAction {
            playlist_path: "/music/Open Classics.m3u".to_string(),
            track_uri: "/music/02 - March.mp3".to_string(),
            track_index: 1,
        }));
        let envelope = UiEvent::Intent(intent.clone()).into_envelope();
        let decoded = UiEvent::from_envelope(envelope).unwrap();
        assert_eq!(decoded, UiEvent::Intent(intent));
    }

    #[test]
    fn held_recording_auto_send_intent_round_trips_with_its_recipient() {
        let intent = UiIntent::Voice(VoiceIntent::CaptureStartAndSend(VoiceRecipientAction {
            id: "sip:mama@example.test".to_string(),
            recipient_address: "sip:mama@example.test".to_string(),
            recipient_name: "Mama".to_string(),
            ..VoiceRecipientAction::default()
        }));

        let decoded = UiIntent::from_event_payload(&intent.to_event_payload()).unwrap();

        assert_eq!(decoded, intent);
    }

    #[test]
    fn every_ui_event_round_trips_through_worker_envelope() {
        let events = vec![
            UiEvent::Ready(UiReady {
                display: DisplayInfo {
                    width: 240,
                    height: 280,
                },
                schema_version: UI_SCHEMA_VERSION,
                screens: Vec::new(),
            }),
            UiEvent::Input(UiInputEvent {
                action: InputAction::Advance,
                method: "button".to_string(),
                timestamp_ms: 42,
                duration_ms: 7,
            }),
            UiEvent::Intent(UiIntent::Runtime(RuntimeIntent::Shutdown)),
            UiEvent::ScreenChanged(UiScreenChanged {
                screen: UiScreen::Hub,
                title: "Hub".to_string(),
            }),
            UiEvent::Health(UiHealth {
                frames: 3,
                button_events: 2,
                last_ui_renderer: "lvgl".to_string(),
                active_screen: UiScreen::Hub,
                full_snapshots: 1,
                patches_per_domain: BTreeMap::new(),
            }),
            UiEvent::ScreenshotCaptured(UiScreenshotCaptured {
                path: "/tmp/yoyopod_screenshot.png".to_string(),
                ok: true,
                method: Some(ScreenshotMethod::LvglReadback),
                detail: String::new(),
            }),
            UiEvent::ScreenshotCaptured(UiScreenshotCaptured {
                path: "/tmp/yoyopod_screenshot.png".to_string(),
                ok: false,
                method: None,
                detail: "LVGL display not initialized".to_string(),
            }),
            UiEvent::Error(UiError::new(UiErrorCode::InvalidCommand, "bad command")),
            UiEvent::ShutdownComplete,
        ];

        for event in events {
            let decoded = UiEvent::from_envelope(event.clone().into_envelope()).unwrap();
            assert_eq!(decoded, event);
        }
    }

    #[test]
    fn every_ui_intent_domain_round_trips_through_event_payload() {
        let intents = vec![
            UiIntent::Music(MusicIntent::PlayPause),
            UiIntent::Call(CallIntent::Start(ContactAction {
                id: "sip:ada@example.test".to_string(),
                name: "Ada".to_string(),
                ..ContactAction::default()
            })),
            UiIntent::Voice(VoiceIntent::CaptureStart(VoiceRecipientAction {
                id: "sip:ada@example.test".to_string(),
                recipient_address: "sip:ada@example.test".to_string(),
                recipient_name: "Ada".to_string(),
                ..VoiceRecipientAction::default()
            })),
            UiIntent::Power(PowerIntent::SetRtcAlarm(RtcAlarmAction {
                when: "2026-05-12T08:00:00Z".to_string(),
                repeat_mask: 31,
            })),
            UiIntent::Navigation(NavigationIntent::Back),
            UiIntent::Runtime(RuntimeIntent::Shutdown),
        ];

        for intent in intents {
            let decoded = UiIntent::from_event_payload(&intent.to_event_payload()).unwrap();
            assert_eq!(decoded, intent);
        }
    }

    #[test]
    fn unknown_command_type_is_rejected() {
        let envelope = WorkerEnvelope::command("ui.nope", None, json!({}));
        assert!(matches!(
            UiCommand::from_envelope(envelope),
            Err(ProtocolError::InvalidEnvelope(_))
        ));
    }

    #[test]
    fn malformed_intent_payload_is_rejected() {
        let envelope = WorkerEnvelope::event("ui.intent", json!({"domain": "music"}));
        assert!(matches!(
            UiEvent::from_envelope(envelope),
            Err(ProtocolError::InvalidEnvelope(_))
        ));
    }

    #[test]
    fn runtime_snapshot_uses_typed_screen_identity() {
        let snapshot = RuntimeSnapshot {
            app_state: UiScreen::Power,
            ..RuntimeSnapshot::default()
        };
        let payload = serde_json::to_value(&snapshot).unwrap();
        assert_eq!(payload["app_state"], "power");

        let decoded = RuntimeSnapshot::from_payload(&payload).unwrap();
        assert_eq!(decoded.app_state, UiScreen::Power);
        assert!(matches!(
            RuntimeSnapshot::from_payload(&json!({ "app_state": "setup" })),
            Err(ProtocolError::InvalidEnvelope(_))
        ));
    }

    #[test]
    fn runtime_patch_reports_domain() {
        assert_eq!(
            RuntimeSnapshotPatch::Music(MusicRuntimeSnapshot::default()).domain(),
            RuntimeSnapshotDomain::Music
        );
        assert_eq!(
            RuntimeSnapshotPatch::Full(RuntimeSnapshot::default()).domain(),
            RuntimeSnapshotDomain::Full
        );
    }

    #[test]
    fn error_envelope_codes_are_normalized() {
        let envelope = WorkerEnvelope::error("ui.worker-error", None, "Worker.Error", "failed");
        let decoded = UiEvent::from_envelope(envelope).unwrap();
        assert_eq!(
            decoded,
            UiEvent::Error(UiError {
                code: "worker_error".to_string(),
                message: "failed".to_string(),
            })
        );
    }

    #[test]
    fn typed_error_constructor_uses_canonical_code() {
        assert_eq!(
            UiError::new(UiErrorCode::InvalidCommand, "bad").code,
            "invalid_command"
        );
        assert_eq!(
            UiError::new(UiErrorCode::ManagerTimeout, "stale manager").code,
            "manager_timeout"
        );
    }
}
