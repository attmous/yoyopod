use std::ptr::NonNull;

use crate::renderer::lvgl::ffi;
use crate::renderer::styling::style as theme;
use crate::scene::roles;

use super::mix_u24;

pub(crate) fn apply_accent_raw(obj: NonNull<ffi::lv_obj_t>, role: &'static str, rgb: u32) {
    const SELECTOR: ffi::LvStyleSelector = 0;
    let accent = unsafe { ffi::lv_color_hex(rgb & 0xFFFFFF) };
    unsafe {
        match role {
            roles::SCENE_BACKDROP => {
                ffi::lv_obj_set_style_bg_color(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::DECK_PILL => {
                ffi::lv_obj_set_style_bg_color(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::DECK_GLYPH => {
                ffi::lv_obj_set_style_image_recolor(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_image_recolor_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::FX_HALO | roles::FX_PULSE | roles::FX_GLOW | roles::FX_SPINNER => {
                ffi::lv_obj_set_style_bg_color(
                    obj.as_ptr(),
                    ffi::lv_color_hex(mix_u24(rgb, theme::BACKGROUND_RGB, 70)),
                    SELECTOR,
                );
            }
            roles::CALL_PANEL => {
                ffi::lv_obj_set_style_bg_color(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
                ffi::lv_obj_set_style_shadow_color(obj.as_ptr(), accent, SELECTOR);
            }
            roles::LIST_ROW_ICON
            | roles::CALL_STATE_LABEL
            | roles::STATUS_WIFI
            | roles::STATUS_TIME
            | roles::STATUS_BATTERY_LABEL => {
                ffi::lv_obj_set_style_text_color(obj.as_ptr(), accent, SELECTOR);
            }
            roles::STATUS_SIGNAL_BAR_0
            | roles::STATUS_SIGNAL_BAR_1
            | roles::STATUS_SIGNAL_BAR_2
            | roles::STATUS_SIGNAL_BAR_3
            | roles::STATUS_GPS_CENTER
            | roles::STATUS_GPS_TAIL
            | roles::STATUS_VOIP_DOT_AFTER_GPS
            | roles::STATUS_BATTERY_FILL
            | roles::STATUS_BATTERY_TIP
            | roles::FX_PARTICLE => {
                ffi::lv_obj_set_style_bg_color(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::STATUS_GPS_RING | roles::STATUS_BATTERY_OUTLINE => {
                ffi::lv_obj_set_style_border_color(obj.as_ptr(), accent, SELECTOR);
            }
            roles::FOOTER_LABEL => {
                ffi::lv_obj_set_style_text_color(
                    obj.as_ptr(),
                    ffi::lv_color_hex(mix_u24(rgb, theme::BACKGROUND_RGB, 65)),
                    SELECTOR,
                );
            }
            _ => {}
        }
    }
}
