use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeSnapshot {
    #[serde(default = "default_app_state")]
    pub app_state: String,
    #[serde(default)]
    pub hub: HubRuntimeSnapshot,
    #[serde(default)]
    pub music: MusicRuntimeSnapshot,
    #[serde(default)]
    pub call: CallRuntimeSnapshot,
    #[serde(default)]
    pub voice: VoiceRuntimeSnapshot,
    #[serde(default)]
    pub power: PowerRuntimeSnapshot,
    #[serde(default)]
    pub network: NetworkRuntimeSnapshot,
    #[serde(default)]
    pub overlay: OverlayRuntimeSnapshot,
}

impl Default for RuntimeSnapshot {
    fn default() -> Self {
        Self {
            app_state: default_app_state(),
            hub: HubRuntimeSnapshot::default(),
            music: MusicRuntimeSnapshot::default(),
            call: CallRuntimeSnapshot::default(),
            voice: VoiceRuntimeSnapshot::default(),
            power: PowerRuntimeSnapshot::default(),
            network: NetworkRuntimeSnapshot::default(),
            overlay: OverlayRuntimeSnapshot::default(),
        }
    }
}

impl RuntimeSnapshot {
    pub fn from_payload(payload: &Value) -> Result<Self> {
        serde_json::from_value(payload.clone()).context("decoding UI runtime snapshot")
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HubRuntimeSnapshot {
    #[serde(default = "default_hub_cards")]
    pub cards: Vec<HubCardSnapshot>,
}

impl Default for HubRuntimeSnapshot {
    fn default() -> Self {
        Self {
            cards: default_hub_cards(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct HubCardSnapshot {
    pub key: String,
    pub title: String,
    #[serde(default)]
    pub subtitle: String,
    #[serde(default = "default_hub_accent")]
    pub accent: u32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct MusicRuntimeSnapshot {
    #[serde(default)]
    pub playing: bool,
    #[serde(default)]
    pub paused: bool,
    #[serde(default = "default_music_title")]
    pub title: String,
    #[serde(default)]
    pub artist: String,
    #[serde(default)]
    pub progress_permille: i32,
    #[serde(default)]
    pub playlists: Vec<ListItemSnapshot>,
    #[serde(default)]
    pub recent_tracks: Vec<ListItemSnapshot>,
}

impl Default for MusicRuntimeSnapshot {
    fn default() -> Self {
        Self {
            playing: false,
            paused: false,
            title: default_music_title(),
            artist: String::new(),
            progress_permille: 0,
            playlists: Vec::new(),
            recent_tracks: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CallRuntimeSnapshot {
    #[serde(default = "default_call_state")]
    pub state: String,
    #[serde(default)]
    pub peer_name: String,
    #[serde(default)]
    pub peer_address: String,
    #[serde(default)]
    pub duration_text: String,
    #[serde(default)]
    pub muted: bool,
    #[serde(default)]
    pub contacts: Vec<ListItemSnapshot>,
    #[serde(default)]
    pub history: Vec<ListItemSnapshot>,
}

impl Default for CallRuntimeSnapshot {
    fn default() -> Self {
        Self {
            state: default_call_state(),
            peer_name: String::new(),
            peer_address: String::new(),
            duration_text: String::new(),
            muted: false,
            contacts: Vec::new(),
            history: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VoiceRuntimeSnapshot {
    #[serde(default = "default_voice_phase")]
    pub phase: String,
    #[serde(default = "default_voice_headline")]
    pub headline: String,
    #[serde(default = "default_voice_body")]
    pub body: String,
    #[serde(default)]
    pub capture_in_flight: bool,
    #[serde(default)]
    pub ptt_active: bool,
}

impl Default for VoiceRuntimeSnapshot {
    fn default() -> Self {
        Self {
            phase: default_voice_phase(),
            headline: default_voice_headline(),
            body: default_voice_body(),
            capture_in_flight: false,
            ptt_active: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PowerRuntimeSnapshot {
    #[serde(default = "default_battery_percent")]
    pub battery_percent: i32,
    #[serde(default)]
    pub charging: bool,
    #[serde(default)]
    pub power_available: bool,
    #[serde(default)]
    pub rows: Vec<String>,
}

impl Default for PowerRuntimeSnapshot {
    fn default() -> Self {
        Self {
            battery_percent: default_battery_percent(),
            charging: false,
            power_available: true,
            rows: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NetworkRuntimeSnapshot {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub connected: bool,
    #[serde(default)]
    pub signal_strength: i32,
    #[serde(default)]
    pub gps_has_fix: bool,
}

impl Default for NetworkRuntimeSnapshot {
    fn default() -> Self {
        Self {
            enabled: false,
            connected: false,
            signal_strength: 0,
            gps_has_fix: false,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct OverlayRuntimeSnapshot {
    #[serde(default)]
    pub loading: bool,
    #[serde(default)]
    pub error: String,
    #[serde(default)]
    pub message: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ListItemSnapshot {
    pub id: String,
    pub title: String,
    #[serde(default)]
    pub subtitle: String,
    #[serde(default)]
    pub icon_key: String,
}

impl ListItemSnapshot {
    pub fn new(
        id: impl Into<String>,
        title: impl Into<String>,
        subtitle: impl Into<String>,
        icon_key: impl Into<String>,
    ) -> Self {
        Self {
            id: id.into(),
            title: title.into(),
            subtitle: subtitle.into(),
            icon_key: icon_key.into(),
        }
    }
}

fn default_app_state() -> String {
    "hub".to_string()
}

fn default_call_state() -> String {
    "idle".to_string()
}

fn default_voice_phase() -> String {
    "idle".to_string()
}

fn default_voice_headline() -> String {
    "Ask".to_string()
}

fn default_voice_body() -> String {
    "Ask me anything...".to_string()
}

fn default_music_title() -> String {
    "Nothing Playing".to_string()
}

fn default_battery_percent() -> i32 {
    100
}

fn default_hub_accent() -> u32 {
    0x00FF88
}

fn default_hub_cards() -> Vec<HubCardSnapshot> {
    vec![
        HubCardSnapshot {
            key: "listen".to_string(),
            title: "Listen".to_string(),
            subtitle: String::new(),
            accent: 0x00FF88,
        },
        HubCardSnapshot {
            key: "talk".to_string(),
            title: "Talk".to_string(),
            subtitle: String::new(),
            accent: 0x00D4FF,
        },
        HubCardSnapshot {
            key: "ask".to_string(),
            title: "Ask".to_string(),
            subtitle: String::new(),
            accent: 0xFFD000,
        },
        HubCardSnapshot {
            key: "setup".to_string(),
            title: "Setup".to_string(),
            subtitle: String::new(),
            accent: 0x9CA3AF,
        },
    ]
}
