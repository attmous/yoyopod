use std::collections::BTreeMap;
use std::path::Path;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};

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
        })
    }

    fn to_payload(&self) -> Value {
        json!({
            "id": self.id,
            "title": self.title,
            "subtitle": self.subtitle,
            "icon_key": self.icon_key,
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
    pub status_text: String,
    pub file_path: String,
    pub duration_ms: i32,
    pub mime_type: String,
    pub message_id: String,
    pub playback_active: bool,
    pub playback_file_path: String,
    pub voice_note_store_dir: String,
}

impl Default for VoiceRuntimeState {
    fn default() -> Self {
        Self {
            phase: "idle".to_string(),
            status_text: String::new(),
            file_path: String::new(),
            duration_ms: 0,
            mime_type: "audio/wav".to_string(),
            message_id: String::new(),
            playback_active: false,
            playback_file_path: String::new(),
            voice_note_store_dir: "data/communication/voice_notes".to_string(),
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

    fn reset_draft(&mut self) {
        let store_dir = self.voice_note_store_dir.clone();
        *self = Self {
            voice_note_store_dir: store_dir,
            ..Self::default()
        };
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

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeState {
    pub current_screen: String,
    pub media: MediaState,
    pub call: CallRuntimeState,
    pub voice: VoiceRuntimeState,
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
            self.apply_voice_note_snapshot(voice_note);
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
                "headline": "Ask",
                "body": voice_body_text(&self.voice),
                "capture_in_flight": self.voice.phase == "recording",
                "ptt_active": self.voice.phase == "recording",
            },
            "power": {
                "battery_percent": 100,
                "charging": false,
                "power_available": true,
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
            "Battery 100%".to_string(),
            "On battery".to_string(),
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
        let mut pages = vec![setup_page(
            "Power",
            "battery",
            vec![
                SetupRow::new("Battery", "100%"),
                SetupRow::new("Charging", "On battery"),
                SetupRow::new("External", "Available"),
            ],
        )];

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

fn i32_field(value: &Value, key: &str) -> Option<i32> {
    let raw = value.get(key)?.as_i64()?;
    i32::try_from(raw).ok()
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
    if voice.phase == "idle" {
        "Ask me anything...".to_string()
    } else if voice.status_text.trim().is_empty() {
        voice_status_text(&voice.phase)
    } else {
        voice.status_text.clone()
    }
}

fn current_millis() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_millis())
        .unwrap_or_default()
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
