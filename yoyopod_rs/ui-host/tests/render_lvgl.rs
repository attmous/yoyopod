use yoyopod_ui_host::render::lvgl::{RendererMode, RendererState};
use yoyopod_ui_host::runtime::UiScreen;

#[test]
fn renderer_mode_names_are_stable() {
    assert_eq!(RendererMode::Auto.as_str(), "auto");
    assert_eq!(RendererMode::Lvgl.as_str(), "lvgl");
    assert_eq!(RendererMode::Framebuffer.as_str(), "framebuffer");
}

#[test]
fn persistent_renderer_tracks_last_screen() {
    let mut state = RendererState::default();

    assert!(state.needs_rebuild(UiScreen::Hub));
    state.mark_screen_built(UiScreen::Hub);
    assert!(!state.needs_rebuild(UiScreen::Hub));
    assert!(state.needs_rebuild(UiScreen::Listen));
}
