use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

use crate::scene::{Modal, Scene, SceneDefaults};

pub struct LoadingProps {
    pub defaults: SceneDefaults,
}

pub fn props_from(_snapshot: &RuntimeSnapshot, defaults: SceneDefaults) -> LoadingProps {
    LoadingProps { defaults }
}

pub fn scene(props: &LoadingProps) -> Scene {
    super::common::overlay_scene(
        UiScreen::Loading,
        &props.defaults,
        Modal::Loading { spinner_step: 0 },
    )
}
