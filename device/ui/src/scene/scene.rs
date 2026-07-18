use yoyopod_protocol::ui::UiScreen;

use crate::animation::Timeline;

use super::{Backdrop, Cursor, Deck, FxLayer, Modal, Stage};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Scene {
    pub id: SceneId,
    pub backdrop: Backdrop,
    pub stage: Stage,
    pub context: Option<String>,
    pub decks: Vec<Deck>,
    pub cursor: Option<Cursor>,
    pub fx: FxLayer,
    pub modal: Option<Modal>,
    pub timelines: Vec<Timeline>,
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
