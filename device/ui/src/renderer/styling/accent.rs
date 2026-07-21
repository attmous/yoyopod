use std::ptr::NonNull;

use crate::renderer::lvgl::ffi;
use crate::renderer::styling::style as theme;
use crate::scene::roles;
use crate::theme::ColorScheme;

use super::mix_u24;

pub(crate) fn apply_accent_raw(
    obj: NonNull<ffi::lv_obj_t>,
    role: &'static str,
    rgb: u32,
    color_scheme: ColorScheme,
) {
    const SELECTOR: ffi::LvStyleSelector = 0;
    let rgb = color_scheme.resolve_accent(role, rgb);
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
            roles::WHEEL_FOCUS_ICON
            | roles::WHEEL_PEEK_ICON
            | roles::MEDIA_WHEEL_PEEK_ICON
            | roles::MEDIA_WHEEL_FOCUS_ICON
            | roles::SETUP_PEEK_ICON
            | roles::SETUP_TILE_ICON
            | roles::SETUP_VOLUME_ICON => {
                ffi::lv_obj_set_style_image_recolor(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_image_recolor_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::WHEEL_AVATAR
            | roles::WHEEL_BADGE
            | roles::EMPTY_PLUS
            | roles::SETUP_PEEK_PLATE
            | roles::SETUP_PEEK_PLATE_ROUND
            | roles::SETUP_TILE_PLATE
            | roles::SETUP_TILE_PLATE_ROUND
            | roles::SETUP_VOLUME_BLOCK => {
                ffi::lv_obj_set_style_bg_color(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::HERO_ART | roles::HERO_AVATAR | roles::ASK_HERO => {
                ffi::lv_obj_set_style_bg_color(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::EMPTY_PLUS_ICON => {
                ffi::lv_obj_set_style_image_recolor(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_image_recolor_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::MEDIA_WHEEL_PEEK_PLATE | roles::MEDIA_WHEEL_FOCUS_PLATE => {
                ffi::lv_obj_set_style_bg_color(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::HERO_ARC => {
                ffi::lv_obj_set_style_arc_color(obj.as_ptr(), accent, ffi::LV_PART_INDICATOR);
            }
            roles::HERO_PLAY => {
                ffi::lv_obj_set_style_bg_color(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::HERO_ART_ICON
            | roles::HERO_PREV
            | roles::HERO_PLAY_ICON
            | roles::HERO_NEXT
            | roles::ASK_HERO_ICON => {
                ffi::lv_obj_set_style_image_recolor(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_image_recolor_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::FX_HALO | roles::FX_GLOW | roles::FX_SPINNER => {
                ffi::lv_obj_set_style_bg_color(
                    obj.as_ptr(),
                    ffi::lv_color_hex(mix_u24(rgb, color_scheme.background(), 70)),
                    SELECTOR,
                );
            }
            roles::FX_PULSE => {
                ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_border_color(obj.as_ptr(), accent, SELECTOR);
            }
            roles::CALL_AVATAR
            | roles::CALL_AVATAR_SM
            | roles::CALL_ANSWER
            | roles::CALL_MUTE
            | roles::CALL_HANGUP
            | roles::CALL_HANGUP_CENTER => {
                ffi::lv_obj_set_style_bg_color(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::SYS_BADGE => {
                ffi::lv_obj_set_style_bg_color(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::SYS_MSG
            | roles::HERO_AVATAR_INITIAL
            | roles::LIST_ROW_FOCUS_INITIAL
            | roles::LIST_ROW_IDLE_INITIAL
            | roles::STATUS_TIME
            | roles::STATUS_BATTERY_LABEL => {
                ffi::lv_obj_set_style_text_color(obj.as_ptr(), accent, SELECTOR);
            }
            roles::LIST_ROW_FOCUS_ICON | roles::LIST_ROW_IDLE_ICON => {
                ffi::lv_obj_set_style_image_recolor(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_image_recolor_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::STATUS_NETWORK_ICON
            | roles::STATUS_GPS_ICON
            | roles::STATUS_VOIP_ICON
            | roles::STATUS_CHARGE_ICON
            | roles::STATUS_BATTERY_ICON => {
                ffi::lv_obj_set_style_text_color(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_image_recolor(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_image_recolor_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::CALL_BUTTON_ICON => {
                ffi::lv_obj_set_style_image_recolor(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_image_recolor_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::FX_PARTICLE => {
                ffi::lv_obj_set_style_bg_color(obj.as_ptr(), accent, SELECTOR);
                ffi::lv_obj_set_style_bg_opa(obj.as_ptr(), theme::OPA_COVER, SELECTOR);
            }
            roles::FOOTER_LABEL => {
                ffi::lv_obj_set_style_text_color(
                    obj.as_ptr(),
                    ffi::lv_color_hex(mix_u24(rgb, color_scheme.background(), 65)),
                    SELECTOR,
                );
            }
            _ => {}
        }
    }
}
