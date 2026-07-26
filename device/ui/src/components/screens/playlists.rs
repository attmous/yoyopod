use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

use crate::scene::{Scene, SceneDefaults, WheelItemModel};

pub struct PlaylistsProps {
    pub defaults: SceneDefaults,
    pub items: Vec<WheelItemModel>,
    pub focus: usize,
}

pub fn props_from(
    snapshot: &RuntimeSnapshot,
    focus: usize,
    defaults: SceneDefaults,
) -> PlaylistsProps {
    PlaylistsProps {
        defaults,
        items: super::media_wheel::models(&snapshot.music.playlists),
        focus,
    }
}

pub fn scene(props: &PlaylistsProps) -> Scene {
    super::media_wheel::scene(
        UiScreen::Playlists,
        &props.defaults,
        super::media_wheel::header("LISTEN", props.items.len(), props.focus),
        &props.items,
        props.focus,
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scene::{defaults_for, Backdrop, DeckKind, FocusPolicy, ItemRender};
    use yoyopod_protocol::ui::ListItemSnapshot;

    #[test]
    fn playlists_use_the_designed_media_wheel() {
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.music.playlists = vec![ListItemSnapshot::new(
            "/music/Open Classics.m3u",
            "Open Classics",
            "3 tracks",
            "playlist",
        )];
        let props = props_from(&snapshot, 0, defaults_for(UiScreen::Playlists));
        let scene = scene(&props);

        assert_eq!(scene.backdrop, Backdrop::Solid(0xE6FDE0));
        assert_eq!(
            scene
                .context
                .as_ref()
                .and_then(|context| context.wheel_header())
                .map(|header| header.title.as_str()),
            Some("LISTEN")
        );
        assert_eq!(
            scene
                .context
                .as_ref()
                .and_then(|context| context.wheel_header())
                .and_then(|header| header.counter.as_deref()),
            None
        );
        assert_eq!(scene.decks[0].kind, DeckKind::Wheel);
        assert_eq!(scene.decks[0].focus_policy, FocusPolicy::Wrap);
        assert_eq!(scene.decks[0].focused_visible_index(), 0);
        assert!(matches!(
            scene.decks[0].items[0].render,
            ItemRender::Wheel(_)
        ));
    }
}
