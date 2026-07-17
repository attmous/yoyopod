use std::ptr::NonNull;

use crate::renderer::lvgl::ffi;
use crate::renderer::styling::style::WidgetStyle;

pub(crate) fn reset_style_raw(obj: NonNull<ffi::lv_obj_t>) {
    const SELECTOR: ffi::LvStyleSelector = 0;
    unsafe {
        ffi::lv_obj_remove_style_all(obj.as_ptr());
        // Generic LVGL objects receive the default theme's padded card style.
        // YoYoPod layouts are explicit, so establish a zero-padding base and
        // let role tuning opt into spacing deliberately.
        ffi::lv_obj_set_style_pad_left(obj.as_ptr(), 0, SELECTOR);
        ffi::lv_obj_set_style_pad_right(obj.as_ptr(), 0, SELECTOR);
        ffi::lv_obj_set_style_pad_top(obj.as_ptr(), 0, SELECTOR);
        ffi::lv_obj_set_style_pad_bottom(obj.as_ptr(), 0, SELECTOR);
        ffi::lv_obj_set_style_pad_row(obj.as_ptr(), 0, SELECTOR);
        ffi::lv_obj_set_style_pad_column(obj.as_ptr(), 0, SELECTOR);
    }
}

pub(crate) fn apply_style_raw(obj: NonNull<ffi::lv_obj_t>, style: WidgetStyle) {
    const SELECTOR: ffi::LvStyleSelector = 0;

    unsafe {
        if let Some(bg_color) = style.bg_color {
            ffi::lv_obj_set_style_bg_color(
                obj.as_ptr(),
                ffi::lv_color_hex(bg_color & 0xFFFFFF),
                SELECTOR,
            );
        }
        ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), style.bg_opa, SELECTOR);

        if let Some(text_color) = style.text_color {
            ffi::lv_obj_set_style_text_color(
                obj.as_ptr(),
                ffi::lv_color_hex(text_color & 0xFFFFFF),
                SELECTOR,
            );
        }

        if let Some(border_color) = style.border_color {
            ffi::lv_obj_set_style_border_color(
                obj.as_ptr(),
                ffi::lv_color_hex(border_color & 0xFFFFFF),
                SELECTOR,
            );
        }
        ffi::lv_obj_set_style_border_width(obj.as_ptr(), style.border_width, SELECTOR);
        ffi::lv_obj_set_style_radius(obj.as_ptr(), style.radius, SELECTOR);
        ffi::lv_obj_set_style_outline_width(obj.as_ptr(), style.outline_width, SELECTOR);
        ffi::lv_obj_set_style_shadow_width(obj.as_ptr(), style.shadow_width, SELECTOR);
    }
}

pub(crate) fn set_widget_hidden_raw(obj: NonNull<ffi::lv_obj_t>, hidden: bool) {
    unsafe {
        if hidden {
            ffi::lv_obj_add_flag(obj.as_ptr(), ffi::LV_OBJ_FLAG_HIDDEN);
        } else {
            ffi::lv_obj_remove_flag(obj.as_ptr(), ffi::LV_OBJ_FLAG_HIDDEN);
        }
    }
}
