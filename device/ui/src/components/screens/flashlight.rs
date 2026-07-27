use yoyopod_protocol::ui::UiScreen;

use crate::scene::{Backdrop, Scene, SceneDefaults, SceneId};

pub fn scene(defaults: &SceneDefaults) -> Scene {
    Scene {
        id: SceneId::new(UiScreen::Flashlight),
        backdrop: Backdrop::Solid(0xFFFFFF),
        stage: defaults.stage,
        context: None,
        decks: Vec::new(),
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
    fn flashlight_scene_contains_only_an_opaque_white_backdrop() {
        let scene = scene(&defaults_for(UiScreen::Flashlight));
        assert_eq!(scene.backdrop, Backdrop::Solid(0xFFFFFF));
        assert!(scene.decks.is_empty());
        assert!(scene.cursor.is_none());
        assert!(scene.fx.halos.is_empty());
        assert!(scene.fx.pulses.is_empty());
        assert!(scene.fx.particles.is_empty());
        assert!(scene.fx.glows.is_empty());
        assert!(scene.timelines.is_empty());
    }
}
