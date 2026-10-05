use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

use crate::engine::Key;
use crate::scene::{
    ButtonModel, ContextLabelModel, DeckItem, ItemRender, Scene, SceneContext, SceneDefaults,
    WheelHeaderModel,
};

pub struct VoiceNoteProps {
    pub defaults: SceneDefaults,
    pub buttons: Vec<DeckItem>,
    pub focus: usize,
    pub retained_draft: bool,
    pub context: Option<SceneContext>,
}

pub fn props_from(
    snapshot: &RuntimeSnapshot,
    focus: usize,
    defaults: SceneDefaults,
) -> VoiceNoteProps {
    let retained_draft = snapshot.voice.interrupted_draft_path.is_some();
    let title = action_title(snapshot, focus);
    let context = retained_draft.then(|| {
        if snapshot.voice.interrupted_draft_phase == "unknown" {
            let caption = match title.as_str() {
                "Send again" => "Resend",
                "Send unavailable" => "No Send",
                _ => &title,
            };
            SceneContext::WheelHeader(WheelHeaderModel::new(
                "Delivery unknown",
                Some(caption.to_string()),
            ))
        } else {
            SceneContext::Label(ContextLabelModel::new(title))
        }
    });
    VoiceNoteProps {
        defaults,
        buttons: buttons(snapshot),
        focus,
        retained_draft,
        context,
    }
}

pub fn scene(props: &VoiceNoteProps) -> Scene {
    let mut scene = super::common::action_scene(UiScreen::VoiceNote, &props.defaults, props.focus);
    if let Some(deck) = scene.decks.first_mut() {
        deck.items = props.buttons.clone();
        if props.retained_draft {
            // Keep all actions and their keys; only the focused tile is drawn.
            deck.recycle_window = Some(1);
            for item in &mut deck.items {
                if let ItemRender::Button(button) = &mut item.render {
                    button.title = match button.title.as_str() {
                        "Send unavailable" => "Send".into(),
                        "Send again" => "Retry".into(),
                        _ => button.title.clone(),
                    };
                }
            }
        }
    }
    if props.retained_draft {
        // VoiceMeter represents active capture and paints above the actions.
        scene.fx.particles.clear();
        scene.context = props.context.clone();
    }
    scene.cursor = Some(crate::scene::Cursor::UnderlineDots {
        count: scene
            .decks
            .first()
            .map(|deck| deck.items.len())
            .unwrap_or(0),
        focus: props.focus,
    });
    scene
}

pub(super) fn action_title(snapshot: &RuntimeSnapshot, focus: usize) -> String {
    let actions = buttons(snapshot);
    match actions.get(focus.min(actions.len().saturating_sub(1))) {
        Some(DeckItem {
            render: ItemRender::Button(button),
            ..
        }) => button.title.clone(),
        _ => "Voice Note".into(),
    }
}

fn buttons(snapshot: &RuntimeSnapshot) -> Vec<DeckItem> {
    if snapshot.voice.interrupted_draft_path.is_some() {
        let send = if snapshot.voice.interrupted_draft_send_allowed
            && snapshot.voice.interrupted_draft_phase == "unknown"
        {
            "Send again"
        } else if snapshot.voice.interrupted_draft_send_allowed {
            "Send"
        } else {
            "Send unavailable"
        };
        return match voice_note_phase(snapshot).as_str() {
            "sending" => vec![button("sending", "Sending", "voice_note")],
            "sent" => vec![button("sent", "Sent", "check")],
            "failed" | "unknown" => vec![
                button("retry", send, "retry"),
                button("play", "Review", "play"),
                button("discard", "Discard", "close"),
            ],
            _ => vec![
                button("send", send, "check"),
                button("play", "Review", "play"),
                button("discard", "Discard", "close"),
            ],
        };
    }
    match voice_note_phase(snapshot).as_str() {
        "review" => vec![
            button("send", "Send", "check"),
            button("play", "Play", "play"),
            button("again", "Again", "close"),
        ],
        "failed" => vec![
            button("retry", "Retry", "retry"),
            button("again", "Again", "close"),
        ],
        "sending" => vec![button("sending", "Sending", "voice_note")],
        "sent" => vec![button("sent", "Sent", "check")],
        "recording" => vec![button("recording", "Recording", "voice_note")],
        _ => vec![button("record", "Voice Note", "voice_note")],
    }
}

fn button(key: &'static str, title: &'static str, icon_key: &'static str) -> DeckItem {
    DeckItem {
        key: Key::Static(key),
        render: ItemRender::Button(ButtonModel {
            title: title.to_string(),
            icon_key: icon_key.to_string(),
        }),
    }
}

