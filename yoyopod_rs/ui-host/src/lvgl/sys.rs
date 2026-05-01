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

pub type LvDisplayFlushCb = unsafe extern "C" fn(*mut lv_display_t, *const lv_area_t, *mut u8);
pub type LvStyleSelector = u32;
pub type YoyopodLvglFlushCb = unsafe extern "C" fn(i32, i32, i32, i32, *const u8, u32, *mut c_void);

pub const LV_DISPLAY_RENDER_MODE_PARTIAL: i32 = 0;
pub const LV_ALIGN_CENTER: i32 = 9;
pub const LV_ALIGN_BOTTOM_MID: i32 = 5;
pub const LV_LABEL_LONG_MODE_WRAP: i32 = 0;
pub const LV_LABEL_LONG_MODE_DOTS: i32 = 1;
pub const LV_LABEL_LONG_MODE_CLIP: i32 = 4;
pub const LV_SCROLLBAR_MODE_OFF: i32 = 0;
pub const LV_TEXT_ALIGN_LEFT: i32 = 1;
pub const LV_TEXT_ALIGN_CENTER: i32 = 2;
pub const LV_RADIUS_CIRCLE: i32 = 0x7FFF;

unsafe extern "C" {
    pub static lv_font_montserrat_12: lv_font_t;
    pub static lv_font_montserrat_14: lv_font_t;
    pub static lv_font_montserrat_16: lv_font_t;
    pub static lv_font_montserrat_18: lv_font_t;
    pub static lv_font_montserrat_24: lv_font_t;

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
    pub fn lv_obj_set_pos(obj: *mut lv_obj_t, x: i32, y: i32);
    pub fn lv_obj_set_size(obj: *mut lv_obj_t, width: i32, height: i32);
    pub fn lv_obj_set_width(obj: *mut lv_obj_t, width: i32);
    pub fn lv_obj_set_height(obj: *mut lv_obj_t, height: i32);
    pub fn lv_obj_invalidate(obj: *mut lv_obj_t);
    pub fn lv_obj_remove_style_all(obj: *mut lv_obj_t);
    pub fn lv_obj_set_style_bg_color(
        obj: *mut lv_obj_t,
        value: lv_color_t,
        selector: LvStyleSelector,
    );
    pub fn lv_obj_set_style_bg_opa(obj: *mut lv_obj_t, value: u8, selector: LvStyleSelector);
    pub fn lv_obj_set_style_text_color(
        obj: *mut lv_obj_t,
        value: lv_color_t,
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
    pub fn lv_obj_set_style_shadow_opa(obj: *mut lv_obj_t, value: u8, selector: LvStyleSelector);
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
    pub fn lv_obj_set_style_image_opa(obj: *mut lv_obj_t, value: u8, selector: LvStyleSelector);
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
    pub fn lv_obj_align(obj: *mut lv_obj_t, align: i32, x_ofs: i32, y_ofs: i32);
    pub fn lv_obj_center(obj: *mut lv_obj_t);

    pub fn lv_label_create(parent: *mut lv_obj_t) -> *mut lv_obj_t;
    pub fn lv_label_set_text(obj: *mut lv_obj_t, text: *const c_char);
    pub fn lv_label_set_long_mode(obj: *mut lv_obj_t, long_mode: i32);

    pub fn lv_image_create(parent: *mut lv_obj_t) -> *mut lv_obj_t;
    pub fn lv_image_set_src(obj: *mut lv_obj_t, src: *const c_void);

    pub fn lv_screen_load(screen: *mut lv_obj_t);

    pub fn yoyopod_lvgl_init() -> i32;
    pub fn yoyopod_lvgl_shutdown();
    pub fn yoyopod_lvgl_register_display(
        width: i32,
        height: i32,
        buffer_pixel_count: u32,
        flush_cb: Option<YoyopodLvglFlushCb>,
        user_data: *mut c_void,
    ) -> i32;
    pub fn yoyopod_lvgl_register_input() -> i32;
    pub fn yoyopod_lvgl_tick_inc(milliseconds: u32);
    pub fn yoyopod_lvgl_timer_handler() -> u32;
    pub fn yoyopod_lvgl_queue_key_event(key: i32, pressed: i32) -> i32;
    pub fn yoyopod_lvgl_show_probe_scene(scene_id: i32) -> i32;
    pub fn yoyopod_lvgl_set_status_bar_state(
        network_enabled: i32,
        network_connected: i32,
        wifi_connected: i32,
        signal_strength: i32,
        gps_has_fix: i32,
    ) -> i32;
    pub fn yoyopod_lvgl_hub_build() -> i32;
    pub fn yoyopod_lvgl_hub_sync(
        icon_key: *const c_char,
        title: *const c_char,
        subtitle: *const c_char,
        footer: *const c_char,
        time_text: *const c_char,
        accent_rgb: u32,
        selected_index: i32,
        total_cards: i32,
        voip_state: i32,
        battery_percent: i32,
        charging: i32,
        power_available: i32,
    ) -> i32;
    pub fn yoyopod_lvgl_hub_destroy();
    pub fn yoyopod_lvgl_talk_build() -> i32;
    pub fn yoyopod_lvgl_talk_sync(
        title_text: *const c_char,
        icon_key: *const c_char,
        outlined: i32,
        footer: *const c_char,
        selected_index: i32,
        total_cards: i32,
        voip_state: i32,
        battery_percent: i32,
        charging: i32,
        power_available: i32,
        accent_rgb: u32,
    ) -> i32;
    pub fn yoyopod_lvgl_talk_destroy();
    pub fn yoyopod_lvgl_talk_actions_build() -> i32;
    pub fn yoyopod_lvgl_talk_actions_sync(
        contact_name: *const c_char,
        title_text: *const c_char,
        status_text: *const c_char,
        status_kind: i32,
        footer: *const c_char,
        icon_0: *const c_char,
        color_kind_0: i32,
        icon_1: *const c_char,
        color_kind_1: i32,
        icon_2: *const c_char,
        color_kind_2: i32,
        action_count: i32,
        selected_index: i32,
        layout_kind: i32,
        button_size_kind: i32,
        voip_state: i32,
        battery_percent: i32,
        charging: i32,
        power_available: i32,
        accent_rgb: u32,
    ) -> i32;
    pub fn yoyopod_lvgl_talk_actions_destroy();
    pub fn yoyopod_lvgl_listen_build() -> i32;
    pub fn yoyopod_lvgl_listen_sync(
        page_text: *const c_char,
        footer: *const c_char,
        item_0: *const c_char,
        item_1: *const c_char,
        item_2: *const c_char,
        item_3: *const c_char,
        subtitle_0: *const c_char,
        subtitle_1: *const c_char,
        subtitle_2: *const c_char,
        subtitle_3: *const c_char,
        icon_0: *const c_char,
        icon_1: *const c_char,
        icon_2: *const c_char,
        icon_3: *const c_char,
        item_count: i32,
        selected_index: i32,
        voip_state: i32,
        battery_percent: i32,
        charging: i32,
        power_available: i32,
        accent_rgb: u32,
        empty_title: *const c_char,
        empty_subtitle: *const c_char,
    ) -> i32;
    pub fn yoyopod_lvgl_listen_destroy();
    pub fn yoyopod_lvgl_playlist_build() -> i32;
    pub fn yoyopod_lvgl_playlist_sync(
        title_text: *const c_char,
        page_text: *const c_char,
        status_chip_text: *const c_char,
        status_chip_kind: i32,
        footer: *const c_char,
        item_0: *const c_char,
        item_1: *const c_char,
        item_2: *const c_char,
        item_3: *const c_char,
        subtitle_0: *const c_char,
        subtitle_1: *const c_char,
        subtitle_2: *const c_char,
        subtitle_3: *const c_char,
        badge_0: *const c_char,
        badge_1: *const c_char,
        badge_2: *const c_char,
        badge_3: *const c_char,
        icon_0: *const c_char,
        icon_1: *const c_char,
        icon_2: *const c_char,
        icon_3: *const c_char,
        item_count: i32,
        selected_visible_index: i32,
        voip_state: i32,
        battery_percent: i32,
        charging: i32,
        power_available: i32,
        accent_rgb: u32,
        empty_title: *const c_char,
        empty_subtitle: *const c_char,
        empty_icon_key: *const c_char,
    ) -> i32;
    pub fn yoyopod_lvgl_playlist_destroy();
    pub fn yoyopod_lvgl_now_playing_build() -> i32;
    pub fn yoyopod_lvgl_now_playing_sync(
        title_text: *const c_char,
        artist_text: *const c_char,
        state_text: *const c_char,
        footer: *const c_char,
        progress_permille: i32,
        voip_state: i32,
        battery_percent: i32,
        charging: i32,
        power_available: i32,
        accent_rgb: u32,
    ) -> i32;
    pub fn yoyopod_lvgl_now_playing_destroy();
    pub fn yoyopod_lvgl_incoming_call_build() -> i32;
    pub fn yoyopod_lvgl_incoming_call_sync(
        caller_name: *const c_char,
        caller_address: *const c_char,
        footer: *const c_char,
        voip_state: i32,
        battery_percent: i32,
        charging: i32,
        power_available: i32,
        accent_rgb: u32,
    ) -> i32;
    pub fn yoyopod_lvgl_incoming_call_destroy();
    pub fn yoyopod_lvgl_outgoing_call_build() -> i32;
    pub fn yoyopod_lvgl_outgoing_call_sync(
        callee_name: *const c_char,
        callee_address: *const c_char,
        footer: *const c_char,
        voip_state: i32,
        battery_percent: i32,
        charging: i32,
        power_available: i32,
        accent_rgb: u32,
    ) -> i32;
    pub fn yoyopod_lvgl_outgoing_call_destroy();
    pub fn yoyopod_lvgl_in_call_build() -> i32;
    pub fn yoyopod_lvgl_in_call_sync(
        caller_name: *const c_char,
        duration_text: *const c_char,
        mute_text: *const c_char,
        footer: *const c_char,
        muted: i32,
        voip_state: i32,
        battery_percent: i32,
        charging: i32,
        power_available: i32,
        accent_rgb: u32,
    ) -> i32;
    pub fn yoyopod_lvgl_in_call_destroy();
    pub fn yoyopod_lvgl_ask_build() -> i32;
    pub fn yoyopod_lvgl_ask_sync(
        icon_key: *const c_char,
        title_text: *const c_char,
        subtitle_text: *const c_char,
        footer: *const c_char,
        voip_state: i32,
        battery_percent: i32,
        charging: i32,
        power_available: i32,
        accent_rgb: u32,
    ) -> i32;
    pub fn yoyopod_lvgl_ask_destroy();
    pub fn yoyopod_lvgl_power_build() -> i32;
    pub fn yoyopod_lvgl_power_sync(
        title_text: *const c_char,
        page_text: *const c_char,
        icon_key: *const c_char,
        footer: *const c_char,
        item_0: *const c_char,
        item_1: *const c_char,
        item_2: *const c_char,
        item_3: *const c_char,
        item_4: *const c_char,
        item_count: i32,
        current_page_index: i32,
        total_pages: i32,
        voip_state: i32,
        battery_percent: i32,
        charging: i32,
        power_available: i32,
        accent_rgb: u32,
    ) -> i32;
    pub fn yoyopod_lvgl_power_destroy();
    pub fn yoyopod_lvgl_clear_screen();
    pub fn yoyopod_lvgl_force_refresh();
    pub fn yoyopod_lvgl_snapshot(output_buf: *mut u8, buf_size: u32) -> i32;
    pub fn yoyopod_lvgl_last_error() -> *const c_char;
    pub fn yoyopod_lvgl_version() -> *const c_char;
}
