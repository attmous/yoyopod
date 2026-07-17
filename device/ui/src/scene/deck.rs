use crate::animation::{presets, ActorRef, Timeline, TimelineRef, TrackIndex};
use crate::components::widgets::{
    call_panel as call_panel_widget, card as card_widget, list_row as list_row_widget,
    wheel_item as wheel_item_widget, CallPanelProps,
};
use crate::engine::{AnimSlot, Element, Key};
use crate::scene::roles;
use crate::ElementKind;

use super::RegionId;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FocusPolicy {
    None,
    Wrap,
    Clamp,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Deck {
    pub kind: DeckKind,
    pub region: RegionId,
    pub items: Vec<DeckItem>,
    pub focus_index: usize,
    pub focus_policy: FocusPolicy,
    pub item_anim: DeckItemAnim,
    pub swap_anim: Option<crate::animation::Transition>,
    pub recycle_window: Option<usize>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeckKind {
    CardRow,
    List,
    Wheel,
    Page,
    Grid,
    Buttons,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeckItem {
    pub key: Key,
    pub render: ItemRender,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ItemRender {
    Companion,
    Card(CardModel),
    Row(RowModel),
    Wheel(WheelItemModel),
    Page(PageModel),
    Button(ButtonModel),
    CallPanel(CallPanelModel),
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CardModel {
    pub title: String,
    pub subtitle: String,
    pub icon_key: String,
    pub accent: u32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RowModel {
    pub id: String,
    pub title: String,
    pub subtitle: String,
    pub icon_key: String,
    pub selected: bool,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WheelItemModel {
    pub title: String,
    pub subtitle: String,
    pub variant: WheelItemVariant,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WheelItemVariant {
    Icon { icon_key: String },
    Media { initial: String, plate_rgb: u32 },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PageModel {
    pub title: String,
    pub body: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ButtonModel {
    pub title: String,
    pub icon_key: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CallPanelModel {
    pub title: String,
    pub state: String,
    pub muted: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeckItemAnim {
    None,
    ScaleOnFocus {
        from_permille: u16,
        to_permille: u16,
    },
    BreatheWhenFocused,
    StaggerEnter {
        delay_per_index_ms: u32,
    },
}

impl Deck {
    pub fn element(&self, index: usize) -> Element {
        let mut element = Element::new(ElementKind::Container, Some(deck_role(self.kind)))
            .key(Key::Indexed(index))
            .child(
                Element::new(ElementKind::Container, Some(roles::DECK_REGION))
                    .key(Key::Static("deck_region"))
                    .region(self.region),
            );
        let short_wheel_offset = if self.kind == DeckKind::Wheel && self.items.len() < 3 {
            80
        } else {
            0
        };
        let focused_item_index = self.normalized_focus_index();
        for (visible_index, (item_index, item)) in self.visible_items().enumerate() {
            let mut item_element = deck_item_element(
                item,
                Some(item_index) == focused_item_index,
                self.item_anim,
                index,
                visible_index,
            );
            if short_wheel_offset != 0 {
                item_element = item_element.offset_y(short_wheel_offset);
            }
            element = element.child(item_element);
        }
        element
    }

    fn visible_items(&self) -> impl Iterator<Item = (usize, &DeckItem)> {
        self.visible_indices()
            .into_iter()
            .map(|index| (index, &self.items[index]))
    }

    fn visible_indices(&self) -> Vec<usize> {
        let len = self.items.len();
        if len == 0 {
            return Vec::new();
        }
        if self.kind != DeckKind::Wheel || self.focus_policy != FocusPolicy::Wrap {
            return self.visible_range().collect();
        }

        let focus = self.focus_index % len;
        let window = self.recycle_window.unwrap_or(len).clamp(1, len);
        let focus_slot = if window == 2 { 0 } else { window / 2 };
        (0..window)
            .map(|slot| (focus + len + slot - focus_slot) % len)
            .collect()
    }

    fn visible_range(&self) -> std::ops::Range<usize> {
        let len = self.items.len();
        if len == 0 {
            return 0..0;
        }

        let focus = self.focus_index.min(len.saturating_sub(1));
        let window = match self.kind {
            DeckKind::Page => 1,
            _ => self.recycle_window.unwrap_or(len),
        }
        .clamp(1, len);

        let mut start = focus.saturating_sub(window / 2);
        if start + window > len {
            start = len - window;
        }
        start..start + window
    }

    pub fn focused_visible_index(&self) -> usize {
        let Some(focus) = self.normalized_focus_index() else {
            return 0;
        };
        self.visible_indices()
            .iter()
            .position(|index| *index == focus)
            .unwrap_or(0)
    }

    fn normalized_focus_index(&self) -> Option<usize> {
        (!self.items.is_empty()).then(|| match self.focus_policy {
            FocusPolicy::Wrap => self.focus_index % self.items.len(),
            FocusPolicy::None | FocusPolicy::Clamp => self.focus_index.min(self.items.len() - 1),
        })
    }

    pub fn enter_timeline(&self) -> Option<Timeline> {
        match self.item_anim {
            DeckItemAnim::StaggerEnter { delay_per_index_ms } => {
                Some(presets::stagger_enter(delay_per_index_ms))
            }
            DeckItemAnim::None
            | DeckItemAnim::ScaleOnFocus { .. }
            | DeckItemAnim::BreatheWhenFocused => None,
        }
    }

    pub fn item_timeline(&self, deck_index: usize) -> Option<Timeline> {
        match self.item_anim {
            DeckItemAnim::BreatheWhenFocused if !self.items.is_empty() => Some(
                presets::breathe_focused_item(deck_index, self.focused_visible_index()),
            ),
            DeckItemAnim::None
            | DeckItemAnim::ScaleOnFocus { .. }
            | DeckItemAnim::StaggerEnter { .. }
            | DeckItemAnim::BreatheWhenFocused => None,
        }
    }

    pub fn swap_timeline(&self) -> Option<Timeline> {
        self.swap_anim
            .as_ref()
            .map(|transition| transition.timeline())
    }
}

fn deck_item_element(
    item: &DeckItem,
    selected: bool,
    item_anim: DeckItemAnim,
    deck_index: usize,
    visible_index: usize,
) -> Element {
    let is_wheel = matches!(item.render, ItemRender::Wheel(_));
    let element = match &item.render {
        ItemRender::Companion => companion_element().key(item.key.clone()),
        ItemRender::Card(card) => card_widget(card).key(item.key.clone()),
        ItemRender::Row(row) => list_row_widget(row, selected, item.key.clone()),
        ItemRender::Wheel(model) => wheel_item_widget(model, selected, item.key.clone()),
        ItemRender::Page(page) => Element::new(ElementKind::Container, Some(roles::PAGE))
            .key(item.key.clone())
            .child(Element::new(ElementKind::Label, Some(roles::PAGE_TITLE)).text(&page.title))
            .child(Element::new(ElementKind::Label, Some(roles::PAGE_BODY)).text(&page.body)),
        ItemRender::CallPanel(call) => call_panel_widget(&CallPanelProps {
            title: call.title.clone(),
            state: call.state.clone(),
            muted: call.muted,
        })
        .key(item.key.clone()),
        ItemRender::Button(button) => Element::new(ElementKind::Container, Some(roles::BUTTON))
            .key(item.key.clone())
            .child(
                Element::new(ElementKind::Image, Some(roles::BUTTON_ICON)).icon(&button.icon_key),
            )
            .child(Element::new(ElementKind::Label, Some(roles::BUTTON_TITLE)).text(&button.title)),
    }
    .actor(ActorRef::DeckItem {
        deck: deck_index,
        index: visible_index,
    });
    match item_anim {
        DeckItemAnim::StaggerEnter { .. } => element.with_anim(AnimSlot {
            timeline: TimelineRef(presets::STAGGER_ENTER_TIMELINE_ID),
            track: TrackIndex(visible_index.min(3)),
        }),
        DeckItemAnim::ScaleOnFocus {
            from_permille,
            to_permille,
        } => {
            let element = element.scale_permille(if selected {
                i32::from(to_permille)
            } else {
                i32::from(from_permille)
            });
            if is_wheel {
                element.opacity(if selected { 255 } else { 115 })
            } else {
                element
            }
        }
        DeckItemAnim::BreatheWhenFocused => {
            element.scale_permille(if selected { 1000 } else { 960 })
        }
        DeckItemAnim::None => element,
    }
}

fn companion_element() -> Element {
    let eye = |key: &'static str| {
        Element::new(ElementKind::Container, Some(roles::COMPANION_EYE))
            .key(Key::Static(key))
            .child(
                Element::new(ElementKind::Container, Some(roles::COMPANION_CATCHLIGHT))
                    .key(Key::String(format!("{key}:catchlight"))),
            )
    };

    Element::new(ElementKind::Container, Some(roles::COMPANION))
        .child(
            Element::new(ElementKind::Container, Some(roles::COMPANION_BODY))
                .key(Key::Static("companion_body")),
        )
        .child(eye("companion_eye_left"))
        .child(eye("companion_eye_right"))
        .child(
            Element::new(ElementKind::Container, Some(roles::COMPANION_MOUTH))
                .key(Key::Static("companion_mouth")),
        )
}

const fn deck_role(kind: DeckKind) -> &'static str {
    match kind {
        DeckKind::CardRow => roles::DECK_CARD_ROW,
        DeckKind::List => roles::DECK_LIST,
        DeckKind::Wheel => roles::DECK_WHEEL,
        DeckKind::Page => roles::DECK_PAGE,
        DeckKind::Grid => roles::DECK_GRID,
        DeckKind::Buttons => roles::DECK_BUTTONS,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn wheel(item_count: usize, focus_index: usize) -> Deck {
        Deck {
            kind: DeckKind::Wheel,
            region: RegionId::Auto,
            items: (0..item_count)
                .map(|index| DeckItem {
                    key: Key::Indexed(index),
                    render: ItemRender::Wheel(WheelItemModel {
                        title: format!("Item {index}"),
                        subtitle: String::new(),
                        variant: WheelItemVariant::Icon {
                            icon_key: "icon_playlists".to_string(),
                        },
                    }),
                })
                .collect(),
            focus_index,
            focus_policy: FocusPolicy::Wrap,
            item_anim: DeckItemAnim::ScaleOnFocus {
                from_permille: 700,
                to_permille: 1000,
            },
            swap_anim: None,
            recycle_window: Some(3),
        }
    }

    #[test]
    fn wheel_window_wraps_around_the_first_item() {
        let deck = wheel(7, 0);
        assert_eq!(deck.visible_indices(), vec![6, 0, 1]);
        assert_eq!(deck.focused_visible_index(), 1);
    }

    #[test]
    fn two_item_wheel_never_duplicates_a_peek() {
        let deck = wheel(2, 0);
        assert_eq!(deck.visible_indices(), vec![0, 1]);

        let element = deck.element(0);
        let wheel_items = &element.children[1..];
        assert_eq!(wheel_items[0].props.offset_y, Some(80));
        assert_eq!(wheel_items[1].props.offset_y, Some(80));
    }

    #[test]
    fn wheel_peeks_are_scaled_and_dimmed() {
        let element = wheel(3, 0).element(0);
        let wheel_items = &element.children[1..];
        assert_eq!(wheel_items[0].props.scale_permille, Some(700));
        assert_eq!(wheel_items[0].props.opacity, Some(115));
        assert_eq!(wheel_items[1].props.scale_permille, Some(1000));
        assert_eq!(wheel_items[1].props.opacity, Some(255));
    }

    #[test]
    fn wheel_normalizes_wrapped_focus_before_selecting() {
        let element = wheel(3, 4).element(0);
        let wheel_items = &element.children[1..];
        assert_eq!(wheel_items[1].props.scale_permille, Some(1000));
        assert_eq!(wheel_items[1].props.opacity, Some(255));
    }
}
