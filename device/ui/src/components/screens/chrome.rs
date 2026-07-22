use yoyopod_protocol::ui::{ListItemSnapshot, RuntimeSnapshot, UiScreen};

use crate::components::widgets::{deck_bar, status_bar, DeckBarProps, StatusBarProps};
use crate::engine::{Element, Key};
use crate::scene::roles;
use crate::scene::{HudBattery, HudConnectivity, HudConnectivityKind, HudScene, HudStatus};
use crate::ElementKind;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScreenChrome {
    pub title: String,
    pub status: HudStatus,
    pub status_opacity: u8,
    pub deck: DeckBarProps,
}

pub fn chrome_for_screen(
    screen: UiScreen,
    snapshot: &RuntimeSnapshot,
    focus_index: usize,
    selected_playlist: Option<&ListItemSnapshot>,
    selected_contact: Option<&ListItemSnapshot>,
    home_focus: Option<usize>,
    deck_visible: bool,
) -> ScreenChrome {
    let capture_dimmed = (screen == UiScreen::TalkContact || screen == UiScreen::Ask)
        && (snapshot.voice.ptt_active
            || snapshot.voice.capture_in_flight
            || matches!(
                snapshot.voice.phase.trim().to_ascii_lowercase().as_str(),
                "recording" | "listening"
            ));
    ScreenChrome {
        title: title_for_screen(
            screen,
            snapshot,
            focus_index,
            selected_playlist,
            selected_contact,
        ),
        status: status_from_snapshot(snapshot),
        status_opacity: if capture_dimmed { 140 } else { 255 },
        deck: DeckBarProps {
            focused_index: deck_focus_for_screen(screen, home_focus),
            visible: deck_visible,
            opacity: if matches!(
                screen,
                UiScreen::IncomingCall | UiScreen::OutgoingCall | UiScreen::InCall
            ) {
                140
            } else if capture_dimmed {
                140
            } else {
                255
            },
        },
    }
}

pub fn hud_scene(chrome: ScreenChrome) -> HudScene {
    HudScene::new(
        Element::new(ElementKind::Container, Some(roles::HUD))
            .key(Key::Static("hud"))
            .child(status_bar(&StatusBarProps {
                status: chrome.status,
                opacity: chrome.status_opacity,
            }))
            .child(deck_bar(&chrome.deck)),
    )
}

fn title_for_screen(
    screen: UiScreen,
    snapshot: &RuntimeSnapshot,
    focus_index: usize,
    selected_playlist: Option<&ListItemSnapshot>,
    selected_contact: Option<&ListItemSnapshot>,
) -> String {
    match screen {
        UiScreen::Hub => snapshot
            .hub
            .cards
            .get(focus_index)
            .or_else(|| snapshot.hub.cards.first())
            .map(|card| card.title.clone())
            .unwrap_or_else(|| "Listen".to_string()),
        UiScreen::Listen => "Listen".to_string(),
        UiScreen::Playlists => "Playlists".to_string(),
        UiScreen::PlaylistTracks => selected_playlist
            .map(|playlist| playlist.title.clone())
            .unwrap_or_else(|| "Playlist".to_string()),
        UiScreen::RecentTracks => "Recent".to_string(),
        UiScreen::NowPlaying => snapshot.music.title.clone(),
        UiScreen::Ask => snapshot.voice.headline.clone(),
        UiScreen::Talk => "Talk".to_string(),
        UiScreen::Contacts => "More People".to_string(),
        UiScreen::CallHistory => "Recents".to_string(),
        UiScreen::TalkContact => talk_contact_title(snapshot, focus_index, selected_contact),
        UiScreen::Replay => "Replay".to_string(),
        UiScreen::VoiceNote => voice_note_title(snapshot, focus_index),
        UiScreen::IncomingCall | UiScreen::OutgoingCall | UiScreen::InCall => {
            call_peer_name(snapshot)
        }
        UiScreen::Setup => "Setup".to_string(),
        UiScreen::SetupVolume => "Volume".to_string(),
        UiScreen::SetupCompanion => "Companion".to_string(),
        UiScreen::SetupContacts => "Contacts".to_string(),
        UiScreen::SetupTheme => "Theme".to_string(),
        UiScreen::SetupAbout => "About".to_string(),
        UiScreen::SetupWifi => "Wi‑Fi".to_string(),
        UiScreen::Loading => "Loading".to_string(),
        UiScreen::Error => "Error".to_string(),
    }
}

