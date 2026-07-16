use std::ffi::c_char;
use std::ffi::c_void;

#[repr(C)]
pub struct lv_display_t {
    _private: [u8; 0],
}

#[repr(C)]
pub struct lv_obj_t {
    _private: [u8; 0],
}

#[repr(C)]
pub struct lv_font_t {
    _private: [u8; 0],
}

#[repr(C)]
pub struct lv_area_t {
    pub x1: i32,
    pub y1: i32,
    pub x2: i32,
    pub y2: i32,
}

#[repr(C)]
#[derive(Clone, Copy)]
pub struct lv_color_t {
    pub blue: u8,
    pub green: u8,
    pub red: u8,
}

/// Leading fields of LVGL 9.x `lv_image_header_t`. Upstream declares three
/// words of C bitfields; on the little-endian GCC/Clang targets we build for,
/// bitfields pack LSB-first, which the accessors below rely on.
#[repr(C)]
#[derive(Clone, Copy)]
pub struct lv_image_header_t {
    /// magic:8 | cf:8 | flags:16
    pub word0: u32,
    /// w:16 | h:16
    pub word1: u32,
    /// stride:16 | reserved:16
    pub word2: u32,
}

impl lv_image_header_t {
    pub fn color_format(&self) -> u32 {
        (self.word0 >> 8) & 0xFF
    }

    pub fn width(&self) -> usize {
        (self.word1 & 0xFFFF) as usize
    }

    pub fn height(&self) -> usize {
        ((self.word1 >> 16) & 0xFFFF) as usize
    }

    pub fn stride(&self) -> usize {
        (self.word2 & 0xFFFF) as usize
    }
}

/// Leading fields of LVGL 9.x `lv_draw_buf_t`. Later LVGL revisions may append
/// fields; snapshots are only read through this prefix, never constructed or
/// sized on the Rust side.
#[repr(C)]
pub struct lv_draw_buf_t {
    pub header: lv_image_header_t,
    pub data_size: u32,
    pub data: *mut u8,
    pub unaligned_data: *mut c_void,
}

pub type LvDisplayFlushCb = unsafe extern "C" fn(*mut lv_display_t, *const lv_area_t, *mut u8);
pub type LvStyleSelector = u32;

/// `lv_color_format_t` value for native RGB565 (LVGL 9.x).
pub const LV_COLOR_FORMAT_RGB565: u32 = 0x12;
pub const LV_DISPLAY_RENDER_MODE_PARTIAL: i32 = 0;
pub const LV_LABEL_LONG_MODE_DOTS: i32 = 1;
pub const LV_LABEL_LONG_MODE_CLIP: i32 = 4;
pub const LV_SCROLLBAR_MODE_OFF: i32 = 0;
pub const LV_TEXT_ALIGN_CENTER: i32 = 2;
pub const LV_RADIUS_CIRCLE: i32 = 0x7FFF;

