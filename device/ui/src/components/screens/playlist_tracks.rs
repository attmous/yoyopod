use yoyopod_protocol::ui::{ListItemSnapshot, RuntimeSnapshot, UiScreen};

use crate::scene::{Scene, SceneDefaults, WheelItemModel};

pub struct PlaylistTracksProps {
    pub defaults: SceneDefaults,
    pub context: String,
    pub items: Vec<WheelItemModel>,
    pub focus: usize,
}

pub fn props_from(
    snapshot: &RuntimeSnapshot,
    focus: usize,
    selected_playlist: Option<&ListItemSnapshot>,
    defaults: SceneDefaults,
) -> PlaylistTracksProps {
    let tracks = selected_playlist
        .and_then(|playlist| snapshot.music.playlist_tracks.get(&playlist.id))
        .cloned()
        .unwrap_or_default();
    let context = selected_playlist
        .map(|playlist| {
            super::media_wheel::context_with_counter(&playlist.title, tracks.len(), focus)
        })
        .unwrap_or_else(|| "PLAYLIST".to_string());
    PlaylistTracksProps {
        defaults,
        context,
        items: super::media_wheel::models(&tracks),
        focus,
    }
}

pub fn scene(props: &PlaylistTracksProps) -> Scene {
    super::media_wheel::scene(
        UiScreen::PlaylistTracks,
        &props.defaults,
        props.context.clone(),
        &props.items,
        props.focus,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scene::{defaults_for, DeckKind, FocusPolicy, ItemRender};

    #[test]
    fn selected_playlist_tracks_render_as_a_depth_three_wheel() {
        let playlist = ListItemSnapshot::new(
            "/music/Open Classics.m3u",
            "Open Classics",
            "3 tracks",
            "playlist",
        );
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.music.playlist_tracks.insert(
            playlist.id.clone(),
            vec![
                ListItemSnapshot::new("/music/1.mp3", "Chaconne", "5:32", "track"),
                ListItemSnapshot::new("/music/2.mp3", "March", "4:18", "track"),
            ],
        );

        let props = props_from(
            &snapshot,
            1,
            Some(&playlist),
            defaults_for(UiScreen::PlaylistTracks),
        );
        let scene = scene(&props);
        assert_eq!(scene.context.as_deref(), Some("OPEN CLASSICS"));
        assert_eq!(scene.decks[0].kind, DeckKind::Wheel);
        assert_eq!(scene.decks[0].focus_policy, FocusPolicy::Wrap);
        assert_eq!(scene.decks[0].focused_visible_index(), 0);
        assert!(matches!(
            scene.decks[0].items[1].render,
            ItemRender::Wheel(_)
        ));
    }
}
