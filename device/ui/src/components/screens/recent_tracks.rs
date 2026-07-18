use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

use crate::scene::{Scene, SceneDefaults, WheelItemModel};

pub struct RecentTracksProps {
    pub defaults: SceneDefaults,
    pub items: Vec<WheelItemModel>,
    pub focus: usize,
}

pub fn props_from(
    snapshot: &RuntimeSnapshot,
    focus: usize,
    defaults: SceneDefaults,
) -> RecentTracksProps {
    RecentTracksProps {
        defaults,
        items: super::media_wheel::models(&snapshot.music.recent_tracks),
        focus,
    }
}

pub fn scene(props: &RecentTracksProps) -> Scene {
    super::media_wheel::scene(
        UiScreen::RecentTracks,
        &props.defaults,
        "LISTEN".to_string(),
        &props.items,
        props.focus,
    )
}
