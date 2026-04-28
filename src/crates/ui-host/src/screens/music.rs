use crate::runtime::{RuntimeSnapshot, UiScreen, UiView};

pub fn playlists_view(snapshot: &RuntimeSnapshot, focus_index: usize) -> UiView {
    UiView {
        screen: UiScreen::Playlists,
        title: "Playlists".to_string(),
        subtitle: "Saved mixes".to_string(),
        footer: "Tap = Next | 2x Tap = Play | Hold = Back".to_string(),
        items: snapshot.music.playlists.clone(),
        focus_index,
    }
}

pub fn recent_tracks_view(snapshot: &RuntimeSnapshot, focus_index: usize) -> UiView {
    UiView {
        screen: UiScreen::RecentTracks,
        title: "Recent".to_string(),
        subtitle: "Recently played".to_string(),
        footer: "Tap = Next | 2x Tap = Play | Hold = Back".to_string(),
        items: snapshot.music.recent_tracks.clone(),
        focus_index,
    }
}

pub fn now_playing_view(snapshot: &RuntimeSnapshot, focus_index: usize) -> UiView {
    UiView {
        screen: UiScreen::NowPlaying,
        title: snapshot.music.title.clone(),
        subtitle: snapshot.music.artist.clone(),
        footer: "Tap = Next | 2x Tap = Play/Pause | Hold = Back".to_string(),
        items: Vec::new(),
        focus_index,
    }
}
