use yoyopod_protocol::ui::{ListItemSnapshot, UiScreen};

use crate::engine::Key;
use crate::scene::{
    CallPanelModel, Cursor, Deck, DeckItem, DeckItemAnim, DeckKind, FocusPolicy, ItemRender,
    RegionId, RowModel, Scene, SceneDefaults, SceneId,
};

pub fn hero_scene(
    screen: UiScreen,
    defaults: &SceneDefaults,
    accent: u32,
    item_count: usize,
    focus: usize,
) -> Scene {
    Scene {
        id: SceneId::new(screen),
        backdrop: defaults.backdrop(accent),
        stage: defaults.stage,
        context: None,
        decks: vec![Deck {
            kind: DeckKind::CardRow,
            region: RegionId::HeroIcon,
            items: Vec::new(),
            focus_index: focus,
            focus_policy: FocusPolicy::Wrap,
            item_anim: DeckItemAnim::ScaleOnFocus {
                from_permille: 960,
                to_permille: 1000,
            },
            swap_anim: None,
            recycle_window: Some(3),
        }],
        cursor: Some(Cursor::UnderlineDots {
            count: item_count,
            focus,
        }),
        fx: defaults.fx_layer(accent),
        modal: None,
        timelines: defaults.fx_timelines(),
    }
}

pub fn list_scene(
    screen: UiScreen,
    defaults: &SceneDefaults,
    items: &[ListItemSnapshot],
    focus: usize,
    focus_policy: FocusPolicy,
) -> Scene {
    let rows = items.iter().map(row_model).collect::<Vec<_>>();
    let deck = Deck {
        kind: DeckKind::List,
        region: RegionId::ListBody,
        items: rows
            .into_iter()
            .map(|row| DeckItem {
                key: Key::String(row.id.clone()),
                render: ItemRender::Row(row),
            })
            .collect(),
        focus_index: focus,
        focus_policy,
        item_anim: DeckItemAnim::StaggerEnter {
            delay_per_index_ms: 40,
        },
        swap_anim: None,
        recycle_window: Some(4),
    };
    let cursor_index = deck.focused_visible_index();
    Scene {
        id: SceneId::new(screen),
        backdrop: defaults.backdrop(0x3ddd53),
        stage: defaults.stage,
        context: None,
        decks: vec![deck],
        cursor: Some(Cursor::RowGlow {
            index: cursor_index,
        }),
        fx: defaults.fx_layer(0x3ddd53),
        modal: None,
        timelines: defaults.fx_timelines(),
    }
}

pub fn action_scene(screen: UiScreen, defaults: &SceneDefaults, focus: usize) -> Scene {
    Scene {
        id: SceneId::new(screen),
        backdrop: defaults.backdrop(0x00d4ff),
        stage: defaults.stage,
        context: None,
        decks: vec![Deck {
            kind: DeckKind::Buttons,
            region: RegionId::ButtonRow,
            items: Vec::new(),
            focus_index: focus,
            focus_policy: FocusPolicy::Wrap,
            item_anim: DeckItemAnim::ScaleOnFocus {
                from_permille: 960,
                to_permille: 1000,
            },
            swap_anim: None,
            recycle_window: None,
        }],
        cursor: Some(Cursor::UnderlineDots { count: 3, focus }),
        fx: defaults.fx_layer(0x00d4ff),
        modal: None,
        timelines: defaults.fx_timelines(),
    }
}

pub fn call_scene(
    screen: UiScreen,
    defaults: &SceneDefaults,
    title: String,
    state: String,
    muted: bool,
) -> Scene {
    Scene {
        id: SceneId::new(screen),
        backdrop: defaults.backdrop(0x3ddd53),
        stage: defaults.stage,
        context: None,
        decks: vec![Deck {
            kind: DeckKind::Page,
            region: RegionId::ListBody,
            items: vec![DeckItem {
                key: Key::Static("call"),
                render: ItemRender::CallPanel(CallPanelModel {
                    title,
                    state,
                    muted,
                }),
            }],
            focus_index: 0,
            focus_policy: FocusPolicy::None,
            item_anim: DeckItemAnim::None,
            swap_anim: None,
            recycle_window: None,
        }],
        cursor: None,
        fx: defaults.fx_layer(0x3ddd53),
        modal: None,
        timelines: defaults.fx_timelines(),
    }
}

pub fn overlay_scene(
    screen: UiScreen,
    defaults: &SceneDefaults,
    modal: crate::scene::Modal,
) -> Scene {
    Scene {
        id: SceneId::new(screen),
        backdrop: defaults.backdrop(0x3ddd53),
        stage: defaults.stage,
        context: None,
        decks: Vec::new(),
        cursor: None,
        fx: defaults.fx_layer(0x3ddd53),
        modal: Some(modal),
        timelines: defaults.fx_timelines(),
    }
}

fn row_model(item: &ListItemSnapshot) -> RowModel {
    RowModel {
        id: item.id.clone(),
        title: item.title.clone(),
        subtitle: item.subtitle.clone(),
        icon_key: item.icon_key.clone(),
        selected: false,
    }
}
