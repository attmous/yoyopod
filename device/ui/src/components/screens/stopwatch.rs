use yoyopod_protocol::ui::UiScreen;

use crate::engine::Key;
use crate::scene::{
    Backdrop, ButtonModel, Cursor, Deck, DeckItem, DeckItemAnim, DeckKind, FocusPolicy, ItemRender,
    RegionId, Scene, SceneDefaults, SceneId, StopwatchModel,
};

pub(crate) const STOPWATCH_STAGE_PERI: u32 = 0xE7E5F7;

pub fn scene(
    defaults: &SceneDefaults,
    display: String,
    actions: Vec<ButtonModel>,
    focus_index: usize,
) -> Scene {
    let action_count = actions.len();
    Scene {
        id: SceneId::new(UiScreen::Stopwatch),
        backdrop: Backdrop::Solid(STOPWATCH_STAGE_PERI),
        stage: defaults.stage,
        context: None,
        decks: vec![Deck {
            kind: DeckKind::Page,
            region: RegionId::Auto,
            items: vec![DeckItem {
                key: Key::Static("stopwatch"),
                render: ItemRender::Stopwatch(StopwatchModel {
                    display,
                    actions,
                    focus_index,
                }),
            }],
            focus_index: 0,
            focus_policy: FocusPolicy::None,
            item_anim: DeckItemAnim::None,
            swap_anim: None,
            recycle_window: Some(1),
        }],
        cursor: Some(Cursor::UnderlineDots {
            count: action_count,
            focus: focus_index,
        }),
        fx: Default::default(),
        modal: None,
        timelines: Vec::new(),
    }
}
