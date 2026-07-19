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
    replay_index: usize,
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
        UiScreen::Replay => {
            let note_count = selected_contact
                .and_then(|contact| snapshot.call.voice_notes_by_contact.get(&contact.id))
                .map(Vec::len)
                .unwrap_or(0);
            if replay_index + 1 < note_count {
                3
            } else {
                2
            }
        }
        UiScreen::VoiceNote => options::voice_note_action_count(snapshot),
        UiScreen::Power => options::power_page_count(snapshot),
        _ => 0,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use yoyopod_protocol::ui::VoiceNoteSummarySnapshot;

    #[test]
    fn replay_removes_next_from_focus_on_the_last_recording() {
        let contact = ListItemSnapshot::new("mama", "Mama", "", "mono:M");
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.call.voice_notes_by_contact.insert(
            contact.id.clone(),
            vec![VoiceNoteSummarySnapshot::default(); 2],
        );

        assert_eq!(
            focus_count(UiScreen::Replay, &snapshot, None, Some(&contact), 0),
            3
        );
        assert_eq!(
            focus_count(UiScreen::Replay, &snapshot, None, Some(&contact), 1),
            2
        );
    }
}
