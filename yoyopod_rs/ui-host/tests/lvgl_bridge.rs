use std::path::Path;

use yoyopod_ui_host::framebuffer::Framebuffer;
use yoyopod_ui_host::hub::HubSnapshot;
use yoyopod_ui_host::lvgl_bridge::{
    default_shim_candidates, render_hub_with_lvgl, render_view_with_lvgl,
};
use yoyopod_ui_host::runtime::{RuntimeSnapshot, UiRuntime};

#[test]
fn missing_explicit_shim_path_returns_contextual_error() {
    let mut framebuffer = Framebuffer::new(240, 280);
    let error = render_hub_with_lvgl(
        &mut framebuffer,
        &HubSnapshot::static_default(),
        Some(Path::new("missing-yoyopod-lvgl-shim.so")),
    )
    .expect_err("missing shim must fail");

    assert!(error.to_string().contains("native LVGL shim"));
}

#[test]
fn default_shim_candidates_include_repo_native_build() {
    let candidates = default_shim_candidates(Path::new("/repo"));

    assert!(candidates.iter().any(|path| path
        .to_string_lossy()
        .replace('\\', "/")
        .contains("yoyopod/ui/lvgl_binding/native/build")));
}

#[test]
fn missing_explicit_shim_path_returns_contextual_error_for_runtime_view() {
    let mut framebuffer = Framebuffer::new(240, 280);
    let mut runtime = UiRuntime::default();
    runtime.apply_snapshot(RuntimeSnapshot::default());
    let view = runtime.active_view();
    let error = render_view_with_lvgl(
        &mut framebuffer,
        &view,
        runtime.snapshot(),
        Some(Path::new("missing-yoyopod-lvgl-shim.so")),
    )
    .expect_err("missing shim must fail");

    assert!(error.to_string().contains("native LVGL shim"));
}
