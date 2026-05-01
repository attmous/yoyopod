use serde_json::{json, Value};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum WorkerDomain {
    Ui,
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

        Some(Self {
            id,
            title,
            subtitle,
            icon_key: icon_key.to_string(),
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
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RuntimeState {
    pub current_screen: String,
    pub media: MediaState,
    pub call: CallRuntimeState,
    pub ui: WorkerHealth,
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
            ui: WorkerHealth::default(),
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

    fn worker_health_mut(&mut self, domain: WorkerDomain) -> &mut WorkerHealth {
        match domain {
            WorkerDomain::Ui => &mut self.ui,
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
                .filter_map(recent_call_history_item)
                .collect();
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
            },
            "voice": {
                "phase": "idle",
                "headline": "Ask",
                "body": "Ask me anything...",
                "capture_in_flight": false,
                "ptt_active": false,
            },
            "power": {
                "battery_percent": 100,
                "charging": false,
                "power_available": true,
                "rows": self.power_rows(),
            },
            "network": {
                "enabled": false,
                "connected": false,
                "signal_strength": 0,
                "gps_has_fix": false,
            },
            "overlay": {
                "loading": false,
                "error": "",
                "message": "",
            },
            "workers": {
                WorkerDomain::Ui.as_str(): worker_payload(&self.ui),
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
            "Network offline".to_string(),
            if self.call.registered {
                "VoIP ready".to_string()
            } else {
                "VoIP offline".to_string()
            },
        ]
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
            "workers": {
                WorkerDomain::Ui.as_str(): worker_payload(&self.ui),
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

fn recent_call_history_item(value: &Value) -> Option<ListItem> {
    let peer_sip_address = string_field(value, "peer_sip_address")?;
    if peer_sip_address.is_empty() {
        return None;
    }

    let direction = string_field(value, "direction").unwrap_or_default();
    let outcome = string_field(value, "outcome").unwrap_or_default();
    let duration = u64_field(value, "duration_seconds")
        .map(format_duration_text)
        .unwrap_or_else(|| format_duration_text(0));
    let subtitle = [direction, outcome, duration]
        .into_iter()
        .filter(|part| !part.is_empty())
        .collect::<Vec<_>>()
        .join(" ");

    Some(ListItem {
        id: peer_sip_address.clone(),
        title: peer_sip_address,
        subtitle,
        icon_key: "call".to_string(),
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

fn worker_payload(worker: &WorkerHealth) -> Value {
    json!({
        "state": worker.state.as_str(),
        "restart_count": worker.restart_count,
        "protocol_errors": worker.protocol_errors,
        "last_reason": worker.last_reason,
    })
}
