use yoyopod_protocol::ui::{ListItemSnapshot, RuntimeSnapshot, UiScreen};

use super::options;
use super::state::HomeMode;
use super::UiRuntime;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct FocusDescriptor {
    pub key: String,
    pub label: String,
}

impl FocusDescriptor {
    fn new(key: impl Into<String>, label: impl Into<String>) -> Self {
        Self {
            key: key.into(),
            label: label.into(),
        }
    }
}

pub(crate) fn focused_item(runtime: &UiRuntime) -> Option<FocusDescriptor> {
    let snapshot = &runtime.snapshot;
    let focus = runtime.focus_index;
    match runtime.active_screen {
        UiScreen::Hub if runtime.home_mode == HomeMode::Focused => snapshot
            .hub
            .cards
            .get(focus)
            .or_else(|| snapshot.hub.cards.first())
            .map(|card| FocusDescriptor::new(card.key.clone(), card.title.clone())),
        UiScreen::Hub => None,
        UiScreen::Listen => list_item(options::listen_items(snapshot).get(focus)),
        UiScreen::Playlists => list_or_empty(&snapshot.music.playlists, focus, "No playlists"),
        UiScreen::PlaylistTracks => {
            let tracks = runtime
                .selected_playlist
                .as_ref()
                .and_then(|playlist| snapshot.music.playlist_tracks.get(&playlist.id))
                .map(Vec::as_slice)
                .unwrap_or_default();
            list_or_empty(tracks, focus, "No tracks")
        }
        UiScreen::RecentTracks => {
            list_or_empty(&snapshot.music.recent_tracks, focus, "No recent tracks")
        }
        UiScreen::NowPlaying => Some(static_item(
            focus,
            &["Previous", music_play_pause_label(snapshot), "Next"],
        )),
        UiScreen::Ask | UiScreen::Loading | UiScreen::Error | UiScreen::SetupWifi => None,
        UiScreen::Talk | UiScreen::Contacts | UiScreen::SetupContacts => list_or_empty(
            &snapshot.call.contacts,
            focus,
            "No contacts yet. Ask a grown-up!",
        ),
        UiScreen::CallHistory => list_or_empty(&snapshot.call.history, focus, "No recent calls"),
        UiScreen::TalkContact => Some(static_item(focus, &["Call", "Hold to record", "Replay"])),
        UiScreen::Replay => {
            if runtime.replay_notes().is_empty() {
                Some(FocusDescriptor::new("empty", "No recordings"))
            } else {
                let labels = ["Delete", voice_play_pause_label(snapshot), "Next"];
                Some(static_item(focus, &labels))
            }
        }
        UiScreen::VoiceNote => voice_note_item(runtime),
        UiScreen::IncomingCall => Some(static_item(focus, &["Answer call", "Reject call"])),
        UiScreen::OutgoingCall => Some(FocusDescriptor::new("hang_up", "Hang up")),
        UiScreen::InCall => Some(static_item(
            focus,
            &[
                if snapshot.call.muted {
                    "Unmute"
                } else {
                    "Mute"
                },
                "Hang up",
            ],
        )),
        UiScreen::Setup => setup_root_item(snapshot, focus),
        UiScreen::SetupVolume => Some(FocusDescriptor::new(
            "volume",
            format!("Volume, level {}", snapshot.settings.volume_level),
        )),
        UiScreen::SetupCompanion => choice_item(
            focus,
            &["Blob", "Owl", "Cat", "Bunny", "Robot"],
            &snapshot.settings.companion,
        ),
        UiScreen::SetupTheme => {
            choice_item(focus, &["Light", "Dark", "Auto"], &snapshot.settings.theme)
        }
        UiScreen::SetupAbout => Some(FocusDescriptor::new("about", "About")),
    }
}

fn list_or_empty(
    items: &[ListItemSnapshot],
    focus: usize,
    empty_label: &'static str,
) -> Option<FocusDescriptor> {
    if items.is_empty() {
        Some(FocusDescriptor::new("empty", empty_label))
    } else {
        list_item(items.get(focus).or_else(|| items.first()))
    }
}

fn list_item(item: Option<&ListItemSnapshot>) -> Option<FocusDescriptor> {
    item.map(|item| FocusDescriptor::new(item.id.clone(), item.title.clone()))
}

fn static_item(focus: usize, labels: &[&str]) -> FocusDescriptor {
    let index = focus.min(labels.len().saturating_sub(1));
    let label = labels.get(index).copied().unwrap_or_default();
    FocusDescriptor::new(format!("item_{index}"), label)
}

