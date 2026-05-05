use crate::runtime::{RuntimeSnapshot, UiScreen, UiView};
use crate::screens::{chrome, ListScreenModel, NowPlayingViewModel};

pub fn playlists_model(snapshot: &RuntimeSnapshot, focus_index: usize) -> ListScreenModel {
    ListScreenModel {
        chrome: chrome::chrome(snapshot, "Tap = Next | 2x Tap = Play | Hold = Back"),
        title: "Playlists".to_string(),
        subtitle: "Saved mixes".to_string(),
        rows: chrome::list_rows(&snapshot.music.playlists, focus_index),
    }
}

pub fn recent_tracks_model(snapshot: &RuntimeSnapshot, focus_index: usize) -> ListScreenModel {
    ListScreenModel {
        chrome: chrome::chrome(snapshot, "Tap = Next | 2x Tap = Play | Hold = Back"),
        title: "Recent".to_string(),
        subtitle: "Recently played".to_string(),
        rows: chrome::list_rows(&snapshot.music.recent_tracks, focus_index),
    }
}

pub fn now_playing_model(snapshot: &RuntimeSnapshot) -> NowPlayingViewModel {
    NowPlayingViewModel {
        chrome: chrome::chrome(snapshot, "Tap = Next | 2x Tap = Play/Pause | Hold = Back"),
        title: snapshot.music.title.clone(),
        artist: snapshot.music.artist.clone(),
        state_text: if snapshot.music.playing {
            "Now Playing".to_string()
        } else if snapshot.music.paused {
            "Paused".to_string()
        } else {
            "Stopped".to_string()
        },
        progress_permille: snapshot.music.progress_permille,
    }
}

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
