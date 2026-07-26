use yoyopod_protocol::ui::{ListItemSnapshot, RuntimeSnapshot, UiScreen};

use crate::scene::{
    Backdrop, Deck, DeckItem, DeckItemAnim, DeckKind, FocusPolicy, ItemRender, RegionId, Scene,
    SceneDefaults, SceneId, WheelItemModel, WheelItemVariant,
};

const LISTEN_STAGE_LIME: u32 = 0xE6FDE0;

pub struct ListenProps {
    pub defaults: SceneDefaults,
    pub items: Vec<WheelItemModel>,
    pub focus: usize,
}

pub fn props_from(
    snapshot: &RuntimeSnapshot,
    focus: usize,
    defaults: SceneDefaults,
) -> ListenProps {
    ListenProps {
        defaults,
        items: items(snapshot)
            .iter()
            .map(|item| WheelItemModel {
                title: item.title.clone(),
                subtitle: item.subtitle.clone(),
                variant: WheelItemVariant::Icon {
                    icon_key: item.icon_key.clone(),
                },
            })
            .collect(),
        focus,
    }
}

pub fn items(_snapshot: &RuntimeSnapshot) -> Vec<ListItemSnapshot> {
    crate::application::options::listen_items(_snapshot)
}

pub fn scene(props: &ListenProps) -> Scene {
    let deck = Deck {
        kind: DeckKind::Wheel,
        region: RegionId::Auto,
        items: props
            .items
            .iter()
            .enumerate()
            .map(|(index, item)| DeckItem {
                key: crate::engine::Key::Indexed(index),
                render: ItemRender::Wheel(item.clone()),
            })
            .collect(),
        focus_index: props.focus,
        focus_policy: FocusPolicy::Wrap,
        item_anim: DeckItemAnim::ScaleOnFocus {
            from_permille: 700,
            to_permille: 1000,
        },
        swap_anim: None,
        recycle_window: Some(3),
    };
    Scene {
        id: SceneId::new(UiScreen::Listen),
        backdrop: Backdrop::Solid(LISTEN_STAGE_LIME),
        stage: props.defaults.stage,
        context: None,
        decks: vec![deck],
        cursor: None,
        fx: Default::default(),
        modal: None,
        timelines: Vec::new(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scene::defaults_for;

    #[test]
    fn listen_root_is_a_three_slot_wrapping_wheel() {
        let snapshot = RuntimeSnapshot::default();
        let props = props_from(&snapshot, 0, defaults_for(UiScreen::Listen));
        let scene = scene(&props);
        let deck = &scene.decks[0];

        assert_eq!(scene.backdrop, Backdrop::Solid(LISTEN_STAGE_LIME));
        assert_eq!(deck.kind, DeckKind::Wheel);
        assert_eq!(deck.focus_policy, FocusPolicy::Wrap);
        assert_eq!(deck.recycle_window, Some(3));
        assert_eq!(deck.focused_visible_index(), 1);
        assert!(scene.cursor.is_none());
    }
}
