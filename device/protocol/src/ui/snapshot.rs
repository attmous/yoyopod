use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::BTreeMap;

use super::UiScreen;
use crate::ProtocolError;

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct RuntimeSnapshot {
    #[serde(default = "default_app_state")]
    pub app_state: UiScreen,
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
    pub settings: SettingsRuntimeSnapshot,
    #[serde(default)]
    pub network: NetworkRuntimeSnapshot,
    #[serde(default)]
    pub wifi_setup: WifiSetupRuntimeSnapshot,
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
            settings: SettingsRuntimeSnapshot::default(),
            network: NetworkRuntimeSnapshot::default(),
            wifi_setup: WifiSetupRuntimeSnapshot::default(),
            overlay: OverlayRuntimeSnapshot::default(),
        }
    }
}

impl RuntimeSnapshot {
    pub fn from_payload(payload: &Value) -> Result<Self, ProtocolError> {
        serde_json::from_value(payload.clone()).map_err(|error| {
            ProtocolError::InvalidEnvelope(format!("invalid UI runtime snapshot: {error}"))
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "domain", content = "snapshot", rename_all = "snake_case")]
pub enum RuntimeSnapshotPatch {
    Full(RuntimeSnapshot),
    AppState(UiScreen),
    Hub(HubRuntimeSnapshot),
    Music(MusicRuntimeSnapshot),
    Call(CallRuntimeSnapshot),
    Voice(VoiceRuntimeSnapshot),
    Power(PowerRuntimeSnapshot),
    Settings(SettingsRuntimeSnapshot),
    Network(NetworkRuntimeSnapshot),
    WifiSetup(WifiSetupRuntimeSnapshot),
    Overlay(OverlayRuntimeSnapshot),
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeSnapshotDomain {
    Full,
    AppState,
    Hub,
    Music,
    Call,
    Voice,
    Power,
    Settings,
    Network,
    WifiSetup,
    Overlay,
}

impl RuntimeSnapshotPatch {
    pub fn from_payload(payload: &Value) -> Result<Self, ProtocolError> {
        serde_json::from_value(payload.clone()).map_err(|error| {
            ProtocolError::InvalidEnvelope(format!("invalid UI runtime patch: {error}"))
        })
    }

    pub const fn domain(&self) -> RuntimeSnapshotDomain {
        match self {
            Self::Full(_) => RuntimeSnapshotDomain::Full,
            Self::AppState(_) => RuntimeSnapshotDomain::AppState,
            Self::Hub(_) => RuntimeSnapshotDomain::Hub,
            Self::Music(_) => RuntimeSnapshotDomain::Music,
            Self::Call(_) => RuntimeSnapshotDomain::Call,
            Self::Voice(_) => RuntimeSnapshotDomain::Voice,
            Self::Power(_) => RuntimeSnapshotDomain::Power,
            Self::Settings(_) => RuntimeSnapshotDomain::Settings,
            Self::Network(_) => RuntimeSnapshotDomain::Network,
            Self::WifiSetup(_) => RuntimeSnapshotDomain::WifiSetup,
            Self::Overlay(_) => RuntimeSnapshotDomain::Overlay,
        }
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
    #[serde(default = "default_music_time_text")]
    pub elapsed_text: String,
    #[serde(default = "default_music_time_text")]
    pub total_text: String,
    #[serde(default)]
    pub playlists: Vec<ListItemSnapshot>,
    #[serde(default)]
    pub playlist_tracks: BTreeMap<String, Vec<ListItemSnapshot>>,
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
            elapsed_text: default_music_time_text(),
            total_text: default_music_time_text(),
            playlists: Vec::new(),
            playlist_tracks: BTreeMap::new(),
            recent_tracks: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct SettingsRuntimeSnapshot {
    #[serde(default = "default_volume_level")]
    pub volume_level: i32,
    #[serde(default = "default_companion")]
    pub companion: String,
    #[serde(default = "default_theme")]
    pub theme: String,
    #[serde(default = "default_speak_names")]
    pub speak_names: bool,
    #[serde(default = "default_device_name")]
    pub device_name: String,
    #[serde(default = "default_firmware_version")]
    pub firmware_version: String,
}

impl Default for SettingsRuntimeSnapshot {
    fn default() -> Self {
        Self {
            volume_level: default_volume_level(),
            companion: default_companion(),
            theme: default_theme(),
            speak_names: default_speak_names(),
            device_name: default_device_name(),
            firmware_version: default_firmware_version(),
        }
    }
}

fn default_music_time_text() -> String {
    "--:--".to_string()
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct CallRuntimeSnapshot {
    #[serde(default = "default_call_state")]
    pub state: String,
    #[serde(default)]
    pub registered: bool,
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
    #[serde(default)]
    pub unread_voice_notes_by_contact: BTreeMap<String, usize>,
    #[serde(default)]
    pub latest_voice_note_by_contact: BTreeMap<String, VoiceNoteSummarySnapshot>,
    #[serde(default)]
    pub voice_notes_by_contact: BTreeMap<String, Vec<VoiceNoteSummarySnapshot>>,
}

impl Default for CallRuntimeSnapshot {
    fn default() -> Self {
        Self {
            state: default_call_state(),
            registered: false,
            peer_name: String::new(),
            peer_address: String::new(),
            duration_text: String::new(),
            muted: false,
            contacts: Vec::new(),
            history: Vec::new(),
            unread_voice_notes_by_contact: BTreeMap::new(),
            latest_voice_note_by_contact: BTreeMap::new(),
            voice_notes_by_contact: BTreeMap::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct VoiceNoteSummarySnapshot {
    #[serde(default)]
    pub message_id: String,
    #[serde(default)]
    pub direction: String,
    #[serde(default)]
    pub delivery_state: String,
    #[serde(default)]
    pub local_file_path: String,
    #[serde(default)]
    pub duration_ms: i32,
    #[serde(default)]
    pub unread: bool,
    #[serde(default)]
    pub display_name: String,
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
    pub ask_unavailable: bool,
    #[serde(default)]
    pub capture_in_flight: bool,
    #[serde(default)]
    pub ptt_active: bool,
    #[serde(default)]
    pub recording_duration_ms: i32,
    #[serde(default)]
    pub capture_level_permille: i32,
    #[serde(default)]
    pub playback_active: bool,
    #[serde(default)]
    pub playback_paused: bool,
    #[serde(default)]
    pub playback_file_path: String,
    #[serde(default)]
    pub playback_elapsed_ms: i32,
    #[serde(default)]
    pub playback_duration_ms: i32,
}

impl Default for VoiceRuntimeSnapshot {
    fn default() -> Self {
        Self {
            phase: default_voice_phase(),
            headline: default_voice_headline(),
            body: default_voice_body(),
            ask_unavailable: false,
            capture_in_flight: false,
            ptt_active: false,
            recording_duration_ms: 0,
            capture_level_permille: 0,
            playback_active: false,
            playback_paused: false,
            playback_file_path: String::new(),
            playback_elapsed_ms: 0,
            playback_duration_ms: 0,
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
    #[serde(default)]
    pub pages: Vec<PowerPageSnapshot>,
}

impl Default for PowerRuntimeSnapshot {
    fn default() -> Self {
        Self {
            battery_percent: default_battery_percent(),
            charging: false,
            power_available: true,
            rows: Vec::new(),
            pages: Vec::new(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PowerPageSnapshot {
    pub title: String,
    #[serde(default = "default_power_icon")]
    pub icon_key: String,
    #[serde(default)]
    pub rows: Vec<String>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct NetworkRuntimeSnapshot {
    #[serde(default)]
    pub enabled: bool,
    #[serde(default)]
    pub connected: bool,
    #[serde(default = "default_connection_type")]
    pub connection_type: String,
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
            connection_type: default_connection_type(),
            signal_strength: 0,
            gps_has_fix: false,
        }
    }
}

/// Transient state for the on-device Wi‑Fi onboarding flow (AP mode + captive
/// portal). Populated by the runtime from `wifi_provisioning_state` events sent
/// by the network worker. The `ap_password` is the *hotspot* password shown to
/// the user (encoded in the on-screen QR) — never the user's home-network
/// password, which is never surfaced in a snapshot.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WifiSetupRuntimeSnapshot {
    #[serde(default)]
    pub active: bool,
    #[serde(default = "default_wifi_setup_phase")]
    pub phase: String,
    #[serde(default)]
    pub ap_ssid: String,
    #[serde(default)]
    pub ap_password: String,
    #[serde(default)]
    pub portal_url: String,
    #[serde(default)]
    pub qr_payload: String,
    #[serde(default)]
    pub status_text: String,
    #[serde(default)]
    pub error: String,
}

impl Default for WifiSetupRuntimeSnapshot {
    fn default() -> Self {
        Self {
            active: false,
            phase: default_wifi_setup_phase(),
            ap_ssid: String::new(),
            ap_password: String::new(),
            portal_url: String::new(),
            qr_payload: String::new(),
            status_text: String::new(),
            error: String::new(),
        }
    }
}

fn default_wifi_setup_phase() -> String {
    "idle".to_string()
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize, Default)]
pub struct OverlayRuntimeSnapshot {
    #[serde(default)]
    pub loading: bool,
    #[serde(default)]
    pub error: String,
    #[serde(default)]
    pub message: String,
    #[serde(default)]
    pub retryable: bool,
    #[serde(default)]
    pub code: String,
    #[serde(default)]
    pub source: String,
    #[serde(default)]
    pub retry_count: u8,
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

fn default_app_state() -> UiScreen {
    UiScreen::Hub
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

fn default_power_icon() -> String {
    "battery".to_string()
}

fn default_connection_type() -> String {
    "none".to_string()
}

fn default_volume_level() -> i32 {
    5
}
fn default_companion() -> String {
    "Bunny".to_string()
}
fn default_theme() -> String {
    "Light".to_string()
}
fn default_speak_names() -> bool {
    true
}
fn default_device_name() -> String {
    "yoyopod".to_string()
}
fn default_firmware_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
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
