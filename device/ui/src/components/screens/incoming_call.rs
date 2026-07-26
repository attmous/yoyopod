use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

use crate::scene::{CallOverlayKind, CallOverlayModel, Scene, SceneDefaults};

pub struct IncomingCallProps {
    pub defaults: SceneDefaults,
    pub model: CallOverlayModel,
}

pub fn props_from(
    snapshot: &RuntimeSnapshot,
    focus: usize,
    defaults: SceneDefaults,
) -> IncomingCallProps {
    IncomingCallProps {
        defaults,
        model: super::common::call_overlay_model(snapshot, CallOverlayKind::Incoming, focus),
    }
}

pub fn scene(props: &IncomingCallProps) -> Scene {
    super::common::call_scene(UiScreen::IncomingCall, &props.defaults, props.model.clone())
}