fn deck_focus_for_screen(screen: UiScreen, home_focus: Option<usize>) -> Option<usize> {
    match screen {
        UiScreen::Hub => home_focus,
        UiScreen::Listen
        | UiScreen::Playlists
        | UiScreen::PlaylistTracks
        | UiScreen::RecentTracks
        | UiScreen::NowPlaying => Some(0),
        UiScreen::Talk
        | UiScreen::Contacts
        | UiScreen::CallHistory
        | UiScreen::TalkContact
        | UiScreen::Replay
        | UiScreen::VoiceNote
        | UiScreen::IncomingCall
        | UiScreen::OutgoingCall
        | UiScreen::InCall => Some(1),
        UiScreen::Ask => Some(2),
        UiScreen::Setup
        | UiScreen::SetupVolume
        | UiScreen::SetupCompanion
        | UiScreen::SetupContacts
        | UiScreen::SetupTheme
        | UiScreen::SetupAbout
        | UiScreen::SetupWifi => Some(3),
        UiScreen::Loading | UiScreen::Error => None,
    }
}

fn status_from_snapshot(snapshot: &RuntimeSnapshot) -> HudStatus {
    let battery_percent = snapshot.power.battery_percent.clamp(0, 100) as u8;
    HudStatus {
        time: "00:00".to_string(),
        connectivity: HudConnectivity {
            kind: connectivity_kind(&snapshot.network.connection_type),
            connected: snapshot.network.connected,
            strength: signal_strength(snapshot.network.signal_strength),
        },
        gps_has_fix: snapshot.network.gps_has_fix,
        voip_registered: snapshot.call.registered,
        battery: HudBattery {
            percent: battery_percent,
            charging: snapshot.power.charging,
            available: snapshot.power.power_available,
        },
    }
}

fn signal_strength(value: i32) -> u8 {
    value.clamp(0, 4) as u8
}

fn connectivity_kind(value: &str) -> HudConnectivityKind {
    match value.trim().to_ascii_lowercase().as_str() {
        "wifi" | "wi-fi" | "wlan" | "wireless" => HudConnectivityKind::Wifi,
        "cellular" | "mobile" | "ppp" | "lte" | "4g" | "5g" => HudConnectivityKind::Cellular,
        _ => HudConnectivityKind::Unknown,
    }
}

fn talk_contact_title(
    _snapshot: &RuntimeSnapshot,
    focus_index: usize,
    _selected_contact: Option<&ListItemSnapshot>,
) -> String {
    match focus_index {
        0 => "Call",
        1 => "Hold to record",
        _ => "Replay",
    }
    .to_string()
}

fn voice_note_title(snapshot: &RuntimeSnapshot, focus_index: usize) -> String {
    let titles: &[&str] = match voice_note_phase(snapshot).as_str() {
        "review" => &["Send", "Play", "Again"],
        "failed" => &["Retry", "Again"],
        "sending" => &["Sending"],
        "sent" => &["Sent"],
        "recording" => &["Recording"],
        _ => &["Voice Note"],
    };
    let selected_index = focus_index.min(titles.len().saturating_sub(1));
    titles
        .get(selected_index)
        .copied()
        .unwrap_or("Voice Note")
        .to_string()
}

fn voice_note_phase(snapshot: &RuntimeSnapshot) -> String {
    let phase = snapshot.voice.phase.trim().to_ascii_lowercase();
    if snapshot.voice.capture_in_flight || snapshot.voice.ptt_active || phase == "recording" {
        return "recording".to_string();
    }
    if matches!(phase.as_str(), "review" | "sending" | "sent" | "failed") {
        return phase;
    }
    "ready".to_string()
}

fn call_peer_name(snapshot: &RuntimeSnapshot) -> String {
    if snapshot.call.peer_name.trim().is_empty() {
        "Unknown".to_string()
    } else {
        snapshot.call.peer_name.clone()
    }
}
