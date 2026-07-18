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
            roles::WHEEL_ICON => {
                ffi::lv_image_set_inner_align(obj.as_ptr(), ffi::LV_IMAGE_ALIGN_CENTER);
            }
            roles::HERO_ART_ICON | roles::HERO_PREV | roles::HERO_PLAY_ICON | roles::HERO_NEXT => {
                ffi::lv_image_set_inner_align(obj.as_ptr(), ffi::LV_IMAGE_ALIGN_CENTER);
            }
            roles::HERO_CONTEXT | roles::HERO_TIME_L | roles::HERO_TIME_R => {
                ffi::lv_label_set_long_mode(obj.as_ptr(), ffi::LV_LABEL_LONG_MODE_CLIP);
                ffi::lv_obj_set_style_text_font(
                    obj.as_ptr(),
                    &ffi::lv_font_montserrat_12,
                    SELECTOR,
                );
                let align = if role == roles::HERO_TIME_L {
                    ffi::LV_TEXT_ALIGN_RIGHT
                } else {
                    ffi::LV_TEXT_ALIGN_LEFT
                };
                ffi::lv_obj_set_style_text_align(obj.as_ptr(), align, SELECTOR);
            }
            roles::HERO_TITLE => {
                ffi::lv_label_set_long_mode(obj.as_ptr(), ffi::LV_LABEL_LONG_MODE_DOTS);
                ffi::lv_obj_set_style_text_font(
                    obj.as_ptr(),
                    &ffi::lv_font_montserrat_18,
                    SELECTOR,
                );
                ffi::lv_obj_set_style_text_align(obj.as_ptr(), ffi::LV_TEXT_ALIGN_CENTER, SELECTOR);
            }
            roles::MEDIA_WHEEL_HEADER_TITLE | roles::MEDIA_WHEEL_HEADER_COUNTER => {
                ffi::lv_label_set_long_mode(obj.as_ptr(), ffi::LV_LABEL_LONG_MODE_DOTS);
                ffi::lv_obj_set_style_text_font(
                    obj.as_ptr(),
                    &ffi::lv_font_montserrat_12,
                    SELECTOR,
                );
                ffi::lv_obj_set_style_text_align(
                    obj.as_ptr(),
                    if role == roles::MEDIA_WHEEL_HEADER_COUNTER {
                        ffi::LV_TEXT_ALIGN_RIGHT
                    } else {
                        ffi::LV_TEXT_ALIGN_LEFT
                    },
                    SELECTOR,
                );
            }
            roles::MEDIA_WHEEL_FOCUS_SUB => {
                ffi::lv_label_set_long_mode(obj.as_ptr(), ffi::LV_LABEL_LONG_MODE_DOTS);
                ffi::lv_obj_set_style_text_font(
                    obj.as_ptr(),
                    &ffi::lv_font_montserrat_12,
                    SELECTOR,
                );
                ffi::lv_obj_set_style_text_align(obj.as_ptr(), ffi::LV_TEXT_ALIGN_LEFT, SELECTOR);
            }
            roles::WHEEL_LABEL => {
                ffi::lv_label_set_long_mode(obj.as_ptr(), ffi::LV_LABEL_LONG_MODE_DOTS);
                ffi::lv_obj_set_style_text_font(
                    obj.as_ptr(),
                    &ffi::lv_font_montserrat_18,
                    SELECTOR,
                );
                ffi::lv_obj_set_style_text_align(obj.as_ptr(), ffi::LV_TEXT_ALIGN_CENTER, SELECTOR);
            }
            roles::MEDIA_WHEEL_PEEK_TITLE | roles::MEDIA_WHEEL_FOCUS_TITLE => {
                ffi::lv_label_set_long_mode(obj.as_ptr(), ffi::LV_LABEL_LONG_MODE_DOTS);
                ffi::lv_obj_set_style_text_font(
                    obj.as_ptr(),
                    if role == roles::MEDIA_WHEEL_PEEK_TITLE {
                        &ffi::lv_font_montserrat_12
                    } else {
                        &ffi::lv_font_montserrat_18
                    },
                    SELECTOR,
                );
                ffi::lv_obj_set_style_text_align(obj.as_ptr(), ffi::LV_TEXT_ALIGN_LEFT, SELECTOR);
            }
            roles::MEDIA_WHEEL_PEEK_INITIAL => {
                ffi::lv_label_set_long_mode(obj.as_ptr(), ffi::LV_LABEL_LONG_MODE_CLIP);
                ffi::lv_obj_set_style_text_font(
                    obj.as_ptr(),
                    &ffi::lv_font_montserrat_18,
                    SELECTOR,
                );
                ffi::lv_obj_set_style_text_align(obj.as_ptr(), ffi::LV_TEXT_ALIGN_CENTER, SELECTOR);
            }
            roles::MEDIA_WHEEL_FOCUS_INITIAL => {
                ffi::lv_label_set_long_mode(obj.as_ptr(), ffi::LV_LABEL_LONG_MODE_CLIP);
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
