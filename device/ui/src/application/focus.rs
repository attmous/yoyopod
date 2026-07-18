use yoyopod_protocol::ui::{ListItemSnapshot, RuntimeSnapshot};

use super::options;
use super::UiScreen;

pub fn advance(current: usize, count: usize) -> usize {
    if count == 0 {
        current
    } else {
        (current + 1) % count
    }
}

pub fn advance_clamped(current: usize, count: usize) -> usize {
    if count == 0 {
        0
    } else {
        (current + 1).min(count - 1)
    }
}

pub fn clamp(current: usize, count: usize) -> usize {
    if count == 0 {
        0
    } else if current >= count {
        count - 1
    } else {
        current
    }
}

pub fn focus_count(
    screen: UiScreen,
    snapshot: &RuntimeSnapshot,
    selected_playlist: Option<&ListItemSnapshot>,
    selected_contact: Option<&ListItemSnapshot>,
) -> usize {
    match screen {
        UiScreen::Hub => snapshot.hub.cards.len().max(1),
        UiScreen::Listen => options::listen_items(snapshot).len(),
        UiScreen::Playlists => snapshot.music.playlists.len(),
        UiScreen::PlaylistTracks => selected_playlist
            .and_then(|playlist| snapshot.music.playlist_tracks.get(&playlist.id))
            .map(Vec::len)
            .unwrap_or(0),
        UiScreen::RecentTracks => snapshot.music.recent_tracks.len(),
        UiScreen::NowPlaying => 3,
        UiScreen::Talk => snapshot.call.contacts.len(),
        UiScreen::Contacts => snapshot.call.contacts.len(),
        UiScreen::CallHistory => snapshot.call.history.len(),
        UiScreen::TalkContact => options::talk_contact_actions(snapshot, selected_contact).len(),
        UiScreen::VoiceNote => options::voice_note_action_count(snapshot),
        UiScreen::Power => options::power_page_count(snapshot),
        _ => 0,
    }
}
