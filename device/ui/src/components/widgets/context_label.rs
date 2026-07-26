use crate::components::primitives::label;
use crate::engine::Key;
use crate::scene::{roles, ContextLabelModel};

pub fn context_label(model: &ContextLabelModel) -> crate::engine::Element {
    label(roles::CONTEXT_LABEL)
        .key(Key::Static("context_label"))
        .text(&model.text)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn depth_context_uses_one_semantic_label() {
        let element = context_label(&ContextLabelModel::new("MAMA"));

        assert_eq!(element.role, Some(roles::CONTEXT_LABEL));
        assert_eq!(element.props.text.as_deref(), Some("MAMA"));
        assert!(element.children.is_empty());
    }
}
