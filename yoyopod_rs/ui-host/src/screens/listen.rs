use crate::runtime::{ListItemSnapshot, RuntimeSnapshot, UiScreen, UiView};

pub fn view(snapshot: &RuntimeSnapshot, focus_index: usize) -> UiView {
    UiView {
        screen: UiScreen::Listen,
        title: "Listen".to_string(),
        subtitle: "Music".to_string(),
        footer: "Tap = Next | 2x Tap = Open | Hold = Back".to_string(),
        items: items(snapshot),
        focus_index,
    }
}

pub fn items(snapshot: &RuntimeSnapshot) -> Vec<ListItemSnapshot> {
    vec![
        ListItemSnapshot::new(
            "now_playing",
            "Now Playing",
            snapshot.music.title.clone(),
            "track",
        ),
        ListItemSnapshot::new("playlists", "Playlists", "Saved mixes", "playlist"),
        ListItemSnapshot::new("recent_tracks", "Recent", "Recently played", "recent"),
        ListItemSnapshot::new("shuffle", "Shuffle All", "Start music", "shuffle"),
    ]
}
