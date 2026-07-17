use crate::components::primitives::container;
use crate::engine::{Element, Key};
use crate::scene::roles;
use crate::ElementKind;

const INK: u32 = 0x1B1B1F;
const INK_300: u32 = 0x8A8076;
const ITEMS: [(&str, u32); 4] = [
    ("listen", 0x9DFC7C),
    ("talk", 0xA9A6E5),
    ("ask", 0xFFD06A),
    ("setup", 0xF37767),
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeckBarProps {
    pub focused_index: Option<usize>,
    pub visible: bool,
}

pub fn deck_bar(props: &DeckBarProps) -> Element {
    ITEMS.iter().enumerate().fold(
        container(roles::DECK_BAR)
            .key(Key::Static("deck_bar"))
            .visible(props.visible),
        |deck, (index, (icon, color))| {
            let focused = props.focused_index == Some(index);
            deck.child(
                container(roles::DECK_SLOT)
                    .key(Key::Indexed(index))
                    .child(
                        container(roles::DECK_PILL)
                            .key(Key::String(format!("deck_pill:{icon}")))
                            .accent(*color)
                            .visible(focused),
                    )
                    .child(
                        Element::new(ElementKind::Image, Some(roles::DECK_GLYPH))
                            .key(Key::String(format!("deck_icon:{icon}")))
                            .icon(format!("deck_{icon}"))
                            .accent(if focused { INK } else { INK_300 }),
                    ),
            )
        },
    )
}
