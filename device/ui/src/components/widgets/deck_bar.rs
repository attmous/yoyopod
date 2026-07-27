use crate::components::primitives::container;
use crate::engine::{Element, Key};
use crate::scene::roles;
use crate::ElementKind;

const INK: u32 = 0x1B1B1F;
const INK_300: u32 = 0x8A8076;
const ITEMS: [(&str, u32); 6] = [
    ("listen", 0x9DFC7C),
    ("talk", 0xA9A6E5),
    ("ask", 0xFFD06A),
    ("stopwatch", 0x78D5D0),
    ("flashlight", 0xFFB45C),
    ("setup", 0xF37767),
];

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeckBarProps {
    pub focused_index: Option<usize>,
    pub visible: bool,
    pub opacity: u8,
}

pub fn deck_bar(props: &DeckBarProps) -> Element {
    let active_index = props.focused_index.unwrap_or(0).min(ITEMS.len() - 1);
    let window_start = active_index.saturating_sub(3).min(ITEMS.len() - 4);

    ITEMS[window_start..window_start + 4]
        .iter()
        .enumerate()
        .fold(
            container(roles::DECK_BAR)
                .key(Key::Static("deck_bar"))
                .visible(props.visible)
                .opacity(props.opacity),
            |deck, (slot_index, (icon, color))| {
                let item_index = window_start + slot_index;
                let focused = props.focused_index == Some(item_index);
                deck.child(
                    container(roles::DECK_SLOT)
                        .key(Key::Indexed(slot_index))
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

#[cfg(test)]
mod tests {
    use super::*;

    fn icon_keys(focused_index: usize) -> Vec<String> {
        deck_bar(&DeckBarProps {
            focused_index: Some(focused_index),
            visible: true,
            opacity: 255,
        })
        .children
        .iter()
        .map(|slot| {
            slot.children[1]
                .props
                .icon_key
                .clone()
                .expect("deck slot icon")
        })
        .collect()
    }

    #[test]
    fn six_destinations_slide_through_four_fixed_slots() {
        assert_eq!(
            icon_keys(0),
            ["deck_listen", "deck_talk", "deck_ask", "deck_stopwatch"]
        );
        assert_eq!(
            icon_keys(4),
            ["deck_talk", "deck_ask", "deck_stopwatch", "deck_flashlight"]
        );
        assert_eq!(
            icon_keys(5),
            [
                "deck_ask",
                "deck_stopwatch",
                "deck_flashlight",
                "deck_setup"
            ]
        );
        assert_eq!(
            icon_keys(0),
            ["deck_listen", "deck_talk", "deck_ask", "deck_stopwatch"]
        );

        let stopwatch = deck_bar(&DeckBarProps {
            focused_index: Some(3),
            visible: true,
            opacity: 255,
        });
        assert_eq!(
            stopwatch.children[3].children[0].props.accent,
            Some(0x78D5D0)
        );
        let flashlight = deck_bar(&DeckBarProps {
            focused_index: Some(4),
            visible: true,
            opacity: 255,
        });
        assert_eq!(
            flashlight.children[3].children[0].props.accent,
            Some(0xFFB45C)
        );
    }
}
