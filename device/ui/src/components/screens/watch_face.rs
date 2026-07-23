use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

use crate::engine::Key;
use crate::scene::{
    Backdrop, Deck, DeckItem, DeckItemAnim, DeckKind, FocusPolicy, FxLayer, ItemRender, RegionId,
    Scene, SceneId, Stage, WatchFaceModel,
};

const MIDNIGHT: u32 = 0x090B14;

pub fn scene(snapshot: &RuntimeSnapshot, date: String, time: String) -> Scene {
    Scene {
        id: SceneId::new(UiScreen::Hub),
        backdrop: Backdrop::Solid(MIDNIGHT),
        stage: Stage::CenteredHeroIcon,
        context: None,
        decks: vec![Deck {
            kind: DeckKind::Page,
            region: RegionId::Auto,
            items: vec![DeckItem {
                key: Key::Static("ambient_watch_face"),
                render: ItemRender::WatchFace(WatchFaceModel {
                    date,
                    time,
                    battery_percent: snapshot.power.battery_percent,
                    charging: snapshot.power.charging,
                    power_available: snapshot.power.power_available,
                }),
            }],
            focus_index: 0,
            focus_policy: FocusPolicy::None,
            item_anim: DeckItemAnim::None,
            swap_anim: None,
            recycle_window: Some(1),
        }],
        cursor: None,
        fx: FxLayer::default(),
        modal: None,
        timelines: Vec::new(),
    }
}
