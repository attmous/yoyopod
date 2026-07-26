use std::ptr::NonNull;

use crate::renderer::lvgl::ffi;
use crate::scene::roles;

pub(crate) fn apply(obj: NonNull<ffi::lv_obj_t>, role: &'static str) -> bool {
    const SELECTOR: ffi::LvStyleSelector = 0;
    unsafe {
        match role {
            roles::CALL_NAME => {
                ffi::lv_label_set_long_mode(obj.as_ptr(), ffi::LV_LABEL_LONG_MODE_DOTS);
                ffi::lv_obj_set_style_text_font(
                    obj.as_ptr(),
                    &ffi::lv_font_montserrat_24,
                    SELECTOR,
                );
                ffi::lv_obj_set_style_text_align(obj.as_ptr(), ffi::LV_TEXT_ALIGN_CENTER, SELECTOR);
            }
            roles::CALL_NAME_SM => {
                ffi::lv_label_set_long_mode(obj.as_ptr(), ffi::LV_LABEL_LONG_MODE_DOTS);
                ffi::lv_obj_set_style_text_font(
                    obj.as_ptr(),
                    &ffi::lv_font_montserrat_18,
                    SELECTOR,
                );
                ffi::lv_obj_set_style_text_align(obj.as_ptr(), ffi::LV_TEXT_ALIGN_CENTER, SELECTOR);
            }
            roles::CALL_STATE => {
                ffi::lv_obj_set_style_text_font(
                    obj.as_ptr(),
                    &ffi::lv_font_montserrat_12,
                    SELECTOR,
                );
                ffi::lv_obj_set_style_text_align(obj.as_ptr(), ffi::LV_TEXT_ALIGN_CENTER, SELECTOR);
            }
            roles::CALL_AVATAR_INITIAL | roles::CALL_AVATAR_INITIAL_SM | roles::CALL_DURATION => {
                ffi::lv_obj_set_style_text_font(
                    obj.as_ptr(),
                    &ffi::lv_font_montserrat_24,
                    SELECTOR,
                );
                ffi::lv_obj_set_style_text_align(obj.as_ptr(), ffi::LV_TEXT_ALIGN_CENTER, SELECTOR);
            }
            _ => return false,
        }
    }
    true
}
