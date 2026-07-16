use std::ptr::NonNull;

use crate::renderer::lvgl::ffi;
use crate::renderer::styling::style as theme;
use crate::scene::roles;

pub(crate) fn apply(obj: NonNull<ffi::lv_obj_t>, role: &'static str) -> bool {
    const SELECTOR: ffi::LvStyleSelector = 0;
    unsafe {
        match role {
            roles::FOOTER_BAR
            | roles::DECK_BAR
            | roles::DECK_SLOT
            | roles::DECK_PILL
            | roles::COMPANION
            | roles::COMPANION_BODY
            | roles::COMPANION_EYE
            | roles::CALL_PANEL
            | roles::STATUS_BAR
            | roles::STATUS_BATTERY_OUTLINE => {
                ffi::lv_obj_set_scrollbar_mode(obj.as_ptr(), ffi::LV_SCROLLBAR_MODE_OFF);
            }
            roles::LIST_ROW => {
                ffi::lv_obj_set_style_pad_left(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_right(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_top(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_bottom(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_scrollbar_mode(obj.as_ptr(), ffi::LV_SCROLLBAR_MODE_OFF);
            }
            roles::STATUS_GPS_RING => {
                ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), theme::OPA_TRANSP, SELECTOR);
                ffi::lv_obj_set_style_radius(obj.as_ptr(), ffi::LV_RADIUS_CIRCLE, SELECTOR);
            }
            roles::STATUS_GPS_CENTER => {
                ffi::lv_obj_set_style_radius(obj.as_ptr(), ffi::LV_RADIUS_CIRCLE, SELECTOR);
            }
            roles::STATUS_GPS_TAIL => {
                ffi::lv_obj_set_style_radius(obj.as_ptr(), 1, SELECTOR);
            }
            roles::STATUS_VOIP_DOT_AFTER_GPS => {
                ffi::lv_obj_set_style_radius(obj.as_ptr(), ffi::LV_RADIUS_CIRCLE, SELECTOR);
            }
            _ => return false,
        }
    }
    true
}