unsafe extern "C" {
    pub static lv_font_montserrat_12: lv_font_t;
    pub static lv_font_montserrat_18: lv_font_t;

    pub fn lv_init();
    pub fn lv_deinit();
    pub fn lv_tick_inc(tick_period: u32);
    pub fn lv_timer_handler() -> u32;

    pub fn lv_display_create(hor_res: i32, ver_res: i32) -> *mut lv_display_t;
    pub fn lv_display_delete(display: *mut lv_display_t);
    pub fn lv_display_set_default(display: *mut lv_display_t);
    pub fn lv_display_set_flush_cb(display: *mut lv_display_t, flush_cb: Option<LvDisplayFlushCb>);
    pub fn lv_display_set_buffers(
        display: *mut lv_display_t,
        buf1: *mut c_void,
        buf2: *mut c_void,
        buf_size: u32,
        render_mode: i32,
    );
    pub fn lv_display_set_user_data(display: *mut lv_display_t, user_data: *mut c_void);
    pub fn lv_display_get_user_data(display: *mut lv_display_t) -> *mut c_void;
    pub fn lv_display_flush_ready(display: *mut lv_display_t);
    pub fn lv_display_get_screen_active(display: *mut lv_display_t) -> *mut lv_obj_t;

    pub fn lv_color_hex(color: u32) -> lv_color_t;

    pub fn lv_obj_create(parent: *mut lv_obj_t) -> *mut lv_obj_t;
    pub fn lv_obj_delete(obj: *mut lv_obj_t);
    pub fn lv_obj_move_to_index(obj: *mut lv_obj_t, index: i32);
    pub fn lv_obj_set_pos(obj: *mut lv_obj_t, x: i32, y: i32);
    pub fn lv_obj_set_size(obj: *mut lv_obj_t, width: i32, height: i32);
    pub fn lv_obj_invalidate(obj: *mut lv_obj_t);
    pub fn lv_obj_remove_style_all(obj: *mut lv_obj_t);
    pub fn lv_obj_set_style_bg_color(
        obj: *mut lv_obj_t,
        value: lv_color_t,
        selector: LvStyleSelector,
    );
    pub fn lv_obj_set_style_bg_opa(obj: *mut lv_obj_t, value: u8, selector: LvStyleSelector);
    pub fn lv_obj_set_style_opa(obj: *mut lv_obj_t, value: u8, selector: LvStyleSelector);
    pub fn lv_obj_set_style_text_color(
        obj: *mut lv_obj_t,
        value: lv_color_t,
        selector: LvStyleSelector,
    );
    pub fn lv_obj_set_style_image_recolor(
        obj: *mut lv_obj_t,
        value: lv_color_t,
        selector: LvStyleSelector,
    );
    pub fn lv_obj_set_style_image_recolor_opa(
        obj: *mut lv_obj_t,
        value: u8,
        selector: LvStyleSelector,
    );
    pub fn lv_obj_set_style_border_color(
        obj: *mut lv_obj_t,
        value: lv_color_t,
        selector: LvStyleSelector,
    );
    pub fn lv_obj_set_style_border_width(obj: *mut lv_obj_t, value: i32, selector: LvStyleSelector);
    pub fn lv_obj_set_style_radius(obj: *mut lv_obj_t, value: i32, selector: LvStyleSelector);
    pub fn lv_obj_set_style_outline_width(
        obj: *mut lv_obj_t,
        value: i32,
        selector: LvStyleSelector,
    );
    pub fn lv_obj_set_style_shadow_width(obj: *mut lv_obj_t, value: i32, selector: LvStyleSelector);
    pub fn lv_obj_set_style_shadow_color(
        obj: *mut lv_obj_t,
        value: lv_color_t,
        selector: LvStyleSelector,
    );
    pub fn lv_obj_set_style_text_font(
        obj: *mut lv_obj_t,
        value: *const lv_font_t,
        selector: LvStyleSelector,
    );
    pub fn lv_obj_set_style_text_align(obj: *mut lv_obj_t, value: i32, selector: LvStyleSelector);
    pub fn lv_obj_set_style_pad_top(obj: *mut lv_obj_t, value: i32, selector: LvStyleSelector);
    pub fn lv_obj_set_style_pad_bottom(obj: *mut lv_obj_t, value: i32, selector: LvStyleSelector);
    pub fn lv_obj_set_style_pad_left(obj: *mut lv_obj_t, value: i32, selector: LvStyleSelector);
    pub fn lv_obj_set_style_pad_right(obj: *mut lv_obj_t, value: i32, selector: LvStyleSelector);
    pub fn lv_obj_set_scrollbar_mode(obj: *mut lv_obj_t, mode: i32);
    pub fn lv_obj_center(obj: *mut lv_obj_t);

    pub fn lv_label_create(parent: *mut lv_obj_t) -> *mut lv_obj_t;
    pub fn lv_label_set_text(obj: *mut lv_obj_t, text: *const c_char);
    pub fn lv_label_set_long_mode(obj: *mut lv_obj_t, long_mode: i32);

    pub fn lv_image_create(parent: *mut lv_obj_t) -> *mut lv_obj_t;
    pub fn lv_image_set_src(obj: *mut lv_obj_t, src: *const c_void);

    pub fn lv_screen_load(screen: *mut lv_obj_t);

    pub fn lv_snapshot_take(obj: *mut lv_obj_t, cf: u32) -> *mut lv_draw_buf_t;
    pub fn lv_draw_buf_destroy(draw_buf: *mut lv_draw_buf_t);
}
