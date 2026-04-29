use yoyopod_ui_host::framebuffer::{rgb565, Framebuffer};
use yoyopod_ui_host::hub::HubSnapshot;
use yoyopod_ui_host::render::framebuffer::{render_hub_fallback, render_test_scene};

#[test]
fn test_scene_changes_with_counter() {
    let mut first = Framebuffer::new(240, 280);
    let mut second = Framebuffer::new(240, 280);

    render_test_scene(&mut first, 1);
    render_test_scene(&mut second, 2);

    assert_ne!(first.as_be_bytes(), second.as_be_bytes());
    assert_eq!(first.pixel(0, 0), rgb565(8, 10, 14));
}

#[test]
fn hub_fallback_uses_snapshot_accent() {
    let mut first = Framebuffer::new(240, 280);
    let mut second = Framebuffer::new(240, 280);
    let mut first_snapshot = HubSnapshot::static_default();
    let mut second_snapshot = HubSnapshot::static_default();
    first_snapshot.accent = 0x00FF88;
    second_snapshot.accent = 0x00D4FF;

    render_hub_fallback(&mut first, &first_snapshot);
    render_hub_fallback(&mut second, &second_snapshot);

    assert_ne!(first.as_be_bytes(), second.as_be_bytes());
    assert_eq!(first.pixel(72, 58), rgb565(0, 255, 136));
    assert_eq!(second.pixel(72, 58), rgb565(0, 212, 255));
}