fn voice_note_phase(snapshot: &RuntimeSnapshot) -> String {
    if snapshot.voice.interrupted_draft_path.is_some() {
        return if snapshot.voice.interrupted_draft_phase.is_empty() {
            "review".into()
        } else {
            snapshot.voice.interrupted_draft_phase.clone()
        };
    }
    let phase = snapshot.voice.phase.trim().to_ascii_lowercase();
    if snapshot.voice.capture_in_flight || snapshot.voice.ptt_active || phase == "recording" {
        return "recording".to_string();
    }
    if matches!(phase.as_str(), "review" | "sending" | "sent" | "failed") {
        return phase;
    }
    "ready".to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::application::UiRuntime;
    use crate::engine::{flatten, Element};
    use crate::renderer::assets::load_render_assets;
    use crate::renderer::styling::layout::LayoutResolver;
    use crate::scene::{defaults_for, Cursor};
    use yoyopod_protocol::ui::{InputAction, UiIntent, VoiceIntent};

    fn retained_draft(phase: &str, send_allowed: bool) -> UiRuntime {
        let mut runtime = UiRuntime {
            active_screen: UiScreen::VoiceNote,
            ..Default::default()
        };
        runtime.snapshot.voice.interrupted_draft_path = Some("owned.wav".into());
        runtime.snapshot.voice.interrupted_draft_id = "draft-a".into();
        runtime.snapshot.voice.interrupted_draft_phase = phase.into();
        runtime.snapshot.voice.interrupted_draft_send_allowed = send_allowed;
        runtime
    }

    fn elements_with_role<'a>(element: &'a Element, role: &str) -> Vec<&'a Element> {
        let mut found = Vec::new();
        if element.role == Some(role) {
            found.push(element);
        }
        for child in &element.children {
            found.extend(elements_with_role(child, role));
        }
        found
    }

    #[test]
    fn retained_draft_advance_renders_only_the_action_that_select_dispatches() {
        let mut runtime = retained_draft("review", true);
        let assets = load_render_assets().unwrap();
        let layout = LayoutResolver::new(&assets);
        for (focus, key, title) in [
            (0, "send", "Send"),
            (1, "play", "Review"),
            (2, "discard", "Discard"),
            (0, "send", "Send"),
        ] {
            let graph = runtime.scene_graph(1_000);
            assert_eq!(runtime.focus_index, focus);
            assert_eq!(graph.active.decks[0].items.len(), 3);
            assert_eq!(
                graph.active.cursor,
                Some(Cursor::UnderlineDots { count: 3, focus })
            );
            let rendered = flatten::flatten(&graph);
            let buttons = elements_with_role(&rendered, "button");
            assert_eq!(buttons.len(), 1, "one centered action at focus {focus}");
            assert_eq!(buttons[0].key, Some(Key::Static(key)));
            assert_eq!(buttons[0].props.selected, Some(true));
            let tile = layout.resolve_role("button", 0).unwrap();
            let label = layout.resolve_role("button_title", 0).unwrap();
            assert_eq!(tile.x * 2 + tile.width, 240, "tile stays centered");
            assert!(tile.y >= 0 && tile.y + tile.height <= 280);
            assert!(label.x >= 0 && label.x + label.width <= tile.width);
            assert!(label.y >= 0 && label.y + label.height <= tile.height);
            let dots = elements_with_role(&rendered, "cursor_dot");
            assert_eq!(dots.len(), 3);
            assert_eq!(dots[focus].props.selected, Some(true));
            assert_eq!(
                dots.iter()
                    .filter(|dot| dot.props.selected == Some(true))
                    .count(),
                1
            );
            assert_eq!(
                elements_with_role(buttons[0], "button_title")[0]
                    .props
                    .text
                    .as_deref(),
                Some(title)
            );
            runtime.handle_input(InputAction::Select, 1_010);
            let intents = runtime.take_intents();
            let [UiIntent::Voice(intent)] = intents.as_slice() else {
                panic!("select must dispatch exactly the displayed action: {intents:?}");
            };
            let action = match (key, intent) {
                ("send", VoiceIntent::SavedSend(action))
                | ("play", VoiceIntent::SavedPlay(action))
                | ("discard", VoiceIntent::SavedDiscard(action)) => action,
                _ => panic!("wrong action for displayed {key}: {intent:?}"),
            };
            assert_eq!(action.file_path, "owned.wav");
            assert_eq!(action.message_id, "draft-a");
            // Discard navigates away; return to the same retained snapshot to
            // check that the existing advance policy also wraps to Send.
            runtime.active_screen = UiScreen::VoiceNote;
            runtime.focus_index = focus;
            runtime.handle_input(InputAction::Advance, 1_020);
        }
    }

    #[test]
    fn retained_draft_has_no_capture_particles_above_its_controls() {
        for phase in ["review", "failed", "unknown", "sending", "sent"] {
            let runtime = retained_draft(phase, true);
            let rendered = flatten::flatten(&runtime.scene_graph(1_000));
            assert!(
                elements_with_role(&rendered, "fx_particle").is_empty(),
                "retained {phase} must not have capture FX over the actions"
            );
        }

        let mut recording = RuntimeSnapshot::default();
        recording.voice.phase = "recording".into();
        let ordinary = scene(&props_from(
            &recording,
            0,
            defaults_for(UiScreen::VoiceNote),
        ));
        assert_eq!(
            elements_with_role(&flatten::scene_element(&ordinary), "fx_particle").len(),
            6,
            "ordinary recording keeps its capture decoration"
        );
    }

    #[test]
    fn retained_draft_phase_and_permission_labels_preserve_existing_actions() {
        for (phase, allowed, key, title, count) in [
            ("review", true, "send", "Send", 3),
            ("review", false, "send", "Send", 3),
            ("failed", true, "retry", "Send", 3),
            ("failed", false, "retry", "Send", 3),
            ("unknown", true, "retry", "Retry", 3),
            ("unknown", false, "retry", "Send", 3),
            ("sending", false, "sending", "Sending", 1),
            ("sent", false, "sent", "Sent", 1),
        ] {
            let mut runtime = retained_draft(phase, allowed);
            let graph = runtime.scene_graph(1_000);
            assert_eq!(graph.active.decks[0].items.len(), count);
            let rendered = flatten::flatten(&graph);
            let buttons = elements_with_role(&rendered, "button");
            assert_eq!(buttons.len(), 1, "phase {phase}, allowed {allowed}");
            assert_eq!(buttons[0].key, Some(Key::Static(key)));
            assert_eq!(
                elements_with_role(buttons[0], "button_title")[0]
                    .props
                    .text
                    .as_deref(),
                Some(title)
            );
            runtime.handle_input(InputAction::Select, 1_010);
            let intents = runtime.take_intents();
            match phase {
                "sending" => assert!(intents.is_empty()),
                "sent" => assert!(matches!(
                    intents.as_slice(),
                    [UiIntent::Voice(VoiceIntent::SavedDiscard(_))]
                )),
                _ if allowed => assert!(matches!(
                    intents.as_slice(),
                    [UiIntent::Voice(VoiceIntent::SavedSend(_))]
                )),
                _ => assert!(intents.is_empty(), "unavailable send cannot dispatch"),
            }
        }
    }

    #[test]
    fn retained_draft_visible_context_and_metadata_follow_focused_action() {
        for (phase, allowed, labels, visible_labels) in [
            (
                "review",
                true,
                ["Send", "Review", "Discard"],
                ["Send", "Review", "Discard"],
            ),
            (
                "review",
                false,
                ["Send unavailable", "Review", "Discard"],
                ["Send unavailable", "Review", "Discard"],
            ),
            (
                "failed",
                true,
                ["Send", "Review", "Discard"],
                ["Send", "Review", "Discard"],
            ),
            (
                "unknown",
                true,
                ["Send again", "Review", "Discard"],
                ["Resend", "Review", "Discard"],
            ),
            (
                "unknown",
                false,
                ["Send unavailable", "Review", "Discard"],
                ["No Send", "Review", "Discard"],
            ),
            ("sending", false, ["Sending"; 3], ["Sending"; 3]),
            ("sent", false, ["Sent"; 3], ["Sent"; 3]),
        ] {
            let mut runtime = retained_draft(phase, allowed);
            let count = if matches!(phase, "sending" | "sent") {
                1
            } else {
                3
            };
            for focus in 0..count {
                assert_eq!(runtime.focus_index, focus);
                let rendered = flatten::flatten(&runtime.scene_graph(1_000));
                if phase == "unknown" {
                    assert!(elements_with_role(&rendered, "context_label").is_empty());
                    assert_eq!(
                        elements_with_role(&rendered, "media_wheel_header_title")[0]
                            .props
                            .text
                            .as_deref(),
                        Some("Delivery unknown")
                    );
                    assert_eq!(
                        elements_with_role(&rendered, "media_wheel_header_counter")[0]
                            .props
                            .text
                            .as_deref(),
                        Some(visible_labels[focus])
                    );
                    assert_eq!(
                        runtime.active_title(),
                        format!("Delivery unknown · {}", labels[focus])
                    );
                } else {
                    assert!(elements_with_role(&rendered, "media_wheel_header_title").is_empty());
                    assert_eq!(
                        elements_with_role(&rendered, "context_label")[0]
                            .props
                            .text
                            .as_deref(),
                        Some(visible_labels[focus])
                    );
                    assert_eq!(runtime.active_title(), labels[focus]);
                }
                runtime.handle_input(InputAction::Advance, 1_020);
                assert!(
                    runtime.take_intents().is_empty(),
                    "advance never sends/captures"
                );
            }
        }
    }
}
