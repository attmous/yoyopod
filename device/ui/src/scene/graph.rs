use yoyopod_protocol::ui::UiScreen;

use crate::theme::ColorScheme;

use super::{HudScene, Modal, Scene};

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RouteParams {
    pub selected_id: Option<String>,
}

#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ActorState {
    pub focus_index: usize,
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct GlobalClock {
    pub started_ms: u64,
    pub now_ms: u64,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ScenePushFrame {
    pub route: UiScreen,
    pub params: RouteParams,
    pub cached_state: SceneCacheEntry,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SceneCacheEntry {
    Discarded,
    Retained { actor_state: ActorState },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SceneGraph {
    pub color_scheme: ColorScheme,
    pub hud: HudScene,
    pub active: Scene,
    pub history: Vec<ScenePushFrame>,
    pub modal_stack: Vec<Modal>,
    pub global_clock: GlobalClock,
}
