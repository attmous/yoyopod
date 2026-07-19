use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

use crate::scene::{CallOverlayKind, CallOverlayModel, Scene, SceneDefaults};

pub struct OutgoingCallProps {
    pub defaults: SceneDefaults,
    pub model: CallOverlayModel,
}

pub fn props_from(
    snapshot: &RuntimeSnapshot,
    focus: usize,
    defaults: SceneDefaults,
) -> OutgoingCallProps {
    OutgoingCallProps {
        defaults,
        model: super::common::call_overlay_model(snapshot, CallOverlayKind::Outgoing, focus),
    }
}

pub fn scene(props: &OutgoingCallProps) -> Scene {
    super::common::call_scene(UiScreen::OutgoingCall, &props.defaults, props.model.clone())
}
