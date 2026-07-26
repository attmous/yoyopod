use crate::components::primitives::{container, label};
use crate::engine::{Element, Key};
use crate::scene::{roles, ButtonModel, StopwatchModel, StopwatchVisualPhase};
use crate::ElementKind;

pub fn stopwatch(model: &StopwatchModel) -> Element {
    container(roles::STOPWATCH_PANEL)
        .key(Key::Static("stopwatch_panel"))
        .child(
            label(roles::STOPWATCH_READOUT)
                .key(Key::Static("stopwatch_readout"))
                .text(&model.display),
        )
        .child(stopwatch_phase(model.phase))
        .child(stopwatch_control_tray(model))
        .child(stopwatch_focus_dots(model))
}

fn stopwatch_phase(phase: StopwatchVisualPhase) -> Element {
    let phase_chip = container(roles::STOPWATCH_PHASE).key(Key::Static("stopwatch_phase"));
    if phase == StopwatchVisualPhase::Running {
        phase_chip
            .child(
                container(roles::STOPWATCH_PHASE_DOT)
                    .key(Key::Static("stopwatch_phase_dot"))
                    .absolute(14, 8, 6, 6),
            )
            .child(
                label(roles::STOPWATCH_PHASE_LABEL)
                    .key(Key::Static("stopwatch_phase_label"))
                    .absolute(25, 3, 49, 16)
                    .text(phase.label()),
            )
    } else {
        phase_chip.child(
            label(roles::STOPWATCH_PHASE_LABEL)
                .key(Key::Static("stopwatch_phase_label"))
                .absolute(8, 3, 72, 16)
                .text(phase.label()),
        )
    }
}

fn stopwatch_control_tray(model: &StopwatchModel) -> Element {
    model.actions.iter().enumerate().fold(
        container(roles::STOPWATCH_CONTROL_TRAY).key(Key::Static("stopwatch_control_tray")),
        |tray, (index, action)| {
            let (x, width) = action_bounds(model.actions.len(), index);
            tray.child(stopwatch_action(
                model.phase,
                action,
                index,
                x,
                width,
                index == model.focus_index,
            ))
        },
    )
}

fn stopwatch_action(
    phase: StopwatchVisualPhase,
    action: &ButtonModel,
    index: usize,
    x: i32,
    width: i32,
    selected: bool,
) -> Element {
    container(action_role(phase, index))
        .key(Key::String(format!("stopwatch_action:{index}")))
        .absolute(x, 7, width, 58)
        .selected(selected)
        .child(
            Element::new(ElementKind::Image, Some(roles::STOPWATCH_ACTION_ICON))
                .absolute((width - 24) / 2, 7, 24, 24)
                .icon(&action.icon_key),
        )
        .child(
            label(roles::STOPWATCH_ACTION_LABEL)
                .absolute(8, 36, width - 16, 16)
                .text(&action.title),
        )
}

const fn action_bounds(action_count: usize, index: usize) -> (i32, i32) {
    if action_count == 1 {
        (39, 126)
    } else if index == 0 {
        (6, 92)
    } else {
        (106, 92)
    }
}

const fn action_role(phase: StopwatchVisualPhase, index: usize) -> &'static str {
    match (phase, index) {
        (StopwatchVisualPhase::Ready, _) | (StopwatchVisualPhase::Paused, 0) => {
            roles::STOPWATCH_ACTION_PRIMARY
        }
        (StopwatchVisualPhase::Running, _) => roles::STOPWATCH_ACTION_PAUSE,
        (StopwatchVisualPhase::Paused, _) => roles::STOPWATCH_ACTION_RESET,
    }
}

fn stopwatch_focus_dots(model: &StopwatchModel) -> Element {
    (0..model.actions.len()).fold(
        container(roles::CURSOR_DOTS)
            .key(Key::Static("stopwatch_focus_dots"))
            .absolute(94, 194, 52, 8),
        |dots, index| {
            dots.child(
                container(roles::CURSOR_DOT)
                    .key(Key::String(format!("stopwatch_focus_dot:{index}")))
                    .absolute(index as i32 * 10, 2, 4, 4)
                    .selected(index == model.focus_index),
            )
        },
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::Layout;
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
    fn ready_and_running_use_one_centered_phase_aware_action() {
        for (phase, title, icon_key, action_role) in [
            (
                StopwatchVisualPhase::Ready,
                "Start",
                "play_sm",
                roles::STOPWATCH_ACTION_PRIMARY,
            ),
            (
                StopwatchVisualPhase::Running,
                "Pause",
                "pause_sm",
                roles::STOPWATCH_ACTION_PAUSE,
            ),
        ] {
            let element = stopwatch(&StopwatchModel {
                display: "00:00.0".to_string(),
                phase,
                actions: vec![ButtonModel {
                    title: title.to_string(),
                    icon_key: icon_key.to_string(),
                }],
                focus_index: 0,
            });

            let actions = descendants_with_role(&element, action_role);
            assert_eq!(actions.len(), 1);
            assert_eq!(
                actions[0].layout,
                Layout::Absolute {
                    x: 39,
                    y: 7,
                    w: 126,
                    h: 58,
                }
            );
            assert_eq!(actions[0].props.selected, Some(true));
            assert_eq!(
                descendants_with_role(actions[0], roles::STOPWATCH_ACTION_LABEL)[0]
                    .props
                    .text
                    .as_deref(),
                Some(title)
            );
            assert_eq!(descendants_with_role(&element, roles::CURSOR_DOT).len(), 1);
        }
    }

    #[test]
    fn paused_state_uses_two_semantic_actions_and_two_focus_dots() {
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

        assert_eq!(
            descendants_with_role(&element, roles::STOPWATCH_READOUT)[0]
                .props
                .text
                .as_deref(),
            Some("00:12.3")
        );
        let resume = descendants_with_role(&element, roles::STOPWATCH_ACTION_PRIMARY)[0];
        let reset = descendants_with_role(&element, roles::STOPWATCH_ACTION_RESET)[0];
        assert_eq!(
            resume.layout,
            Layout::Absolute {
                x: 6,
                y: 7,
                w: 92,
                h: 58,
            }
        );
        assert_eq!(
            reset.layout,
            Layout::Absolute {
                x: 106,
                y: 7,
                w: 92,
                h: 58,
            }
        );
        assert_eq!(resume.props.selected, Some(false));
        assert_eq!(reset.props.selected, Some(true));
        assert_eq!(
            descendants_with_role(reset, roles::STOPWATCH_ACTION_ICON)[0]
                .props
                .icon_key
                .as_deref(),
            Some("reset_sm")
        );
        let dots = descendants_with_role(&element, roles::CURSOR_DOT);
        assert_eq!(dots.len(), 2);
        assert_eq!(dots[0].props.selected, Some(false));
        assert_eq!(dots[1].props.selected, Some(true));
    }
}
