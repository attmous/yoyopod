use crate::components::primitives::{container, image, label};
use crate::engine::{Element, Key};
use crate::scene::{roles, CallOverlayKind, CallOverlayModel};

const INK: u32 = 0x1B1B1F;
const CREAM: u32 = 0xFCE6D2;
const MINT: u32 = 0x6FDFB1;
const CORAL: u32 = 0xF37767;
const TOMATO: u32 = 0xE5443B;

pub fn call_overlay(model: &CallOverlayModel) -> Element {
    let compact = model.kind == CallOverlayKind::Active;
    let mut overlay = container(roles::CALL_OVERLAY)
        .key(Key::Static("call_overlay"))
        .child(label(roles::CALL_STATE).text(&model.state));

    overlay = if compact {
        overlay
            .child(avatar(
                roles::CALL_AVATAR_SM,
                roles::CALL_AVATAR_INITIAL_SM,
                model,
            ))
            .child(label(roles::CALL_NAME_SM).text(&model.name))
            .child(label(roles::CALL_DURATION).text(&model.duration))
    } else {
        overlay
            .child(avatar(
                roles::CALL_AVATAR,
                roles::CALL_AVATAR_INITIAL,
                model,
            ))
            .child(label(roles::CALL_NAME).text(&model.name))
    };

    match model.kind {
        CallOverlayKind::Incoming => overlay
            .child(call_button(
                roles::CALL_ANSWER,
                "answer_sm",
                MINT,
                model.focus_index == 0,
            ))
            .child(call_button(
                roles::CALL_HANGUP,
                "close_sm",
                TOMATO,
                model.focus_index == 1,
            )),
        CallOverlayKind::Outgoing => overlay.child(call_button(
            roles::CALL_HANGUP_CENTER,
            "close_sm",
            TOMATO,
            true,
        )),
        CallOverlayKind::Active => overlay
            .child(call_button(
                roles::CALL_MUTE,
                "mic_sm",
                if model.muted { CORAL } else { CREAM },
                model.focus_index == 0,
            ))
            .child(call_button(
                roles::CALL_HANGUP,
                "close_sm",
                TOMATO,
                model.focus_index == 1,
            )),
    }
}

fn avatar(role: &'static str, initial_role: &'static str, model: &CallOverlayModel) -> Element {
    container(role)
        .accent(model.avatar_rgb)
        .child(label(initial_role).text(&model.initial))
}

fn call_button(role: &'static str, icon_key: &'static str, fill: u32, focused: bool) -> Element {
    container(role)
        .accent(fill)
        .selected(focused)
        .scale_permille(if focused { 1_100 } else { 1_000 })
        .child(image(roles::CALL_BUTTON_ICON).icon(icon_key).accent(INK))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn model(kind: CallOverlayKind) -> CallOverlayModel {
        CallOverlayModel {
            kind,
            state: "INCOMING".to_string(),
            name: "Mama".to_string(),
            initial: "M".to_string(),
            avatar_rgb: 0xE8A93C,
            duration: "02:14".to_string(),
            muted: false,
            focus_index: 0,
        }
    }

    #[test]
    fn incoming_has_two_semantic_svg_controls() {
        let overlay = call_overlay(&model(CallOverlayKind::Incoming));
        let answer = overlay
            .children
            .iter()
            .find(|child| child.role == Some(roles::CALL_ANSWER))
            .expect("answer control");
        let hangup = overlay
            .children
            .iter()
            .find(|child| child.role == Some(roles::CALL_HANGUP))
            .expect("hangup control");

        assert_eq!(answer.props.selected, Some(true));
        assert_eq!(answer.props.scale_permille, Some(1_100));
        assert_eq!(
            answer.children[0].props.icon_key.as_deref(),
            Some("answer_sm")
        );
        assert_eq!(
            hangup.children[0].props.icon_key.as_deref(),
            Some("close_sm")
        );
    }

    #[test]
    fn muted_call_uses_coral_without_changing_the_mic_glyph() {
        let mut model = model(CallOverlayKind::Active);
        model.muted = true;
        let overlay = call_overlay(&model);
        let mute = overlay
            .children
            .iter()
            .find(|child| child.role == Some(roles::CALL_MUTE))
            .expect("mute control");

        assert_eq!(mute.props.accent, Some(CORAL));
        assert_eq!(mute.children[0].props.icon_key.as_deref(), Some("mic_sm"));
    }
}
