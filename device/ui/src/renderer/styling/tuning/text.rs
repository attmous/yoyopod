use std::ptr::NonNull;

use crate::renderer::lvgl::ffi;
use crate::scene::roles;

pub(crate) fn apply(obj: NonNull<ffi::lv_obj_t>, role: &'static str) -> bool {
    const SELECTOR: ffi::LvStyleSelector = 0;
    unsafe {
        match role {
            roles::FOOTER_LABEL => {
                ffi::lv_label_set_long_mode(obj.as_ptr(), ffi::LV_LABEL_LONG_MODE_CLIP);
                ffi::lv_obj_set_style_text_font(
                    obj.as_ptr(),
                    &ffi::lv_font_montserrat_12,
                    SELECTOR,
                );
                ffi::lv_obj_set_style_text_align(obj.as_ptr(), ffi::LV_TEXT_ALIGN_CENTER, SELECTOR);
            }
            roles::STATUS_TIME | roles::STATUS_BATTERY_LABEL => {
                ffi::lv_label_set_long_mode(obj.as_ptr(), ffi::LV_LABEL_LONG_MODE_CLIP);
                ffi::lv_obj_set_style_text_font(
                    obj.as_ptr(),
                    &ffi::lv_font_montserrat_12,
                    SELECTOR,
                );
                ffi::lv_obj_set_style_text_align(obj.as_ptr(), ffi::LV_TEXT_ALIGN_CENTER, SELECTOR);
            }
            roles::STATUS_NETWORK_ICON
            | roles::STATUS_GPS_ICON
            | roles::STATUS_VOIP_ICON
            | roles::STATUS_CHARGE_ICON
            | roles::STATUS_BATTERY_ICON => {
                ffi::lv_obj_set_style_text_font(
                    obj.as_ptr(),
                    &ffi::lv_font_montserrat_12,
                    SELECTOR,
                );
                ffi::lv_image_set_inner_align(obj.as_ptr(), ffi::LV_IMAGE_ALIGN_CENTER);
            }
            _ => return false,
        }
    }
    true
}
