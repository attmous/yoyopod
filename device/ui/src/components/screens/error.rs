use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

use crate::scene::{Modal, Scene, SceneDefaults};

pub struct ErrorProps {
    pub defaults: SceneDefaults,
    pub retryable: bool,
}

pub fn props_from(snapshot: &RuntimeSnapshot, defaults: SceneDefaults) -> ErrorProps {
    ErrorProps {
        defaults,
        retryable: snapshot.overlay.retryable,
    }
}

pub fn scene(props: &ErrorProps) -> Scene {
    super::common::overlay_scene(
        UiScreen::Error,
        &props.defaults,
        Modal::Error {
            retryable: props.retryable,
        },
    )
}
