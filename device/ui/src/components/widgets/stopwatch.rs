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
            ),
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

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scene::ButtonModel;

    #[test]
    fn paused_stopwatch_centers_readout_and_exposes_two_actions() {
        let element = stopwatch(&StopwatchModel {
            display: "00:12.3".to_string(),
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
