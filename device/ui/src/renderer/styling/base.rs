use std::ptr::NonNull;

use crate::renderer::lvgl::ffi;
use crate::renderer::styling::style::WidgetStyle;

pub(crate) fn reset_style_raw(obj: NonNull<ffi::lv_obj_t>) {
    unsafe {
        ffi::lv_obj_remove_style_all(obj.as_ptr());
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
        if let Some(outline_color) = style.outline_color {
            ffi::lv_obj_set_style_outline_color(
                obj.as_ptr(),
                ffi::lv_color_hex(outline_color & 0xFFFFFF),
                SELECTOR,
            );
        }
        ffi::lv_obj_set_style_outline_width(obj.as_ptr(), style.outline_width, SELECTOR);
        ffi::lv_obj_set_style_outline_pad(obj.as_ptr(), style.outline_pad, SELECTOR);
        if let Some(arc_color) = style.arc_color {
            ffi::lv_obj_set_style_arc_color(
                obj.as_ptr(),
                ffi::lv_color_hex(arc_color & 0xFFFFFF),
                SELECTOR,
            );
        }
        ffi::lv_obj_set_style_arc_width(obj.as_ptr(), style.arc_width, SELECTOR);
        ffi::lv_obj_set_style_arc_rounded(obj.as_ptr(), style.arc_rounded, SELECTOR);
        ffi::lv_obj_set_style_shadow_width(obj.as_ptr(), style.shadow_width, SELECTOR);
    }
}

pub(crate) fn apply_arc_indicator_style_raw(obj: NonNull<ffi::lv_obj_t>, style: WidgetStyle) {
    unsafe {
        if let Some(arc_color) = style.arc_color {
            ffi::lv_obj_set_style_arc_color(
                obj.as_ptr(),
                ffi::lv_color_hex(arc_color & 0xFFFFFF),
                ffi::LV_PART_INDICATOR,
            );
        }
        ffi::lv_obj_set_style_arc_width(obj.as_ptr(), style.arc_width, ffi::LV_PART_INDICATOR);
        ffi::lv_obj_set_style_arc_rounded(obj.as_ptr(), style.arc_rounded, ffi::LV_PART_INDICATOR);
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
