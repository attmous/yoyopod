use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

use crate::scene::{CallOverlayKind, CallOverlayModel, Scene, SceneDefaults};

pub struct InCallProps {
    pub defaults: SceneDefaults,
    pub model: CallOverlayModel,
}

pub fn props_from(
    snapshot: &RuntimeSnapshot,
    focus: usize,
    defaults: SceneDefaults,
) -> InCallProps {
    InCallProps {
        defaults,
        model: super::common::call_overlay_model(snapshot, CallOverlayKind::Active, focus),
    }
}

pub fn scene(props: &InCallProps) -> Scene {
    super::common::call_scene(UiScreen::InCall, &props.defaults, props.model.clone())
}
