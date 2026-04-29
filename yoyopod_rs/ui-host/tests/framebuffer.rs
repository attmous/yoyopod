use yoyopod_ui_host::framebuffer::{rgb565, Framebuffer};

#[test]
fn packs_rgb888_to_rgb565_big_endian_bytes() {
    assert_eq!(rgb565(255, 0, 0), 0xF800);
    assert_eq!(rgb565(0, 255, 0), 0x07E0);
    assert_eq!(rgb565(0, 0, 255), 0x001F);
}

#[test]
fn fills_rectangle_inside_bounds() {
    let mut fb = Framebuffer::new(4, 3);
    fb.clear(rgb565(0, 0, 0));
    fb.fill_rect(1, 1, 2, 1, rgb565(255, 0, 0));

    assert_eq!(fb.pixel(0, 1), rgb565(0, 0, 0));
    assert_eq!(fb.pixel(1, 1), rgb565(255, 0, 0));
    assert_eq!(fb.pixel(2, 1), rgb565(255, 0, 0));
    assert_eq!(fb.pixel(3, 1), rgb565(0, 0, 0));
}

#[test]
fn pastes_big_endian_rgb565_region_inside_bounds() {
    let mut fb = Framebuffer::new(4, 3);
    fb.clear(rgb565(0, 0, 0));

    fb.paste_be_bytes_region(1, 1, 2, 1, &[0xF8, 0x00, 0x07, 0xE0]);

    assert_eq!(fb.pixel(0, 1), rgb565(0, 0, 0));
    assert_eq!(fb.pixel(1, 1), rgb565(255, 0, 0));
    assert_eq!(fb.pixel(2, 1), rgb565(0, 255, 0));
    assert_eq!(fb.pixel(3, 1), rgb565(0, 0, 0));
}
