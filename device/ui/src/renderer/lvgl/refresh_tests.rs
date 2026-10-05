use std::time::{Duration, Instant};

use super::*;
use crate::renderer::widgets::LvglFacade;

// This is the only test that initializes LVGL. Keep native cases in this one
// test, on its owning thread: LVGL has process-global initialization/teardown.
#[test]
fn completed_native_frames_have_current_shadow_pixels_within_refresh_period() {
    let mut facade = NativeLvglFacade::open(None).unwrap();
    let mut framebuffer = Framebuffer::new(240, 280);
    facade.ensure_display_registered(&framebuffer).unwrap();
    let root = facade.create_root().unwrap();
    let panel = facade.create_container(root, "button").unwrap();
    let object = facade.widget_obj(panel).unwrap();

    unsafe {
        ffi::lv_obj_set_style_bg_opa(object.as_ptr(), 255, 0);
        ffi::lv_obj_set_style_bg_color(object.as_ptr(), ffi::lv_color_hex(0xff0000), 0);
        // Make the initial periodic refresh due without a wall-clock sleep.
        ffi::lv_tick_inc(33);
    }
    render_with_one_ms_tick(&mut facade, &mut framebuffer);
    assert_eq!(framebuffer.pixels()[160 * 240 + 120], 0xf800);

    for (color, expected) in [(0x00ff00, 0x07e0), (0x0000ff, 0x001f), (0xff0000, 0xf800)] {
        unsafe {
            ffi::lv_obj_set_style_bg_color(object.as_ptr(), ffi::lv_color_hex(color), 0);
        }
        render_with_one_ms_tick(&mut facade, &mut framebuffer);
        assert_eq!(
            framebuffer.pixels()[160 * 240 + 120],
            expected,
            "completed frame must contain the changed color before the periodic refresh is due"
        );
    }
    assert!(facade.flush_target.framebuffer.is_null());
    framebuffer.clear(0xaaaa);
    unsafe {
        // A later LVGL callback must no longer borrow the returned framebuffer.
        ffi::lv_obj_invalidate(object.as_ptr());
        ffi::lv_tick_inc(33);
        let _ = ffi::lv_timer_handler();
    }
    assert!(framebuffer.pixels().iter().all(|pixel| *pixel == 0xaaaa));
}

fn render_with_one_ms_tick(facade: &mut NativeLvglFacade, framebuffer: &mut Framebuffer) {
    // tick_lvgl uses max(elapsed, 1). A future origin gives a deterministic
    // one-ms tick even on a preempted/slow test host, without changing LVGL's
    // refresh period or calling a separate redraw/snapshot API.
    facade.last_tick = Instant::now() + Duration::from_secs(3_600);
    facade.render_frame(framebuffer).unwrap();
}
