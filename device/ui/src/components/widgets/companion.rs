use crate::engine::{Element, Key};
use crate::scene::roles;
use crate::ElementKind;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CompanionVariant {
    Blob,
    Owl,
    Cat,
    Bunny,
    Robot,
}

impl CompanionVariant {
    pub fn from_setting(value: &str) -> Self {
        match value.trim().to_ascii_lowercase().as_str() {
            "owl" => Self::Owl,
            "cat" => Self::Cat,
            "bunny" => Self::Bunny,
            "robot" => Self::Robot,
            _ => Self::Blob,
        }
    }

    pub const fn name(self) -> &'static str {
        match self {
            Self::Blob => "Blob",
            Self::Owl => "Owl",
            Self::Cat => "Cat",
            Self::Bunny => "Bunny",
            Self::Robot => "Robot",
        }
    }

    const fn icon_key(self) -> &'static str {
        match self {
            Self::Blob => "companion_blob",
            Self::Owl => "companion_owl",
            Self::Cat => "companion_cat",
            Self::Bunny => "companion_bunny",
            Self::Robot => "companion_robot",
        }
    }

    const fn panel_rect(self) -> (i32, i32, i32, i32) {
        match self {
            Self::Blob => (63, 68, 114, 114),
            Self::Owl => (65, 52, 110, 140),
            Self::Cat => (50, 57, 140, 140),
            Self::Bunny => (60, 40, 120, 160),
            Self::Robot => (65, 46, 110, 150),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CompanionModel {
    pub variant: CompanionVariant,
}

pub fn companion(model: &CompanionModel) -> Element {
    let (x, y, width, height) = model.variant.panel_rect();
    Element::new(ElementKind::Container, Some(roles::COMPANION))
        .absolute(x, y, width, height)
        .child(
            Element::new(ElementKind::Image, Some(roles::COMPANION_SPRITE))
                .key(Key::Static("companion_sprite"))
                .icon(model.variant.icon_key())
                .absolute(0, 0, width, height),
        )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::Layout;

    #[test]
    fn settings_map_to_typed_variants_with_a_safe_blob_fallback() {
        assert_eq!(CompanionVariant::from_setting("OWL"), CompanionVariant::Owl);
        assert_eq!(
            CompanionVariant::from_setting(" bunny "),
            CompanionVariant::Bunny
        );
        assert_eq!(
            CompanionVariant::from_setting("unknown"),
            CompanionVariant::Blob
        );
    }

    #[test]
    fn every_companion_uses_its_normative_panel_box_and_sprite() {
        let cases = [
            (CompanionVariant::Blob, (63, 68, 114, 114), "companion_blob"),
            (CompanionVariant::Owl, (65, 52, 110, 140), "companion_owl"),
            (CompanionVariant::Cat, (50, 57, 140, 140), "companion_cat"),
            (
                CompanionVariant::Bunny,
                (60, 40, 120, 160),
                "companion_bunny",
            ),
            (
                CompanionVariant::Robot,
                (65, 46, 110, 150),
                "companion_robot",
            ),
        ];

        for (variant, expected_rect, expected_icon) in cases {
            let element = companion(&CompanionModel { variant });
            let Layout::Absolute { x, y, w, h } = element.layout else {
                panic!("companion root must use an absolute panel box");
            };
            assert_eq!((x, y, w, h), expected_rect);
            assert_eq!(
                element.children[0].props.icon_key.as_deref(),
                Some(expected_icon)
            );
        }
    }
}
