use yoyopod_protocol::ui::UiScreen;

use crate::animation::Timeline;

use super::{Backdrop, Cursor, Deck, FxLayer, Modal, Stage};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Scene {
    pub id: SceneId,
    pub backdrop: Backdrop,
    pub stage: Stage,
    pub context: Option<SceneContext>,
    pub decks: Vec<Deck>,
    pub cursor: Option<Cursor>,
    pub fx: FxLayer,
    pub modal: Option<Modal>,
    pub timelines: Vec<Timeline>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WheelHeaderModel {
    pub title: String,
    pub counter: Option<String>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContextLabelModel {
    pub text: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SetupCounterModel {
    pub text: String,
}

impl ContextLabelModel {
    pub fn new(text: impl Into<String>) -> Self {
        Self { text: text.into() }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SceneContext {
    WheelHeader(WheelHeaderModel),
    Label(ContextLabelModel),
    SetupCounter(SetupCounterModel),
}

impl SceneContext {
    pub fn wheel_header(&self) -> Option<&WheelHeaderModel> {
        match self {
            Self::WheelHeader(header) => Some(header),
            Self::Label(_) => None,
            Self::SetupCounter(_) => None,
        }
    }

    pub fn label(&self) -> Option<&ContextLabelModel> {
        match self {
            Self::Label(label) => Some(label),
            Self::WheelHeader(_) => None,
            Self::SetupCounter(_) => None,
        }
    }

    pub fn setup_counter(&self) -> Option<&SetupCounterModel> {
        match self {
            Self::SetupCounter(counter) => Some(counter),
            Self::WheelHeader(_) | Self::Label(_) => None,
        }
    }
}

impl From<WheelHeaderModel> for SceneContext {
    fn from(value: WheelHeaderModel) -> Self {
        Self::WheelHeader(value)
    }
}

impl From<ContextLabelModel> for SceneContext {
    fn from(value: ContextLabelModel) -> Self {
        Self::Label(value)
    }
}

impl From<SetupCounterModel> for SceneContext {
    fn from(value: SetupCounterModel) -> Self {
        Self::SetupCounter(value)
    }
}

impl WheelHeaderModel {
    pub fn new(title: impl Into<String>, counter: Option<String>) -> Self {
        Self {
            title: title.into(),
            counter,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct SceneId {
    pub screen: UiScreen,
    pub generation: u32,
}

impl SceneId {
    pub const fn new(screen: UiScreen) -> Self {
        Self {
            screen,
            generation: 0,
        }
    }

    pub fn with_route_key(screen: UiScreen, route_key: Option<&str>) -> Self {
        Self {
            screen,
            generation: route_key.map(route_generation).unwrap_or(0),
        }
    }
}

fn route_generation(route_key: &str) -> u32 {
    route_key.bytes().fold(0x811c9dc5, |hash, byte| {
        hash.wrapping_mul(0x01000193) ^ u32::from(byte)
    })
}
