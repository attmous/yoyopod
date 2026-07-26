use crate::components::primitives::{container, label};
use crate::engine::{Element, Key};
use crate::scene::{roles, StopwatchModel};
use crate::ElementKind;

pub fn stopwatch(model: &StopwatchModel) -> Element {
    let button_x = if model.actions.len() == 1 {
        vec![76]
    } else {
        vec![28, 132]
    };

    model.actions.iter().enumerate().fold(
        container(roles::STOPWATCH_PANEL)
            .key(Key::Static("stopwatch_panel"))
            .child(
                label(roles::STOPWATCH_READOUT)
                    .key(Key::Static("stopwatch_readout"))
                    .text(&model.display),
            )
            .child(stopwatch_phase(model)),
        |panel, (index, action)| {
            panel.child(
                container(roles::BUTTON)
                    .key(Key::String(format!("stopwatch_action:{index}")))
                    .absolute(button_x[index], 126, 80, 72)
                    .selected(index == model.focus_index)
                    .child(
                        Element::new(ElementKind::Image, Some(roles::BUTTON_ICON))
                            .icon(&action.icon_key),
                    )
                    .child(label(roles::BUTTON_TITLE).text(&action.title)),
            )
        },
    )
}

fn stopwatch_phase(model: &StopwatchModel) -> Element {
    let phase = container(roles::STOPWATCH_PHASE)
        .key(Key::Static("stopwatch_phase"))
        .child(
            label(roles::STOPWATCH_PHASE_LABEL)
                .key(Key::Static("stopwatch_phase_label"))
                .text(model.phase.label()),
        );

    if model.phase == crate::scene::StopwatchVisualPhase::Running {
        phase.child(container(roles::STOPWATCH_PHASE_DOT).key(Key::Static("stopwatch_phase_dot")))
    } else {
        phase
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scene::{ButtonModel, StopwatchVisualPhase};

    fn descendants_with_role<'a>(element: &'a Element, role: &str) -> Vec<&'a Element> {
        let mut found = Vec::new();
        if element.role == Some(role) {
            found.push(element);
        }
        for child in &element.children {
            found.extend(descendants_with_role(child, role));
        }
        found
    }

    #[test]
    fn phase_label_and_live_dot_follow_the_explicit_visual_phase() {
        for (phase, expected_label, expected_dot_count) in [
            (StopwatchVisualPhase::Ready, "Ready", 0),
            (StopwatchVisualPhase::Running, "Running", 1),
            (StopwatchVisualPhase::Paused, "Paused", 0),
        ] {
            let element = stopwatch(&StopwatchModel {
                display: "00:12.3".to_string(),
                phase,
                actions: vec![ButtonModel {
                    title: "Pause".to_string(),
                    icon_key: "pause_sm".to_string(),
                }],
                focus_index: 0,
            });

            assert_eq!(
                descendants_with_role(&element, roles::STOPWATCH_PHASE_LABEL)[0]
                    .props
                    .text
                    .as_deref(),
                Some(expected_label)
            );
            assert_eq!(
                descendants_with_role(&element, roles::STOPWATCH_PHASE_DOT).len(),
                expected_dot_count
            );
        }
    }

    #[test]
    fn paused_stopwatch_centers_readout_and_exposes_two_actions() {
        let element = stopwatch(&StopwatchModel {
            display: "00:12.3".to_string(),
            phase: StopwatchVisualPhase::Paused,
            actions: vec![
                ButtonModel {
                    title: "Resume".to_string(),
                    icon_key: "play_sm".to_string(),
                },
                ButtonModel {
                    title: "Reset".to_string(),
                    icon_key: "reset_sm".to_string(),
                },
            ],
            focus_index: 1,
        });

        assert_eq!(element.children[0].props.text.as_deref(), Some("00:12.3"));
        assert_eq!(element.children[1].props.selected, Some(false));
        assert_eq!(element.children[2].props.selected, Some(true));
        assert_eq!(
            element.children[2].children[0].props.icon_key.as_deref(),
            Some("reset_sm")
        );
    }
}
