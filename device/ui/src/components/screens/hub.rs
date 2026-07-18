use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

use crate::engine::Key;
use crate::scene::{
    Deck, DeckItem, DeckItemAnim, DeckKind, FocusPolicy, ItemRender, RegionId, Scene,
    SceneDefaults, SceneId,
};

pub struct HubProps {
    pub defaults: SceneDefaults,
    pub companion: DeckItem,
}

pub fn props_from(_snapshot: &RuntimeSnapshot, _focus: usize, defaults: SceneDefaults) -> HubProps {
    HubProps {
        defaults,
        companion: DeckItem {
            key: Key::Static("home_companion"),
            render: ItemRender::Companion,
        },
    }
}

pub fn scene(props: &HubProps) -> Scene {
    Scene {
        id: SceneId::new(UiScreen::Hub),
        backdrop: props.defaults.backdrop(0xFCE6D2),
        stage: props.defaults.stage,
        context: None,
        decks: vec![Deck {
            kind: DeckKind::CardRow,
            region: RegionId::Auto,
            items: vec![props.companion.clone()],
            focus_index: 0,
            focus_policy: FocusPolicy::None,
            item_anim: DeckItemAnim::BreatheWhenFocused,
            swap_anim: None,
            recycle_window: Some(1),
        }],
        cursor: None,
        fx: Default::default(),
        modal: None,
        timelines: Vec::new(),
    }
}
