use crate::animation::{presets, ActorRef, Timeline, TimelineRef, TrackIndex};
use crate::components::widgets::{
    call_panel as call_panel_widget, card as card_widget, list_row as list_row_widget,
    CallPanelProps,
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
        for (visible_index, (item_index, item)) in self.visible_items().enumerate() {
            element = element.child(deck_item_element(
                item,
                item_index == self.focus_index,
                self.item_anim,
                index,
                visible_index,
            ));
        }
        element
    }

    fn visible_items(&self) -> impl Iterator<Item = (usize, &DeckItem)> {
        let range = self.visible_range();
        self.items
            .iter()
            .enumerate()
            .skip(range.start)
            .take(range.end.saturating_sub(range.start))
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
        let range = self.visible_range();
        self.focus_index
            .min(self.items.len().saturating_sub(1))
            .saturating_sub(range.start)
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
    let element = match &item.render {
        ItemRender::Companion => companion_element().key(item.key.clone()),
        ItemRender::Card(card) => card_widget(card).key(item.key.clone()),
        ItemRender::Row(row) => list_row_widget(row, selected, item.key.clone()),
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
        } => element.scale_permille(if selected {
            i32::from(to_permille)
        } else {
            i32::from(from_permille)
        }),
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
        DeckKind::Page => roles::DECK_PAGE,
        DeckKind::Grid => roles::DECK_GRID,
        DeckKind::Buttons => roles::DECK_BUTTONS,
    }
}
