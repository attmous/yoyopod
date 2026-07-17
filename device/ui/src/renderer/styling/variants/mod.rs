use std::ptr::NonNull;

use crate::renderer::lvgl::ffi;
use crate::renderer::styling::style as theme;
use crate::scene::roles;

pub(crate) fn apply_variant_raw(
    obj: NonNull<ffi::lv_obj_t>,
    role: &'static str,
    variant: &'static str,
    accent_rgb: u32,
) {
    const SELECTOR: ffi::LvStyleSelector = 0;
    unsafe {
        match (role, variant) {
            (roles::SCENE_BACKDROP, "solid" | "gradient" | "accent_drift" | "vignette") => {
                ffi::lv_obj_set_style_bg_color(
                    obj.as_ptr(),
                    ffi::lv_color_hex(super::backdrop_bg_rgb(variant, accent_rgb)),
                    SELECTOR,
                );
                ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            (roles::MODAL, "loading") => {
                ffi::lv_obj_set_style_border_color(
                    obj.as_ptr(),
                    ffi::lv_color_hex(theme::MUTED_RGB),
                    SELECTOR,
                );
                ffi::lv_obj_set_style_border_width(obj.as_ptr(), 1, SELECTOR);
            }
            (roles::MODAL, "error") => {
                ffi::lv_obj_set_style_border_color(
                    obj.as_ptr(),
                    ffi::lv_color_hex(theme::ERROR_RGB),
                    SELECTOR,
                );
                ffi::lv_obj_set_style_border_width(obj.as_ptr(), 1, SELECTOR);
            }
            _ => {}
        }
    }
}
