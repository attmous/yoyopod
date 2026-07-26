use crate::components::primitives::{container, image, label};
use crate::scene::{roles, EmptyStateModel};

const INK: u32 = 0x1B1B1F;

pub fn empty_state(model: &EmptyStateModel) -> crate::engine::Element {
    container(roles::EMPTY_STATE)
        .child(
            container(roles::EMPTY_PLUS).accent(model.accent).child(
                image(roles::EMPTY_PLUS_ICON)
                    .icon(&model.icon_key)
                    .accent(INK),
            ),
        )
        .child(label(roles::EMPTY_HINT).text(&model.message))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn empty_state_uses_the_designed_plus_and_hint_roles() {
        let element = empty_state(&EmptyStateModel {
            icon_key: "plus".to_string(),
            message: "No contacts yet.\nAsk a grown-up!".to_string(),
            accent: 0xA9A6E5,
        });

        assert_eq!(element.role, Some(roles::EMPTY_STATE));
        assert_eq!(element.children[0].role, Some(roles::EMPTY_PLUS));
        assert_eq!(
            element.children[0].children[0].role,
            Some(roles::EMPTY_PLUS_ICON)
        );
        assert_eq!(element.children[1].role, Some(roles::EMPTY_HINT));
    }
}