fn music_play_pause_label(snapshot: &RuntimeSnapshot) -> &'static str {
    if snapshot.music.playing {
        "Pause"
    } else if snapshot.music.paused {
        "Resume"
    } else {
        "Play"
    }
}

fn voice_play_pause_label(snapshot: &RuntimeSnapshot) -> &'static str {
    if snapshot.voice.playback_active {
        "Pause"
    } else if snapshot.voice.playback_paused {
        "Resume"
    } else {
        "Play"
    }
}

fn voice_note_item(runtime: &UiRuntime) -> Option<FocusDescriptor> {
    let labels: &[&str] = match runtime.voice_note_phase().as_str() {
        "review" => &["Send", "Play", "Again"],
        "failed" => &["Retry", "Again"],
        _ => return None,
    };
    Some(static_item(runtime.focus_index, labels))
}

fn setup_root_item(snapshot: &RuntimeSnapshot, focus: usize) -> Option<FocusDescriptor> {
    let labels = [
        format!("Volume, level {}", snapshot.settings.volume_level),
        format!("Companion, {}", snapshot.settings.companion),
        format!("Contacts, {}", snapshot.call.contacts.len()),
        format!("Theme, {}", snapshot.settings.theme),
        format!(
            "Speak names, {}",
            if snapshot.settings.speak_names {
                "on"
            } else {
                "off"
            }
        ),
        // Order must match `setup_root_items` in the Setup scene: Wi-Fi sits
        // before About, or focusing the Wi-Fi row announces the wrong label
        // (and About gets clamped to it).
        "Wi-Fi".to_string(),
        "About".to_string(),
    ];
    let index = focus.min(labels.len().saturating_sub(1));
    labels
        .get(index)
        .map(|label| FocusDescriptor::new(format!("item_{index}"), label.clone()))
}

fn choice_item(focus: usize, labels: &[&str], current: &str) -> Option<FocusDescriptor> {
    let index = focus.min(labels.len().saturating_sub(1));
    labels.get(index).map(|label| {
        let spoken = if label.eq_ignore_ascii_case(current) {
            format!("{label}, current")
        } else {
            (*label).to_string()
        };
        FocusDescriptor::new(format!("item_{index}"), spoken)
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use yoyopod_protocol::ui::VoiceNoteSummarySnapshot;

    #[test]
    fn dynamic_lists_speak_the_rendered_item_and_empty_state() {
        let mut runtime = UiRuntime {
            active_screen: UiScreen::Playlists,
            ..UiRuntime::default()
        };
        assert_eq!(focused_item(&runtime).unwrap().label, "No playlists");

        runtime.snapshot.music.playlists = vec![ListItemSnapshot::new(
            "bedtime",
            "Bedtime songs",
            "3 tracks",
            "playlist",
        )];
        assert_eq!(focused_item(&runtime).unwrap().label, "Bedtime songs");
    }

    #[test]
    fn transport_labels_follow_live_playback_state() {
        let mut runtime = UiRuntime {
            active_screen: UiScreen::NowPlaying,
            focus_index: 1,
            ..UiRuntime::default()
        };
        assert_eq!(focused_item(&runtime).unwrap().label, "Play");

        runtime.snapshot.music.playing = true;
        assert_eq!(focused_item(&runtime).unwrap().label, "Pause");
    }

    #[test]
    fn replay_has_a_spoken_empty_state() {
        let mut runtime = UiRuntime {
            active_screen: UiScreen::Replay,
            ..UiRuntime::default()
        };
        assert_eq!(focused_item(&runtime).unwrap().label, "No recordings");

        let contact = ListItemSnapshot::new("mama", "Mama", "", "mono:M");
        runtime.selected_contact = Some(contact.clone());
        runtime
            .snapshot
            .call
            .voice_notes_by_contact
            .insert(contact.id, vec![VoiceNoteSummarySnapshot::default()]);
        assert_eq!(focused_item(&runtime).unwrap().label, "Delete");
    }

    #[test]
    fn setup_root_labels_match_the_rendered_wheel_order() {
        let snapshot = RuntimeSnapshot::default();
        // Wi-Fi is index 5 (before About at 6), matching `setup_root_items`.
        assert_eq!(setup_root_item(&snapshot, 5).unwrap().label, "Wi-Fi");
        assert_eq!(setup_root_item(&snapshot, 6).unwrap().label, "About");
        // Every focusable setup row must have a spoken label, or trailing rows
        // get clamped to the wrong one.
        let count =
            crate::application::focus::focus_count(UiScreen::Setup, &snapshot, None, None, 0);
        assert_eq!(count, 7);
        assert!(
            setup_root_item(&snapshot, count - 1).is_some(),
            "the last setup row must have an accessibility label"
        );
    }
}
