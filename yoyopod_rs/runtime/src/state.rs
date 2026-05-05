use std::collections::BTreeMap;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

use crate::voice::{
    match_voice_confirmation_response, normalize_voice_activation, route_voice_transcript,
    VoiceCaptureSettings, VoiceCommandIntent, VoiceCommandSettings, VoiceConfirmationResponse,
    VoiceRouteKind, VoiceSpeechSettings,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum WorkerDomain {
    Ui,
    Cloud,
    Media,
    Voip,
    Network,
    Power,
    Voice,
}

impl WorkerDomain {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Ui => "ui",
            Self::Cloud => "cloud",
            Self::Media => "media",
            Self::Voip => "voip",
            Self::Network => "network",
            Self::Power => "power",
            Self::Voice => "voice",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkerState {
    Stopped,
    Starting,
    Running,
    Degraded,
    Disabled,
}

impl WorkerState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Stopped => "stopped",
            Self::Starting => "starting",
            Self::Running => "running",
            Self::Degraded => "degraded",
            Self::Disabled => "disabled",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkerHealth {
    pub state: WorkerState,
    pub restart_count: u64,
    pub protocol_errors: u64,
    pub last_reason: String,
}

impl Default for WorkerHealth {
    fn default() -> Self {
        Self {
            state: WorkerState::Stopped,
            restart_count: 0,
            protocol_errors: 0,
            last_reason: String::new(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CallState {
    Idle,
    Incoming,
    Outgoing,
    Active,
    Error,
}

impl CallState {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Idle => "idle",
            Self::Incoming => "incoming",
            Self::Outgoing => "outgoing",
            Self::Active => "active",
            Self::Error => "error",
        }
    }

    fn from_worker_state(raw: &str) -> Self {
        let normalized = raw.trim().to_ascii_lowercase();
        if normalized.starts_with("outgoing_") {
            return Self::Outgoing;
        }

        match normalized.as_str() {
            "incoming" => Self::Incoming,
            "outgoing" => Self::Outgoing,
            "connected" | "streams_running" | "paused" | "paused_by_remote"
            | "updated_by_remote" | "active" => Self::Active,
            "error" => Self::Error,
            _ => Self::Idle,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ListItem {
    pub id: String,
    pub title: String,
    pub subtitle: String,
    pub icon_key: String,
    pub aliases: Vec<String>,
}

impl ListItem {
    fn from_snapshot(value: &Value, icon_key: &'static str) -> Option<Self> {
        if !value.is_object() {
            return None;
        }

        let id = string_field(value, "uri")
            .or_else(|| string_field(value, "id"))
            .unwrap_or_default();
        let title = string_field(value, "name")
            .or_else(|| string_field(value, "title"))
            .unwrap_or_default();
        let subtitle = string_field(value, "artist")
            .or_else(|| string_field(value, "subtitle"))
            .or_else(|| playlist_track_count_subtitle(value, icon_key))
            .unwrap_or_default();
        let icon_key = string_field(value, "icon_key").unwrap_or_else(|| icon_key.to_string());

        Some(Self {
            id,
            title,
            subtitle,
            icon_key,
            aliases: string_array_field(value, "aliases"),
        })
    }

    fn to_payload(&self) -> Value {
        json!({
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "icon_key": self.icon_key,
            "aliases": self.aliases,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MediaState {
    pub connected: bool,
    pub playback_state: String,
    pub title: String,
    pub artist: String,
    pub progress_permille: i32,
    pub volume: i32,
    pub playlists: Vec<ListItem>,
    pub recent_tracks: Vec<ListItem>,
}

impl Default for MediaState {
    fn default() -> Self {
        Self {
            connected: false,
            playback_state: "stopped".to_string(),
            title: "Nothing Playing".to_string(),
            artist: String::new(),
            progress_permille: 0,
            volume: 50,
            playlists: Vec::new(),
            recent_tracks: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CallRuntimeState {
    pub registered: bool,
    pub registration_state: String,
    pub state: CallState,
    pub peer_name: String,
    pub peer_address: String,
    pub duration_text: String,
    pub muted: bool,
    pub contacts: Vec<ListItem>,
    pub history: Vec<ListItem>,
    pub unread_voice_notes_by_contact: BTreeMap<String, usize>,
    pub latest_voice_note_by_contact: BTreeMap<String, VoiceNoteSummary>,
}

impl Default for CallRuntimeState {
    fn default() -> Self {
        Self {
            registered: false,
            registration_state: "none".to_string(),
            state: CallState::Idle,
            peer_name: String::new(),
            peer_address: String::new(),
            duration_text: String::new(),
            muted: false,
            contacts: Vec::new(),
            history: Vec::new(),
            unread_voice_notes_by_contact: BTreeMap::new(),
            latest_voice_note_by_contact: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceNoteSummary {
    pub message_id: String,
    pub direction: String,
    pub delivery_state: String,
    pub local_file_path: String,
    pub duration_ms: i32,
    pub unread: bool,
    pub display_name: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct VoiceCommandOutcome {
    headline: String,
    body: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceAskTurn {
    pub question: String,
    pub answer: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceCallConfirmation {
    pub spoken_name: String,
    pub display_name: String,
}

impl VoiceNoteSummary {
    fn to_payload(&self) -> Value {
        json!({
            "message_id": self.message_id,
            "direction": self.direction,
            "delivery_state": self.delivery_state,
            "local_file_path": self.local_file_path,
            "duration_ms": self.duration_ms,
            "unread": self.unread,
            "display_name": self.display_name,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct VoiceRuntimeState {
    pub phase: String,
    pub headline: String,
    pub body: String,
    pub status_text: String,
    pub file_path: String,
    pub duration_ms: i32,
    pub mime_type: String,
    pub message_id: String,
    pub playback_active: bool,
    pub playback_file_path: String,
    pub voice_note_store_dir: String,
    pub last_transcript: String,
    pub command_settings: VoiceCommandSettings,
    pub capture_settings: VoiceCaptureSettings,
    pub speech_settings: VoiceSpeechSettings,
    pub ask_capture_active: bool,
    pub ask_transcribe_requested: bool,
    pub pending_ask_question: String,
    pub ask_history: Vec<VoiceAskTurn>,
    pub pending_call_confirmation: Option<VoiceCallConfirmation>,
}

impl Default for VoiceRuntimeState {
    fn default() -> Self {
        Self {
            phase: "idle".to_string(),
            headline: "Ask".to_string(),
            body: "Ask me anything...".to_string(),
            status_text: String::new(),
            file_path: String::new(),
            duration_ms: 0,
            mime_type: "audio/wav".to_string(),
            message_id: String::new(),
            playback_active: false,
            playback_file_path: String::new(),
            voice_note_store_dir: "data/communication/voice_notes".to_string(),
            last_transcript: String::new(),
            command_settings: VoiceCommandSettings::default(),
            capture_settings: VoiceCaptureSettings::default(),
            speech_settings: VoiceSpeechSettings::default(),
            ask_capture_active: false,
            ask_transcribe_requested: false,
            pending_ask_question: String::new(),
            ask_history: Vec::new(),
            pending_call_confirmation: None,
        }
    }
}

impl VoiceRuntimeState {
    pub fn recording_file_path(&self) -> String {
        let filename = format!(
            "yoyopod-voice-note-{}-{}.wav",
            std::process::id(),
            current_millis()
        );
        Path::new(&self.voice_note_store_dir)
            .join(filename)
            .to_string_lossy()
            .to_string()
    }

    pub fn ask_recording_file_path(&self) -> String {
        let filename = format!(
            "yoyopod-ask-{}-{}.wav",
            std::process::id(),
            current_millis()
        );
        Path::new(&self.voice_note_store_dir)
            .join(filename)
            .to_string_lossy()
            .to_string()
    }

    pub fn transcribe_payload(&self, audio_path: &str) -> Value {
        json!({
            "audio_path": audio_path,
            "format": "wav",
            "sample_rate_hz": self.capture_settings.sample_rate_hz,
            "channels": 1,
            "language": self.capture_settings.stt_language,
            "model": self.capture_settings.stt_model,
            "prompt": self.capture_settings.stt_prompt,
            "max_audio_seconds": self.capture_settings.max_audio_ms as f64 / 1000.0,
            "delete_input_on_success": true,
        })
    }

    pub fn speak_payload(&self, text: &str) -> Value {
        json!({
            "text": text.trim(),
            "voice": self.speech_settings.tts_voice,
            "model": self.speech_settings.tts_model,
            "instructions": self.speech_settings.tts_instructions,
            "format": "wav",
            "sample_rate_hz": self.speech_settings.sample_rate_hz,
        })
    }

    pub fn ask_history_payload(&self) -> Value {
        let history = self
            .ask_history
            .iter()
            .flat_map(|turn| {
                [
                    json!({"role": "user", "text": turn.question}),
                    json!({"role": "assistant", "text": turn.answer}),
                ]
            })
            .collect::<Vec<_>>();
        json!(history)
    }

    fn remember_ask_turn(&mut self, question: &str, answer: &str) {
        let limit = self.command_settings.ask_max_response_chars.max(1);
        let question = trim_ask_history_text(question, limit);
        let answer = trim_ask_history_text(answer, limit);
        if question.is_empty() || answer.is_empty() {
            return;
        }

        self.ask_history.push(VoiceAskTurn { question, answer });
        let max_turns = self.command_settings.ask_max_history_turns.max(1);
        if self.ask_history.len() > max_turns {
            let keep_from = self.ask_history.len() - max_turns;
            self.ask_history.drain(..keep_from);
        }
    }

    fn reset_draft(&mut self) {
        let store_dir = self.voice_note_store_dir.clone();
        let command_settings = self.command_settings.clone();
        let capture_settings = self.capture_settings.clone();
        let speech_settings = self.speech_settings.clone();
        let pending_ask_question = self.pending_ask_question.clone();
        let ask_history = self.ask_history.clone();
        *self = Self {
            voice_note_store_dir: store_dir,
            command_settings,
            capture_settings,
            speech_settings,
            pending_ask_question,
            ask_history,
            ..Self::default()
        };
    }

    fn set_interaction(
        &mut self,
        phase: impl Into<String>,
        headline: impl Into<String>,
        body: impl Into<String>,
    ) {
        self.phase = phase.into();
        self.headline = headline.into();
        self.body = body.into();
        self.status_text.clear();
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NetworkRuntimeState {
    pub enabled: bool,
    pub connected: bool,
    pub connection_type: String,
    pub signal_strength: i32,
    pub gps_has_fix: bool,
    pub setup_network_rows: Vec<SetupRow>,
    pub setup_gps_rows: Vec<SetupRow>,
}

impl Default for NetworkRuntimeState {
    fn default() -> Self {
        Self {
            enabled: false,
            connected: false,
            connection_type: "none".to_string(),
            signal_strength: 0,
            gps_has_fix: false,
            setup_network_rows: Vec::new(),
            setup_gps_rows: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CloudRuntimeState {
    pub device_id: String,
    pub provisioning_state: String,
    pub cloud_state: String,
    pub mqtt_connected: bool,
    pub last_error_summary: String,
}

impl Default for CloudRuntimeState {
    fn default() -> Self {
        Self {
            device_id: String::new(),
            provisioning_state: "unprovisioned".to_string(),
            cloud_state: "offline".to_string(),
            mqtt_connected: false,
            last_error_summary: String::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct PowerSafetyConfig {
    pub enabled: bool,
    pub low_battery_warning_percent: f64,
    pub low_battery_warning_cooldown_seconds: f64,
    pub auto_shutdown_enabled: bool,
    pub critical_shutdown_percent: f64,
    pub shutdown_delay_seconds: f64,
    pub shutdown_command: String,
    pub shutdown_state_file: String,
}

impl Default for PowerSafetyConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            low_battery_warning_percent: 20.0,
            low_battery_warning_cooldown_seconds: 300.0,
            auto_shutdown_enabled: true,
            critical_shutdown_percent: 10.0,
            shutdown_delay_seconds: 15.0,
            shutdown_command: "sudo -n shutdown -h now".to_string(),
            shutdown_state_file: "data/last_shutdown_state.json".to_string(),
        }
    }
}

#[derive(Debug, Clone, Default, PartialEq)]
pub struct PowerSafetyState {
    pub config: PowerSafetyConfig,
    pub low_battery_warning_active: bool,
    pub next_warning_at_seconds: u64,
    pub shutdown_pending: bool,
    pub shutdown_reason: String,
    pub shutdown_requested_at_seconds: u64,
    pub shutdown_execute_at_seconds: u64,
}

#[derive(Debug, Clone, PartialEq)]
pub enum PowerSafetyAction {
    LowBatteryWarning {
        threshold_percent: f64,
        battery_percent: f64,
        next_warning_at_seconds: u64,
    },
    GracefulShutdownRequested {
        reason: String,
        delay_seconds: f64,
        battery_percent: f64,
        requested_at_seconds: u64,
        execute_at_seconds: u64,
    },
    GracefulShutdownCancelled {
        reason: String,
    },
}

#[derive(Debug, Clone, PartialEq)]
pub struct PowerRuntimeState {
    pub available: bool,
    pub source: String,
    pub battery_percent: i32,
    pub battery_known: bool,
    pub charging: bool,
    pub charging_known: bool,
    pub external_power: bool,
    pub external_power_known: bool,
    pub model: String,
    pub firmware_version: String,
    pub voltage_text: String,
    pub rtc_time: String,
    pub alarm_text: String,
    pub error: String,
    pub safety: PowerSafetyState,
}

impl Default for PowerRuntimeState {
    fn default() -> Self {
        Self {
            available: true,
            source: "pisugar".to_string(),
            battery_percent: 100,
            battery_known: true,
            charging: false,
            charging_known: true,
            external_power: false,
            external_power_known: true,
            model: String::new(),
            firmware_version: String::new(),
            voltage_text: "Unknown".to_string(),
            rtc_time: "Unknown".to_string(),
            alarm_text: "Unknown".to_string(),
            error: String::new(),
            safety: PowerSafetyState::default(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SetupRow {
    pub label: String,
    pub value: String,
}

impl SetupRow {
    fn new(label: impl Into<String>, value: impl Into<String>) -> Self {
        Self {
            label: label.into(),
            value: value.into(),
        }
    }

    fn formatted(&self) -> String {
        format!("{}: {}", self.label, self.value)
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct RuntimeState {
    pub current_screen: String,
    pub media: MediaState,
    pub call: CallRuntimeState,
    pub voice: VoiceRuntimeState,
    pub power: PowerRuntimeState,
    pub network: NetworkRuntimeState,
    pub cloud: CloudRuntimeState,
    pub ui: WorkerHealth,
    pub cloud_worker: WorkerHealth,
    pub media_worker: WorkerHealth,
    pub voip_worker: WorkerHealth,
    pub network_worker: WorkerHealth,
    pub power_worker: WorkerHealth,
    pub voice_worker: WorkerHealth,
    pub loop_iterations: u64,
    pub last_loop_duration_ms: u64,
}

impl Default for RuntimeState {
    fn default() -> Self {
        Self {
            current_screen: "hub".to_string(),
            media: MediaState::default(),
            call: CallRuntimeState::default(),
            voice: VoiceRuntimeState::default(),
            power: PowerRuntimeState::default(),
            network: NetworkRuntimeState::default(),
            cloud: CloudRuntimeState::default(),
            ui: WorkerHealth::default(),
            cloud_worker: WorkerHealth::default(),
            media_worker: WorkerHealth::default(),
            voip_worker: WorkerHealth::default(),
            network_worker: WorkerHealth::default(),
            power_worker: WorkerHealth::default(),
            voice_worker: WorkerHealth::default(),
            loop_iterations: 0,
            last_loop_duration_ms: 0,
        }
    }
}

impl RuntimeState {
    pub fn record_worker_protocol_error(
        &mut self,
        domain: WorkerDomain,
        reason: impl Into<String>,
    ) {
        let health = self.worker_health_mut(domain);
        health.protocol_errors += 1;
        health.state = WorkerState::Degraded;
        health.last_reason = reason.into();
    }

    pub fn mark_worker(
        &mut self,
        domain: WorkerDomain,
        state: WorkerState,
        reason: impl Into<String>,
    ) {
        let health = self.worker_health_mut(domain);
        health.state = state;
        health.last_reason = reason.into();
    }

    pub fn seed_contacts(&mut self, contacts: Vec<ListItem>) {
        self.call.contacts = contacts;
    }

    pub fn configure_voice_note_store_dir(&mut self, voice_note_store_dir: impl Into<String>) {
        let voice_note_store_dir = voice_note_store_dir.into();
        if !voice_note_store_dir.trim().is_empty() {
            self.voice.voice_note_store_dir = voice_note_store_dir;
        }
    }

    pub fn configure_voice_commands(&mut self, command_settings: VoiceCommandSettings) {
        self.voice.command_settings = command_settings;
    }

    pub fn configure_voice_capture(&mut self, capture_settings: VoiceCaptureSettings) {
        self.voice.capture_settings = capture_settings;
    }

    pub fn configure_voice_speech(&mut self, speech_settings: VoiceSpeechSettings) {
        self.voice.speech_settings = speech_settings;
    }

    pub fn configure_media_volume(&mut self, volume: i32) {
        self.media.volume = volume.clamp(0, 100);
    }

    pub fn contact_for_voice_label(&self, label: &str) -> Option<&ListItem> {
        find_contact(self, label)
    }

    pub fn pending_voice_call_confirmation_response(
        &self,
        transcript: &str,
    ) -> Option<VoiceConfirmationResponse> {
        self.voice.pending_call_confirmation.as_ref()?;
        match_voice_confirmation_response(transcript)
    }

    pub fn pending_voice_call_confirmation_contact(&self) -> Option<&ListItem> {
        let pending = self.voice.pending_call_confirmation.as_ref()?;
        find_contact(self, &pending.spoken_name)
    }

    pub fn infer_voice_call_confirmation(&self, transcript: &str) -> Option<VoiceCallConfirmation> {
        infer_voice_call_confirmation(self, transcript)
    }

    pub fn configure_power_safety(&mut self, config: PowerSafetyConfig) {
        self.power.safety.config = config;
    }

    pub fn power_safety_actions(
        &self,
        snapshot: &Value,
        now_seconds: u64,
    ) -> Vec<PowerSafetyAction> {
        let snapshot = snapshot.get("snapshot").unwrap_or(snapshot);
        if !self.power.safety.config.enabled {
            return Vec::new();
        }
        if !snapshot
            .get("available")
            .and_then(Value::as_bool)
            .unwrap_or(self.power.available)
        {
            return Vec::new();
        }

        let Some(battery) = snapshot
            .get("battery")
            .filter(|battery| battery.is_object())
        else {
            return Vec::new();
        };
        let Some(battery_percent) =
            f64_field(battery, "level_percent").filter(|level| level.is_finite())
        else {
            return Vec::new();
        };

        let has_external_power = battery
            .get("power_plugged")
            .and_then(Value::as_bool)
            .unwrap_or(false)
            || battery
                .get("charging")
                .and_then(Value::as_bool)
                .unwrap_or(false);
        if has_external_power {
            if self.power.safety.shutdown_pending {
                return vec![PowerSafetyAction::GracefulShutdownCancelled {
                    reason: "external_power_restored".to_string(),
                }];
            }
            return Vec::new();
        }

        let config = &self.power.safety.config;
        if config.auto_shutdown_enabled
            && battery_percent <= config.critical_shutdown_percent
            && !self.power.safety.shutdown_pending
        {
            return vec![PowerSafetyAction::GracefulShutdownRequested {
                reason: "critical_battery".to_string(),
                delay_seconds: config.shutdown_delay_seconds,
                battery_percent,
                requested_at_seconds: now_seconds,
                execute_at_seconds: now_seconds
                    + seconds_to_u64_ceiling(config.shutdown_delay_seconds),
            }];
        }

        if battery_percent > config.low_battery_warning_percent {
            return Vec::new();
        }
        if now_seconds < self.power.safety.next_warning_at_seconds {
            return Vec::new();
        }

        vec![PowerSafetyAction::LowBatteryWarning {
            threshold_percent: config.low_battery_warning_percent,
            battery_percent,
            next_warning_at_seconds: now_seconds
                + seconds_to_u64_ceiling(config.low_battery_warning_cooldown_seconds),
        }]
    }

    pub fn power_shutdown_due(&self, now_seconds: u64) -> bool {
        self.power.safety.shutdown_pending
            && self.power.safety.shutdown_execute_at_seconds <= now_seconds
    }

    pub fn power_shutdown_state_payload(&self, saved_at_seconds: u64) -> Value {
        json!({
            "saved_at_epoch_seconds": saved_at_seconds,
            "shutdown": {
                "reason": self.power.safety.shutdown_reason,
                "requested_at_epoch_seconds": self.power.safety.shutdown_requested_at_seconds,
                "execute_at_epoch_seconds": self.power.safety.shutdown_execute_at_seconds,
                "command": self.power.safety.config.shutdown_command,
            },
            "screen": {
                "current": self.current_screen,
            },
            "power": {
                "available": self.power.available,
                "battery_percent": self.power.battery_percent,
                "battery_known": self.power.battery_known,
                "charging": self.power.charging,
                "charging_known": self.power.charging_known,
                "external_power": self.power.external_power,
                "external_power_known": self.power.external_power_known,
                "source": self.power.source,
                "model": self.power.model,
                "error": self.power.error,
            },
            "media": {
                "connected": self.media.connected,
                "playback_state": self.media.playback_state,
                "title": self.media.title,
                "artist": self.media.artist,
                "progress_permille": self.media.progress_permille,
            },
            "voip": {
                "registered": self.call.registered,
                "registration_state": self.call.registration_state,
                "call_state": self.call.state.as_str(),
                "peer_name": self.call.peer_name,
                "peer_address": self.call.peer_address,
                "muted": self.call.muted,
            },
            "network": {
                "enabled": self.network.enabled,
                "connected": self.network.connected,
                "connection_type": self.network.connection_type,
                "signal_strength": self.network.signal_strength,
                "gps_has_fix": self.network.gps_has_fix,
            },
            "cloud": {
                "device_id": self.cloud.device_id,
                "provisioning_state": self.cloud.provisioning_state,
                "cloud_state": self.cloud.cloud_state,
                "mqtt_connected": self.cloud.mqtt_connected,
            },
            "loop": {
                "iterations": self.loop_iterations,
                "last_duration_ms": self.last_loop_duration_ms,
            },
        })
    }

    pub fn mark_power_shutdown_completed(&mut self) {
        self.power.safety.shutdown_pending = false;
    }

    fn apply_power_safety_actions(&mut self, actions: &[PowerSafetyAction]) {
        for action in actions {
            match action {
                PowerSafetyAction::LowBatteryWarning {
                    next_warning_at_seconds,
                    ..
                } => {
                    self.power.safety.low_battery_warning_active = true;
                    self.power.safety.next_warning_at_seconds = *next_warning_at_seconds;
                }
                PowerSafetyAction::GracefulShutdownRequested {
                    reason,
                    requested_at_seconds,
                    execute_at_seconds,
                    ..
                } => {
                    self.power.safety.shutdown_pending = true;
                    self.power.safety.shutdown_reason = reason.clone();
                    self.power.safety.shutdown_requested_at_seconds = *requested_at_seconds;
                    self.power.safety.shutdown_execute_at_seconds = *execute_at_seconds;
                }
                PowerSafetyAction::GracefulShutdownCancelled { .. } => {
                    self.power.safety.shutdown_pending = false;
                    self.power.safety.shutdown_reason.clear();
                    self.power.safety.shutdown_requested_at_seconds = 0;
                    self.power.safety.shutdown_execute_at_seconds = 0;
                    self.power.safety.low_battery_warning_active = false;
                    self.power.safety.next_warning_at_seconds = 0;
                }
            }
        }
    }

    fn worker_health_mut(&mut self, domain: WorkerDomain) -> &mut WorkerHealth {
        match domain {
            WorkerDomain::Ui => &mut self.ui,
            WorkerDomain::Cloud => &mut self.cloud_worker,
            WorkerDomain::Media => &mut self.media_worker,
            WorkerDomain::Voip => &mut self.voip_worker,
            WorkerDomain::Network => &mut self.network_worker,
            WorkerDomain::Power => &mut self.power_worker,
            WorkerDomain::Voice => &mut self.voice_worker,
        }
    }

    pub fn apply_media_snapshot(&mut self, snapshot: &Value) {
        if let Some(connected) = snapshot.get("connected").and_then(Value::as_bool) {
            self.media.connected = connected;
        }
        if let Some(playback_state) = string_field(snapshot, "playback_state") {
            self.media.playback_state = playback_state;
        }
        if let Some(volume) =
            i32_field(snapshot, "volume").or_else(|| i32_field(snapshot, "default_volume"))
        {
            self.media.volume = volume.clamp(0, 100);
        }
        let explicit_progress_permille = i32_field(snapshot, "progress_permille")
            .filter(|progress_permille| (0..=1000).contains(progress_permille));
        if let Some(progress_permille) = explicit_progress_permille {
            self.media.progress_permille = progress_permille;
        }
        if let Some(track) = snapshot.get("current_track") {
            self.media.title = string_field(track, "name")
                .or_else(|| string_field(track, "title"))
                .unwrap_or_else(|| "Nothing Playing".to_string());
            self.media.artist = first_artist(track).unwrap_or_default();
            if let Some(progress_permille) = derived_progress_permille(snapshot, track) {
                self.media.progress_permille = progress_permille;
            } else if explicit_progress_permille.is_none() {
                self.media.progress_permille = 0;
            }
        }
        if let Some(playlists) = snapshot.get("playlists").and_then(Value::as_array) {
            self.media.playlists = playlists
                .iter()
                .filter_map(|item| ListItem::from_snapshot(item, "playlist"))
                .collect();
        }
        if let Some(recent_tracks) = snapshot.get("recent_tracks").and_then(Value::as_array) {
            self.media.recent_tracks = recent_tracks
                .iter()
                .filter_map(|item| ListItem::from_snapshot(item, "track"))
                .collect();
        }
    }

    pub fn apply_voip_snapshot(&mut self, snapshot: &Value) {
        if let Some(registered) = snapshot.get("registered").and_then(Value::as_bool) {
            self.call.registered = registered;
        }
        if let Some(registration_state) = string_field(snapshot, "registration_state") {
            self.call.registration_state = registration_state;
        }
        if let Some(call_state) = snapshot.get("call_state") {
            self.call.state = call_state
                .as_str()
                .map(CallState::from_worker_state)
                .unwrap_or(CallState::Idle);
        }
        if let Some(active_call_peer) = string_field(snapshot, "active_call_peer") {
            self.call.peer_address = active_call_peer.clone();
            self.call.peer_name = active_call_peer;
        }
        self.call.duration_text = call_duration_text(snapshot, self.call.state).unwrap_or_default();
        if let Some(muted) = snapshot.get("muted").and_then(Value::as_bool) {
            self.call.muted = muted;
        }
        if let Some(contacts) = snapshot.get("contacts").and_then(Value::as_array) {
            self.call.contacts = contacts
                .iter()
                .filter_map(|item| ListItem::from_snapshot(item, "person"))
                .collect();
        }
        if let Some(history) = snapshot
            .get("recent_call_history")
            .and_then(Value::as_array)
        {
            self.call.history = history
                .iter()
                .filter_map(|item| recent_call_history_item(item, &self.call.contacts))
                .collect();
        }
        if let Some(unread) = snapshot
            .get("unread_voice_notes_by_contact")
            .and_then(Value::as_object)
        {
            self.call.unread_voice_notes_by_contact = unread
                .iter()
                .filter_map(|(key, value)| {
                    value.as_u64().map(|count| (key.clone(), count as usize))
                })
                .collect();
        }
        if let Some(latest) = snapshot
            .get("latest_voice_note_by_contact")
            .and_then(Value::as_object)
        {
            self.call.latest_voice_note_by_contact = latest
                .iter()
                .filter_map(|(key, value)| {
                    voice_note_summary_from_value(value).map(|summary| (key.clone(), summary))
                })
                .collect();
        }
        if let Some(voice_note) = snapshot.get("voice_note") {
            if self.voice.ask_capture_active {
                self.apply_ask_capture_snapshot(voice_note);
            } else {
                self.apply_voice_note_snapshot(voice_note);
            }
        }
        if let Some(playback) = snapshot.get("voice_note_playback") {
            self.apply_voice_note_playback_snapshot(playback);
        }
    }

    pub fn apply_ui_intent(&mut self, domain: &str, action: &str, payload: &Value) {
        if domain.trim().eq_ignore_ascii_case("voice") {
            self.apply_voice_intent(action, payload);
        }
    }

    fn apply_voice_intent(&mut self, action: &str, payload: &Value) {
        match normalized(action).as_str() {
            "ask_start" | "begin_ask" => {
                self.voice.ask_capture_active = true;
                self.voice.ask_transcribe_requested = false;
                self.voice.set_interaction(
                    "listening",
                    "Listening",
                    "Say YoYo, then ask or command...",
                );
            }
            "ask_stop" | "finish_ask" => {
                self.voice.ask_capture_active = true;
                self.voice
                    .set_interaction("thinking", "Thinking", "Just a moment...");
            }
            "ask_cancel" => {
                self.voice.ask_capture_active = false;
                self.voice.ask_transcribe_requested = false;
                self.voice.pending_ask_question.clear();
                self.voice
                    .set_interaction("idle", "Ask", "Ask me anything...");
            }
            "capture_start" | "start_recording" => {
                self.voice.phase = "recording".to_string();
                self.voice.status_text = "Recording...".to_string();
                if let Some(file_path) = string_field(payload, "file_path") {
                    self.voice.file_path = file_path;
                }
            }
            "capture_stop" | "stop_recording" => {
                if self.voice.phase == "recording" {
                    self.voice.phase = "review".to_string();
                    self.voice.status_text = "Ready to send".to_string();
                }
            }
            "send" | "send_voice_note" => {
                self.voice.phase = "sending".to_string();
                self.voice.status_text = "Sending...".to_string();
            }
            "play" | "play_latest" => {
                self.voice.playback_active = true;
                self.voice.status_text = "Playing preview".to_string();
                if let Some(file_path) = string_field(payload, "file_path") {
                    self.voice.playback_file_path = file_path;
                }
            }
            "stop_playback" => {
                self.voice.playback_active = false;
                self.voice.playback_file_path.clear();
            }
            "discard" | "again" | "reset" => self.voice.reset_draft(),
            _ => {}
        }
    }

    pub fn apply_voice_transcript(&mut self, payload: &Value) {
        self.voice.ask_capture_active = false;
        self.voice.ask_transcribe_requested = false;
        let transcript = string_field(payload, "text")
            .or_else(|| string_field(payload, "transcript"))
            .unwrap_or_default();
        self.voice.last_transcript = transcript.trim().to_string();
        if self.voice.last_transcript.is_empty() {
            self.voice.pending_ask_question.clear();
            self.voice.pending_call_confirmation = None;
            self.voice
                .set_interaction("reply", "No Speech", "I did not catch a command.");
            return;
        }

        if self.apply_pending_voice_call_confirmation_response() {
            return;
        }

        let decision =
            route_voice_transcript(&self.voice.last_transcript, &self.voice.command_settings);
        match decision.kind {
            VoiceRouteKind::Command => {
                self.voice.pending_ask_question.clear();
                let command = decision.command.as_ref();
                self.apply_voice_command_outcome(command.and_then(|command| {
                    voice_command_outcome(self, command.intent, &command.contact_name)
                }));
            }
            VoiceRouteKind::AskFallback => {
                if let Some(confirmation) =
                    infer_voice_call_confirmation(self, &self.voice.last_transcript)
                {
                    self.voice.pending_ask_question.clear();
                    self.voice.pending_call_confirmation = Some(confirmation.clone());
                    self.voice.set_interaction(
                        "reply",
                        "Confirm Call",
                        format!(
                            "Did you want to call {}? Say yes or no.",
                            confirmation.display_name
                        ),
                    );
                    return;
                }
                self.voice.pending_ask_question = decision.normalized_text;
                self.voice
                    .set_interaction("thinking", "Thinking", "Finding an answer...");
            }
            VoiceRouteKind::AskExit => {
                self.voice.pending_ask_question.clear();
                self.voice.set_interaction("reply", "Ask", "Going back.");
            }
            VoiceRouteKind::Action => {
                self.voice.pending_ask_question.clear();
                self.voice.set_interaction("reply", "Command", "");
                if let Some(screen) = screen_for_voice_route(&decision.route_name) {
                    self.current_screen = screen.to_string();
                }
            }
            VoiceRouteKind::LocalHelp => {
                if let Some(confirmation) =
                    infer_voice_call_confirmation(self, &self.voice.last_transcript)
                {
                    self.voice.pending_ask_question.clear();
                    self.voice.pending_call_confirmation = Some(confirmation.clone());
                    self.voice.set_interaction(
                        "reply",
                        "Confirm Call",
                        format!(
                            "Did you want to call {}? Say yes or no.",
                            confirmation.display_name
                        ),
                    );
                    return;
                }
                self.voice.pending_ask_question.clear();
                self.voice.set_interaction(
                    "reply",
                    "Try Again",
                    "Try saying call mom, play music, or volume up.",
                );
            }
        }
    }

    pub fn apply_voice_ask_result(&mut self, payload: &Value) {
        self.voice.ask_capture_active = false;
        self.voice.ask_transcribe_requested = false;
        let answer_from_payload = string_field(payload, "answer");
        let answer = answer_from_payload.clone().unwrap_or_else(|| {
            "I cannot reach Ask right now. I can still help with music, calls, and volume."
                .to_string()
        });
        if let Some(answer_from_payload) = answer_from_payload {
            let question = std::mem::take(&mut self.voice.pending_ask_question);
            self.voice
                .remember_ask_turn(&question, &answer_from_payload);
        } else {
            self.voice.pending_ask_question.clear();
        }
        self.voice.set_interaction("reply", "Answer", answer);
    }

    fn apply_voice_command_outcome(&mut self, outcome: Option<VoiceCommandOutcome>) {
        let outcome = outcome.unwrap_or(VoiceCommandOutcome {
            headline: "Not Ready".to_string(),
            body: "That command is recognized but not wired yet.".to_string(),
        });
        self.voice
            .set_interaction("reply", outcome.headline, outcome.body);
    }

    fn apply_pending_voice_call_confirmation_response(&mut self) -> bool {
        let Some(response) =
            self.pending_voice_call_confirmation_response(&self.voice.last_transcript)
        else {
            if self.voice.pending_call_confirmation.is_some() {
                self.voice.pending_call_confirmation = None;
            }
            return false;
        };
        let Some(pending) = self.voice.pending_call_confirmation.take() else {
            return false;
        };
        self.voice.pending_ask_question.clear();
        match response {
            VoiceConfirmationResponse::Yes => {
                let outcome = find_contact(self, &pending.spoken_name)
                    .map(|contact| VoiceCommandOutcome {
                        headline: "Calling".to_string(),
                        body: format!("Calling {}.", contact.title),
                    })
                    .unwrap_or_else(|| VoiceCommandOutcome {
                        headline: "No Match".to_string(),
                        body: format!("I could not find {}.", pending.spoken_name),
                    });
                self.voice
                    .set_interaction("reply", outcome.headline, outcome.body);
            }
            VoiceConfirmationResponse::No => {
                self.voice.set_interaction(
                    "reply",
                    "Cancelled",
                    format!("Okay, I will not call {}.", pending.display_name),
                );
            }
        }
        true
    }

    fn apply_ask_capture_snapshot(&mut self, voice_note: &Value) {
        let raw_state = string_field(voice_note, "state").unwrap_or_else(|| "idle".to_string());
        if let Some(file_path) = string_field(voice_note, "file_path") {
            self.voice.file_path = file_path;
        }
        if let Some(duration_ms) = i32_field(voice_note, "duration_ms") {
            self.voice.duration_ms = duration_ms.max(0);
        }
        match normalized(&raw_state).as_str() {
            "recording" => {
                if self.voice.phase != "thinking" {
                    self.voice.set_interaction(
                        "listening",
                        "Listening",
                        "Say YoYo, then ask or command...",
                    );
                }
            }
            "recorded" | "review" => {
                self.voice.ask_transcribe_requested = true;
                self.voice
                    .set_interaction("thinking", "Thinking", "Just a moment...");
            }
            "failed" | "error" => {
                self.voice.ask_capture_active = false;
                self.voice.ask_transcribe_requested = false;
                self.voice.set_interaction(
                    "reply",
                    "Mic Unavailable",
                    "Voice capture is not ready on this device.",
                );
            }
            "cancelled" | "canceled" | "idle" => {
                self.voice.ask_capture_active = false;
                self.voice.ask_transcribe_requested = false;
            }
            _ => {}
        }
    }

    fn apply_voice_note_snapshot(&mut self, voice_note: &Value) {
        let raw_state = string_field(voice_note, "state").unwrap_or_else(|| "idle".to_string());
        let phase = match normalized(&raw_state).as_str() {
            "recording" => "recording",
            "recorded" | "review" => "review",
            "sending" => "sending",
            "sent" | "delivered" => "sent",
            "failed" | "error" => "failed",
            _ => "idle",
        };

        if phase == "idle" {
            self.voice.reset_draft();
            return;
        }

        self.voice.phase = phase.to_string();
        self.voice.status_text = voice_status_text(phase);
        if let Some(file_path) = string_field(voice_note, "file_path") {
            self.voice.file_path = file_path;
        }
        if let Some(duration_ms) = i32_field(voice_note, "duration_ms") {
            self.voice.duration_ms = duration_ms.max(0);
        }
        if let Some(mime_type) = string_field(voice_note, "mime_type") {
            self.voice.mime_type = mime_type;
        }
        if let Some(message_id) = string_field(voice_note, "message_id") {
            self.voice.message_id = message_id;
        }
    }

    fn apply_voice_note_playback_snapshot(&mut self, playback: &Value) {
        if let Some(playing) = playback.get("playing").and_then(Value::as_bool) {
            self.voice.playback_active = playing;
            if playing {
                self.voice.status_text = "Playing preview".to_string();
            }
        }
        if let Some(file_path) = string_field(playback, "file_path") {
            self.voice.playback_file_path = file_path;
        }
        if !self.voice.playback_active {
            self.voice.playback_file_path.clear();
        }
    }

    pub fn apply_network_snapshot(&mut self, snapshot: &Value) {
        let snapshot = snapshot.get("snapshot").unwrap_or(snapshot);
        let app_state = snapshot.get("app_state").unwrap_or(snapshot);
        if let Some(enabled) = app_state
            .get("network_enabled")
            .or_else(|| app_state.get("enabled"))
            .and_then(Value::as_bool)
        {
            self.network.enabled = enabled;
        }
        if let Some(connected) = app_state.get("connected").and_then(Value::as_bool) {
            self.network.connected = connected;
        } else if let Some(connected) = snapshot.get("connected").and_then(Value::as_bool) {
            self.network.connected = connected;
        }
        if let Some(connection_type) = string_field(app_state, "connection_type")
            .or_else(|| string_field(snapshot, "connection_type"))
        {
            self.network.connection_type = connection_type;
        }
        if let Some(signal_strength) = i32_field(app_state, "signal_bars")
            .or_else(|| i32_field(app_state, "signal_strength"))
            .or_else(|| {
                snapshot
                    .get("signal")
                    .and_then(|signal| i32_field(signal, "bars"))
            })
            .or_else(|| i32_field(snapshot, "signal_strength"))
        {
            self.network.signal_strength = signal_strength.clamp(0, 4);
        }
        if let Some(gps_has_fix) = app_state
            .get("gps_has_fix")
            .or_else(|| snapshot.get("gps_has_fix"))
            .and_then(Value::as_bool)
        {
            self.network.gps_has_fix = gps_has_fix;
        }
        if let Some(setup) = snapshot
            .get("views")
            .and_then(|views| views.get("setup"))
            .filter(|setup| setup.is_object())
        {
            if let Some(enabled) = setup.get("network_enabled").and_then(Value::as_bool) {
                self.network.enabled = enabled;
            }
            if let Some(rows) = setup_rows(setup.get("network_rows")) {
                self.network.setup_network_rows = rows;
            }
            if let Some(rows) = setup_rows(setup.get("gps_rows")) {
                self.network.setup_gps_rows = rows;
            }
        }
    }

    pub fn apply_power_snapshot(&mut self, snapshot: &Value) {
        let snapshot = snapshot.get("snapshot").unwrap_or(snapshot);
        let safety_actions = self.power_safety_actions(snapshot, current_epoch_seconds());
        if let Some(available) = snapshot.get("available").and_then(Value::as_bool) {
            self.power.available = available;
        }
        if let Some(source) = string_field(snapshot, "source") {
            self.power.source = source;
        }
        if let Some(error) = string_field(snapshot, "error") {
            self.power.error = error;
        }
        if let Some(device) = snapshot.get("device").filter(|device| device.is_object()) {
            if let Some(model) = string_field(device, "model") {
                self.power.model = model;
            }
            if let Some(firmware_version) = string_field(device, "firmware_version") {
                self.power.firmware_version = firmware_version;
            }
        }
        if let Some(battery) = snapshot
            .get("battery")
            .filter(|battery| battery.is_object())
        {
            if let Some(level_percent) = f64_field(battery, "level_percent") {
                if level_percent.is_finite() {
                    self.power.battery_percent = (level_percent.round() as i32).clamp(0, 100);
                    self.power.battery_known = true;
                }
            }
            if let Some(charging) = battery.get("charging").and_then(Value::as_bool) {
                self.power.charging = charging;
                self.power.charging_known = true;
            }
            if let Some(power_plugged) = battery.get("power_plugged").and_then(Value::as_bool) {
                self.power.external_power = power_plugged;
                self.power.external_power_known = true;
            }
            self.power.voltage_text = format_voltage_text(
                f64_field(battery, "voltage_volts"),
                f64_field(battery, "temperature_celsius"),
            );
        }
        if let Some(rtc) = snapshot.get("rtc").filter(|rtc| rtc.is_object()) {
            if let Some(time) = string_field(rtc, "time") {
                self.power.rtc_time = compact_datetime_text(&time);
            }
            if let Some(alarm_enabled) = rtc.get("alarm_enabled").and_then(Value::as_bool) {
                self.power.alarm_text = if alarm_enabled {
                    string_field(rtc, "alarm_time")
                        .map(|time| compact_time_text(&time))
                        .unwrap_or_else(|| "On".to_string())
                } else {
                    "Off".to_string()
                };
            }
        }
        self.reconcile_power_safety(snapshot);
        self.apply_power_safety_actions(&safety_actions);
    }

    fn reconcile_power_safety(&mut self, snapshot: &Value) {
        if !self.power.available {
            self.power.safety.shutdown_pending = false;
            self.power.safety.shutdown_reason.clear();
            self.power.safety.shutdown_requested_at_seconds = 0;
            self.power.safety.shutdown_execute_at_seconds = 0;
            return;
        }
        let Some(battery) = snapshot
            .get("battery")
            .filter(|battery| battery.is_object())
        else {
            return;
        };
        let has_external_power = battery
            .get("power_plugged")
            .and_then(Value::as_bool)
            .unwrap_or(false)
            || battery
                .get("charging")
                .and_then(Value::as_bool)
                .unwrap_or(false);
        let battery_percent = f64_field(battery, "level_percent");
        if has_external_power
            || battery_percent
                .is_some_and(|level| level > self.power.safety.config.low_battery_warning_percent)
        {
            self.power.safety.low_battery_warning_active = false;
            self.power.safety.next_warning_at_seconds = 0;
        }
    }

    pub fn apply_cloud_snapshot(&mut self, snapshot: &Value) {
        let snapshot = snapshot.get("snapshot").unwrap_or(snapshot);
        if let Some(device_id) = string_field(snapshot, "device_id") {
            self.cloud.device_id = device_id;
        }
        if let Some(provisioning_state) = string_field(snapshot, "provisioning_state") {
            self.cloud.provisioning_state = provisioning_state;
        }
        if let Some(cloud_state) = string_field(snapshot, "cloud_state") {
            self.cloud.cloud_state = cloud_state;
        }
        if let Some(mqtt_connected) = snapshot.get("mqtt_connected").and_then(Value::as_bool) {
            self.cloud.mqtt_connected = mqtt_connected;
        }
        if let Some(last_error_summary) = string_field(snapshot, "last_error_summary") {
            self.cloud.last_error_summary = last_error_summary;
        }
    }

    pub fn ui_snapshot_payload(&self) -> Value {
        json!({
            "app_state": self.current_screen,
            "hub": {
                "cards": self.default_hub_cards(),
            },
            "music": {
                "playing": self.media.playback_state == "playing",
                "paused": self.media.playback_state == "paused",
                "title": self.media.title,
                "artist": self.media.artist,
                "progress_permille": self.media.progress_permille,
                "volume": self.media.volume,
                "playlists": list_payload(&self.media.playlists),
                "recent_tracks": list_payload(&self.media.recent_tracks),
            },
            "call": {
                "state": self.call.state.as_str(),
                "peer_name": self.call.peer_name,
                "peer_address": self.call.peer_address,
                "duration_text": self.call.duration_text,
                "muted": self.call.muted,
                "contacts": list_payload(&self.call.contacts),
                "history": list_payload(&self.call.history),
                "unread_voice_notes_by_contact": self.call.unread_voice_notes_by_contact,
                "latest_voice_note_by_contact": voice_note_summary_payload(&self.call.latest_voice_note_by_contact),
            },
            "voice": {
                "phase": self.voice.phase,
                "headline": self.voice.headline,
                "body": voice_body_text(&self.voice),
                "capture_in_flight": self.voice.ask_capture_active || self.voice.phase == "recording",
                "ptt_active": self.voice.phase == "recording",
            },
            "power": {
                "battery_percent": self.power.battery_percent,
                "charging": self.power.charging,
                "power_available": self.power.available,
                "rows": self.power_rows(),
                "pages": self.setup_pages(),
            },
            "network": {
                "enabled": self.network.enabled,
                "connected": self.network.connected,
                "connection_type": self.network.connection_type,
                "signal_strength": self.network.signal_strength,
                "gps_has_fix": self.network.gps_has_fix,
            },
            "cloud": {
                "device_id": self.cloud.device_id,
                "provisioning_state": self.cloud.provisioning_state,
                "cloud_state": self.cloud.cloud_state,
                "mqtt_connected": self.cloud.mqtt_connected,
                "last_error_summary": self.cloud.last_error_summary,
            },
            "overlay": {
                "loading": false,
                "error": "",
                "message": "",
            },
            "workers": {
                WorkerDomain::Ui.as_str(): worker_payload(&self.ui),
                WorkerDomain::Cloud.as_str(): worker_payload(&self.cloud_worker),
                WorkerDomain::Media.as_str(): worker_payload(&self.media_worker),
                WorkerDomain::Voip.as_str(): worker_payload(&self.voip_worker),
                WorkerDomain::Network.as_str(): worker_payload(&self.network_worker),
                WorkerDomain::Power.as_str(): worker_payload(&self.power_worker),
                WorkerDomain::Voice.as_str(): worker_payload(&self.voice_worker),
            },
        })
    }

    fn default_hub_cards(&self) -> Vec<Value> {
        vec![
            json!({
                "key": "listen",
                "title": "Listen",
                "subtitle": "",
                "accent": 0x00FF88,
            }),
            json!({
                "key": "talk",
                "title": "Talk",
                "subtitle": "",
                "accent": 0x00D4FF,
            }),
            json!({
                "key": "ask",
                "title": "Ask",
                "subtitle": "",
                "accent": 0xFFD000,
            }),
            json!({
                "key": "setup",
                "title": "Setup",
                "subtitle": "",
                "accent": 0x9CA3AF,
            }),
        ]
    }

    fn power_rows(&self) -> Vec<String> {
        vec![
            format!("Battery {}", self.power_battery_value()),
            self.power_external_value().to_string(),
            self.network_status_row(),
            if self.call.registered {
                "VoIP ready".to_string()
            } else {
                "VoIP offline".to_string()
            },
        ]
    }

    fn network_status_row(&self) -> String {
        if self.network.connected {
            "Network connected".to_string()
        } else if self.network.enabled {
            "Network searching".to_string()
        } else {
            "Network offline".to_string()
        }
    }

    fn setup_pages(&self) -> Vec<Value> {
        let mut pages = vec![setup_page("Power", "battery", self.power_setup_rows())];

        if self.network.enabled {
            pages.push(setup_page(
                "Network",
                "signal",
                if self.network.setup_network_rows.is_empty() {
                    vec![
                        SetupRow::new("Status", self.network_setup_status()),
                        SetupRow::new("Type", self.network.connection_type.to_uppercase()),
                        SetupRow::new("Signal", format!("{}/4", self.network.signal_strength)),
                        SetupRow::new("PPP", if self.network.connected { "Up" } else { "Down" }),
                    ]
                } else {
                    self.network.setup_network_rows.clone()
                },
            ));
            pages.push(setup_page(
                "GPS",
                "care",
                if self.network.setup_gps_rows.is_empty() {
                    vec![
                        SetupRow::new(
                            "Fix",
                            if self.network.gps_has_fix {
                                "Yes"
                            } else {
                                "Searching"
                            },
                        ),
                        SetupRow::new("Lat", "--"),
                        SetupRow::new("Lng", "--"),
                        SetupRow::new("Alt", "--"),
                        SetupRow::new("Speed", "--"),
                    ]
                } else {
                    self.network.setup_gps_rows.clone()
                },
            ));
        }

        pages.extend([
            setup_page(
                "Time",
                "clock",
                vec![
                    SetupRow::new("RTC", "Unknown"),
                    SetupRow::new("Alarm", "Unknown"),
                    SetupRow::new("Uptime", "--"),
                    SetupRow::new("Screen", "Awake"),
                ],
            ),
            setup_page(
                "Care",
                "care",
                vec![
                    SetupRow::new("Network", self.network_status_value()),
                    SetupRow::new(
                        "VoIP",
                        if self.call.registered {
                            "Ready"
                        } else {
                            "Offline"
                        },
                    ),
                    SetupRow::new(
                        "Media",
                        if self.media.connected {
                            "Connected"
                        } else {
                            "Offline"
                        },
                    ),
                    SetupRow::new("Watchdog", "Off"),
                ],
            ),
            setup_page(
                "Voice",
                "voice_note",
                vec![
                    SetupRow::new("Voice Cmds", "Unknown"),
                    SetupRow::new("AI Requests", "Unknown"),
                    SetupRow::new("Screen Read", "Unknown"),
                    SetupRow::new("Mic", "Unknown"),
                    SetupRow::new("Volume", "--"),
                ],
            ),
        ]);
        pages
    }

    fn network_setup_status(&self) -> &'static str {
        if self.network.connected {
            "Online"
        } else if self.network.enabled {
            "Registered"
        } else {
            "Disabled"
        }
    }

    fn network_status_value(&self) -> &'static str {
        if self.network.connected {
            "Connected"
        } else if self.network.enabled {
            "Searching"
        } else {
            "Offline"
        }
    }

    fn power_setup_rows(&self) -> Vec<SetupRow> {
        if !self.power.available {
            return vec![
                SetupRow::new("Source", self.power.source.clone()),
                SetupRow::new("Model", self.power_model_value()),
                SetupRow::new("Status", "Offline"),
                SetupRow::new("Reason", truncate(&self.power_error_value(), 18)),
                SetupRow::new("RTC", self.power.rtc_time.clone()),
                SetupRow::new("Alarm", self.power.alarm_text.clone()),
            ];
        }

        vec![
            SetupRow::new("Model", self.power_model_value()),
            SetupRow::new("Battery", self.power_battery_value()),
            SetupRow::new("Charging", self.power_charging_value()),
            SetupRow::new("External", self.power_external_value()),
            SetupRow::new("Voltage", self.power.voltage_text.clone()),
            SetupRow::new("RTC", self.power.rtc_time.clone()),
            SetupRow::new("Alarm", self.power.alarm_text.clone()),
        ]
    }

    fn power_battery_value(&self) -> String {
        if !self.power.battery_known {
            return "Unknown".to_string();
        }
        let suffix = if self.power.charging { " chg" } else { "" };
        format!("{}%{suffix}", self.power.battery_percent)
    }

    fn power_charging_value(&self) -> &'static str {
        if !self.power.charging_known {
            "Unknown"
        } else if self.power.charging {
            "Charging"
        } else {
            "Idle"
        }
    }

    fn power_external_value(&self) -> &'static str {
        if !self.power.external_power_known {
            "Unknown"
        } else if self.power.external_power {
            "Plugged"
        } else {
            "On battery"
        }
    }

    fn power_model_value(&self) -> String {
        if self.power.model.trim().is_empty() {
            "Unknown".to_string()
        } else {
            self.power.model.clone()
        }
    }

    fn power_error_value(&self) -> String {
        if self.power.error.trim().is_empty() {
            "Unavailable".to_string()
        } else {
            self.power.error.clone()
        }
    }

    pub fn status_payload(&self) -> Value {
        json!({
            "screen": {
                "current": self.current_screen,
            },
            "media": {
                "connected": self.media.connected,
                "playback_state": self.media.playback_state,
                "title": self.media.title,
                "artist": self.media.artist,
                "progress_permille": self.media.progress_permille,
                "volume": self.media.volume,
            },
            "voip": {
                "registered": self.call.registered,
                "registration_state": self.call.registration_state,
                "call_state": self.call.state.as_str(),
                "peer_name": self.call.peer_name,
                "peer_address": self.call.peer_address,
                "muted": self.call.muted,
            },
            "cloud": {
                "provisioning_state": self.cloud.provisioning_state,
                "cloud_state": self.cloud.cloud_state,
                "mqtt_connected": self.cloud.mqtt_connected,
                "last_error_summary": self.cloud.last_error_summary,
            },
            "power": {
                "available": self.power.available,
                "battery_percent": self.power.battery_percent,
                "charging": self.power.charging,
                "external_power": self.power.external_power,
                "source": self.power.source,
                "model": self.power.model,
                "error": self.power.error,
                "low_battery_warning_active": self.power.safety.low_battery_warning_active,
                "shutdown_pending": self.power.safety.shutdown_pending,
                "shutdown_reason": self.power.safety.shutdown_reason,
                "warning_threshold_percent": self.power.safety.config.low_battery_warning_percent,
                "critical_shutdown_percent": self.power.safety.config.critical_shutdown_percent,
                "shutdown_delay_seconds": self.power.safety.config.shutdown_delay_seconds,
                "shutdown_state_file": self.power.safety.config.shutdown_state_file,
            },
            "workers": {
                WorkerDomain::Ui.as_str(): worker_payload(&self.ui),
                WorkerDomain::Cloud.as_str(): worker_payload(&self.cloud_worker),
                WorkerDomain::Media.as_str(): worker_payload(&self.media_worker),
                WorkerDomain::Voip.as_str(): worker_payload(&self.voip_worker),
                WorkerDomain::Network.as_str(): worker_payload(&self.network_worker),
                WorkerDomain::Power.as_str(): worker_payload(&self.power_worker),
                WorkerDomain::Voice.as_str(): worker_payload(&self.voice_worker),
            },
            "loop": {
                "iterations": self.loop_iterations,
                "last_duration_ms": self.last_loop_duration_ms,
            },
        })
    }
}

fn string_field(value: &Value, key: &str) -> Option<String> {
    value.get(key).and_then(Value::as_str).map(str::to_string)
}

fn string_array_field(value: &Value, key: &str) -> Vec<String> {
    value
        .get(key)
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::trim)
                .filter(|item| !item.is_empty())
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default()
}

fn i32_field(value: &Value, key: &str) -> Option<i32> {
    let raw = value.get(key)?.as_i64()?;
    i32::try_from(raw).ok()
}

fn f64_field(value: &Value, key: &str) -> Option<f64> {
    let value = value.get(key)?;
    value
        .as_f64()
        .or_else(|| value.as_str()?.trim().parse::<f64>().ok())
}

fn i64_field(value: &Value, key: &str) -> Option<i64> {
    value.get(key)?.as_i64()
}

fn u64_field(value: &Value, key: &str) -> Option<u64> {
    value.get(key)?.as_u64()
}

fn first_artist(track: &Value) -> Option<String> {
    track
        .get("artists")
        .and_then(Value::as_array)
        .and_then(|artists| artists.first())
        .and_then(Value::as_str)
        .map(str::to_string)
        .or_else(|| string_field(track, "artist"))
}

fn playlist_track_count_subtitle(value: &Value, icon_key: &str) -> Option<String> {
    if icon_key != "playlist" {
        return None;
    }

    let track_count = value.get("track_count")?.as_u64()?;
    let suffix = if track_count == 1 { "track" } else { "tracks" };
    Some(format!("{track_count} {suffix}"))
}

fn derived_progress_permille(snapshot: &Value, track: &Value) -> Option<i32> {
    let position_ms = i64_field(snapshot, "time_position_ms")?;
    let length_ms = i64_field(track, "length_ms")?;
    if length_ms <= 0 {
        return None;
    }

    let permille = ((position_ms as i128) * 1000 / (length_ms as i128)).clamp(0, 1000);
    i32::try_from(permille).ok()
}

fn call_duration_text(snapshot: &Value, call_state: CallState) -> Option<String> {
    if call_state != CallState::Active {
        return None;
    }

    snapshot
        .get("call_session")
        .and_then(|session| u64_field(session, "duration_seconds"))
        .map(format_duration_text)
}

fn recent_call_history_item(value: &Value, contacts: &[ListItem]) -> Option<ListItem> {
    let peer_sip_address = string_field(value, "peer_sip_address")?;
    if peer_sip_address.is_empty() {
        return None;
    }

    let outcome = string_field(value, "outcome").unwrap_or_default();
    let duration_seconds = u64_field(value, "duration_seconds").unwrap_or(0);
    let title = contacts
        .iter()
        .find(|contact| contact.id == peer_sip_address)
        .map(|contact| contact.title.clone())
        .unwrap_or_else(|| peer_sip_address.clone());
    let subtitle = match outcome.as_str() {
        "missed" => "Missed call".to_string(),
        "completed" if duration_seconds > 0 => {
            format!("Call {}", format_duration_text(duration_seconds))
        }
        "completed" => "Call done".to_string(),
        "rejected" => "Rejected".to_string(),
        "failed" => "Failed".to_string(),
        "cancelled" | "canceled" => "Cancelled".to_string(),
        _ => String::new(),
    };
    let direction = string_field(value, "direction").unwrap_or_default();
    let icon_key = if direction == "outgoing" {
        "call"
    } else {
        "talk"
    };

    Some(ListItem {
        id: peer_sip_address.clone(),
        title,
        subtitle,
        icon_key: icon_key.to_string(),
        aliases: Vec::new(),
    })
}

fn format_duration_text(total_seconds: u64) -> String {
    let hours = total_seconds / 3600;
    let minutes = (total_seconds % 3600) / 60;
    let seconds = total_seconds % 60;

    if hours > 0 {
        format!("{hours}:{minutes:02}:{seconds:02}")
    } else {
        format!("{minutes:02}:{seconds:02}")
    }
}

fn list_payload(items: &[ListItem]) -> Vec<Value> {
    items.iter().map(ListItem::to_payload).collect()
}

fn setup_page(title: &str, icon_key: &str, rows: Vec<SetupRow>) -> Value {
    json!({
        "title": title,
        "icon_key": icon_key,
        "rows": rows.into_iter().map(|row| row.formatted()).collect::<Vec<_>>(),
    })
}

fn setup_rows(value: Option<&Value>) -> Option<Vec<SetupRow>> {
    let rows = value?.as_array()?;
    let parsed = rows
        .iter()
        .filter_map(|row| {
            let values = row.as_array()?;
            if values.len() != 2 {
                return None;
            }
            Some(SetupRow::new(
                values[0].as_str().unwrap_or_default(),
                values[1].as_str().unwrap_or_default(),
            ))
        })
        .collect::<Vec<_>>();
    Some(parsed)
}

fn format_voltage_text(voltage: Option<f64>, temperature: Option<f64>) -> String {
    match (voltage, temperature) {
        (Some(voltage), Some(temperature)) if voltage.is_finite() && temperature.is_finite() => {
            format!("{voltage:.2}V {temperature:.0}C")
        }
        (Some(voltage), _) if voltage.is_finite() => format!("{voltage:.2} V"),
        (_, Some(temperature)) if temperature.is_finite() => format!("{temperature:.1} C"),
        _ => "Unknown".to_string(),
    }
}

fn compact_datetime_text(value: &str) -> String {
    let value = value.trim();
    if value.len() >= 16 && value.as_bytes().get(10) == Some(&b'T') {
        format!("{} {}", &value[5..10], &value[11..16])
    } else {
        value.to_string()
    }
}

fn compact_time_text(value: &str) -> String {
    let value = value.trim();
    if value.len() >= 16 && value.as_bytes().get(10) == Some(&b'T') {
        value[11..16].to_string()
    } else {
        value.to_string()
    }
}

fn truncate(value: &str, max_length: usize) -> String {
    if value.len() <= max_length {
        value.to_string()
    } else if max_length <= 3 {
        value.chars().take(max_length).collect()
    } else {
        format!(
            "{}...",
            value.chars().take(max_length - 3).collect::<String>()
        )
    }
}

fn voice_note_summary_from_value(value: &Value) -> Option<VoiceNoteSummary> {
    if !value.is_object() {
        return None;
    }

    Some(VoiceNoteSummary {
        message_id: string_field(value, "message_id").unwrap_or_default(),
        direction: string_field(value, "direction").unwrap_or_default(),
        delivery_state: string_field(value, "delivery_state").unwrap_or_default(),
        local_file_path: string_field(value, "local_file_path").unwrap_or_default(),
        duration_ms: i32_field(value, "duration_ms").unwrap_or(0).max(0),
        unread: value
            .get("unread")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        display_name: string_field(value, "display_name").unwrap_or_default(),
    })
}

fn voice_note_summary_payload(summaries: &BTreeMap<String, VoiceNoteSummary>) -> Value {
    Value::Object(
        summaries
            .iter()
            .map(|(key, summary)| (key.clone(), summary.to_payload()))
            .collect(),
    )
}

fn voice_status_text(phase: &str) -> String {
    match phase {
        "recording" => "Recording...".to_string(),
        "review" => "Ready to send".to_string(),
        "sending" => "Sending...".to_string(),
        "sent" => "Sent".to_string(),
        "failed" => "Couldn't send".to_string(),
        _ => String::new(),
    }
}

fn voice_body_text(voice: &VoiceRuntimeState) -> String {
    if matches!(
        voice.phase.as_str(),
        "idle" | "listening" | "thinking" | "reply"
    ) {
        voice.body.clone()
    } else if voice.status_text.trim().is_empty() {
        voice_status_text(&voice.phase)
    } else {
        voice.status_text.clone()
    }
}

fn trim_ask_history_text(text: &str, limit: usize) -> String {
    text.split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(limit.max(1))
        .collect()
}

fn screen_for_voice_route(route_name: &str) -> Option<&'static str> {
    match normalized(route_name).as_str() {
        "open_talk" => Some("talk"),
        "open_listen" => Some("listen"),
        "open_setup" => Some("power"),
        "go_home" => Some("hub"),
        _ => None,
    }
}

const VOICE_CALL_HINT_TOKENS: &[&str] = &["call", "dial", "phone", "ring"];
const VOICE_NEGATION_TOKENS: &[&str] = &[
    "no", "not", "never", "dont", "don't", "cant", "can't", "cannot", "wont", "won't",
];

fn infer_voice_call_confirmation(
    state: &RuntimeState,
    transcript: &str,
) -> Option<VoiceCallConfirmation> {
    let activation = normalize_voice_activation(
        transcript,
        &state.voice.command_settings.activation_prefixes,
    );
    let tokens = voice_command_tokens(&activation.normalized_text);
    if tokens.is_empty()
        || !tokens
            .iter()
            .any(|token| VOICE_CALL_HINT_TOKENS.contains(&token.as_str()))
        || tokens
            .iter()
            .any(|token| VOICE_NEGATION_TOKENS.contains(&token.as_str()))
    {
        return None;
    }

    for contact in &state.call.contacts {
        let mut labels = contact_labels(contact);
        labels.sort_by_key(|label| std::cmp::Reverse(label.len()));
        for label in labels {
            let label_tokens = voice_command_tokens(&label);
            if !label_tokens.is_empty()
                && label_tokens
                    .iter()
                    .all(|label_token| tokens.contains(label_token))
            {
                return Some(VoiceCallConfirmation {
                    spoken_name: label,
                    display_name: contact.title.clone(),
                });
            }
        }
    }
    None
}

fn voice_command_tokens(text: &str) -> Vec<String> {
    let mut tokens = Vec::new();
    let mut current = String::new();
    for character in text.chars() {
        if character.is_ascii_alphanumeric() || character == '\'' {
            current.push(character.to_ascii_lowercase());
        } else if !current.is_empty() {
            tokens.push(std::mem::take(&mut current));
        }
    }
    if !current.is_empty() {
        tokens.push(current);
    }
    tokens
}

fn voice_command_outcome(
    state: &RuntimeState,
    intent: VoiceCommandIntent,
    contact_name: &str,
) -> Option<VoiceCommandOutcome> {
    match intent {
        VoiceCommandIntent::PlayMusic => Some(VoiceCommandOutcome {
            headline: "Playing".to_string(),
            body: "Starting local music.".to_string(),
        }),
        VoiceCommandIntent::CallContact => match find_contact(state, contact_name) {
            Some(contact) => Some(VoiceCommandOutcome {
                headline: "Calling".to_string(),
                body: format!("Calling {}.", contact.title),
            }),
            None => Some(VoiceCommandOutcome {
                headline: "No Match".to_string(),
                body: format!("I could not find {contact_name}."),
            }),
        },
        VoiceCommandIntent::VolumeUp => Some(volume_outcome(state.media.volume + 10)),
        VoiceCommandIntent::VolumeDown => Some(volume_outcome(state.media.volume - 10)),
        VoiceCommandIntent::ReadScreen => Some(VoiceCommandOutcome {
            headline: "Screen Read".to_string(),
            body: "You are on Ask. Say a direct command now.".to_string(),
        }),
        VoiceCommandIntent::MuteMic => Some(VoiceCommandOutcome {
            headline: "Mic Muted".to_string(),
            body: "Voice commands mic is muted.".to_string(),
        }),
        VoiceCommandIntent::UnmuteMic => Some(VoiceCommandOutcome {
            headline: "Mic Live".to_string(),
            body: "Voice commands mic is live.".to_string(),
        }),
        VoiceCommandIntent::Unknown => None,
    }
}

fn volume_outcome(volume: i32) -> VoiceCommandOutcome {
    let volume = volume.clamp(0, 100);
    let level = ((volume as f64) / 10.0).round() as i32;
    VoiceCommandOutcome {
        headline: "Volume".to_string(),
        body: format!("Volume is {level} out of 10."),
    }
}

fn find_contact<'a>(state: &'a RuntimeState, spoken_name: &str) -> Option<&'a ListItem> {
    let spoken_name = normalize_contact_label(spoken_name);
    if spoken_name.is_empty() {
        return None;
    }

    state.call.contacts.iter().find(|contact| {
        contact_labels(contact)
            .iter()
            .any(|label| label == &spoken_name)
    })
}

fn contact_labels(contact: &ListItem) -> Vec<String> {
    let mut labels = vec![
        normalize_contact_label(&contact.title),
        normalize_contact_label(&contact.subtitle),
        normalize_contact_label(&contact.id),
    ];
    labels.extend(
        contact
            .aliases
            .iter()
            .map(|alias| normalize_contact_label(alias)),
    );
    labels.retain(|label| !label.is_empty());

    if labels
        .iter()
        .any(|label| ["mom", "mama", "mum", "mommy", "mother"].contains(&label.as_str()))
    {
        labels.extend(
            ["mom", "mama", "mum", "mommy", "mother"]
                .iter()
                .map(|label| (*label).to_string()),
        );
    }
    if labels
        .iter()
        .any(|label| ["dad", "dada", "daddy", "papa", "father"].contains(&label.as_str()))
    {
        labels.extend(
            ["dad", "dada", "daddy", "papa", "father"]
                .iter()
                .map(|label| (*label).to_string()),
        );
    }

    labels.sort();
    labels.dedup();
    labels
}

fn normalize_contact_label(value: &str) -> String {
    value
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
        .to_ascii_lowercase()
}

fn current_millis() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default()
}

fn current_epoch_seconds() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_secs())
        .unwrap_or_default()
}

fn seconds_to_u64_ceiling(seconds: f64) -> u64 {
    if !seconds.is_finite() || seconds <= 0.0 {
        0
    } else {
        seconds.ceil() as u64
    }
}

fn normalized(value: &str) -> String {
    value.trim().to_ascii_lowercase()
}

fn worker_payload(worker: &WorkerHealth) -> Value {
    json!({
        "state": worker.state.as_str(),
        "restart_count": worker.restart_count,
        "protocol_errors": worker.protocol_errors,
        "last_reason": worker.last_reason,
    })
}
