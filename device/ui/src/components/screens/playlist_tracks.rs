use yoyopod_protocol::ui::{ListItemSnapshot, RuntimeSnapshot, UiScreen};

use crate::scene::{Scene, SceneDefaults, WheelHeaderModel, WheelItemModel};

pub struct PlaylistTracksProps {
    pub defaults: SceneDefaults,
    pub header: WheelHeaderModel,
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
    let header = selected_playlist
        .map(|playlist| super::media_wheel::header(&playlist.title, tracks.len(), focus))
        .unwrap_or_else(|| super::media_wheel::header("PLAYLIST", tracks.len(), focus));
    PlaylistTracksProps {
        defaults,
        header,
        items: super::media_wheel::models(&tracks),
        focus,
    }
}

pub fn scene(props: &PlaylistTracksProps) -> Scene {
    super::media_wheel::scene(
        UiScreen::PlaylistTracks,
        &props.defaults,
        props.header.clone(),
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
            "Open Classics - Holst",
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
        assert_eq!(
            scene
                .context
                .as_ref()
                .and_then(|context| context.wheel_header())
                .map(|header| header.title.as_str()),
            Some("HOLST")
        );
        assert_eq!(
            scene
                .context
                .as_ref()
                .and_then(|context| context.wheel_header())
                .and_then(|header| header.counter.as_deref()),
            Some("2 / 2")
        );
        assert_eq!(scene.decks[0].kind, DeckKind::Wheel);
        assert_eq!(scene.decks[0].focus_policy, FocusPolicy::Wrap);
        assert_eq!(scene.decks[0].focused_visible_index(), 0);
        assert!(matches!(
            scene.decks[0].items[1].render,
            ItemRender::Wheel(_)
        ));
    }
}
