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
            | roles::DECK_WHEEL
            | roles::DECK_SLOT
            | roles::DECK_PILL
            | roles::COMPANION
            | roles::COMPANION_BODY
            | roles::COMPANION_EYE
            | roles::HERO_PLAYER
            | roles::HERO_ART
            | roles::HERO_AVATAR
            | roles::HERO_PLAY
            | roles::CALL_OVERLAY
            | roles::ASK_SURFACE
            | roles::ASK_HERO
            | roles::ASK_PROGRESS
            | roles::STATUS_BAR => {
                ffi::lv_obj_set_scrollbar_mode(obj.as_ptr(), ffi::LV_SCROLLBAR_MODE_OFF);
            }
            roles::STATUS_LEFT_CLUSTER | roles::STATUS_RIGHT_CLUSTER => {
                ffi::lv_obj_set_style_pad_left(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_right(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_top(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_bottom(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_column(
                    obj.as_ptr(),
                    if role == roles::STATUS_LEFT_CLUSTER {
                        4
                    } else {
                        3
                    },
                    SELECTOR,
                );
                ffi::lv_obj_set_scrollbar_mode(obj.as_ptr(), ffi::LV_SCROLLBAR_MODE_OFF);
                ffi::lv_obj_set_flex_flow(obj.as_ptr(), ffi::LV_FLEX_FLOW_ROW);
                ffi::lv_obj_set_flex_align(
                    obj.as_ptr(),
                    if role == roles::STATUS_LEFT_CLUSTER {
                        ffi::LV_FLEX_ALIGN_START
                    } else {
                        ffi::LV_FLEX_ALIGN_END
                    },
                    ffi::LV_FLEX_ALIGN_CENTER,
                    ffi::LV_FLEX_ALIGN_CENTER,
                );
            }
            roles::LIST_ROW => {
                ffi::lv_obj_set_style_pad_left(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_right(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_top(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_bottom(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_scrollbar_mode(obj.as_ptr(), ffi::LV_SCROLLBAR_MODE_OFF);
            }
            roles::WHEEL_ITEM
            | roles::TALK_WHEEL_ITEM
            | roles::WHEEL_AVATAR
            | roles::WHEEL_BADGE
            | roles::EMPTY_STATE
            | roles::EMPTY_PLUS
            | roles::MEDIA_WHEEL_HEADER
            | roles::MEDIA_WHEEL_PREVIOUS
            | roles::MEDIA_WHEEL_NEXT
            | roles::MEDIA_WHEEL_PEEK_PLATE
            | roles::MEDIA_WHEEL_FOCUS
            | roles::MEDIA_WHEEL_FOCUS_PLATE => {
                ffi::lv_obj_set_style_pad_left(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_right(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_top(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_bottom(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_scrollbar_mode(obj.as_ptr(), ffi::LV_SCROLLBAR_MODE_OFF);
            }
            roles::SETUP_WHEEL_ITEM
            | roles::SETUP_TILE_PLATE
            | roles::SETUP_TILE_PLATE_ROUND
            | roles::SETUP_VOLUME
            | roles::SETUP_VOLUME_METER
            | roles::SETUP_VOLUME_BLOCK
            | roles::SETUP_ABOUT => {
                ffi::lv_obj_set_style_pad_left(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_right(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_top(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_bottom(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_scrollbar_mode(obj.as_ptr(), ffi::LV_SCROLLBAR_MODE_OFF);
            }
            roles::RECORDING_PANEL | roles::VOICE_METER | roles::RECORDING_TIMER_DOT => {
                ffi::lv_obj_set_style_pad_left(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_right(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_top(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_bottom(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_scrollbar_mode(obj.as_ptr(), ffi::LV_SCROLLBAR_MODE_OFF);
            }
            roles::CALL_AVATAR
            | roles::CALL_AVATAR_SM
            | roles::CALL_ANSWER
            | roles::CALL_MUTE
            | roles::CALL_HANGUP
            | roles::CALL_HANGUP_CENTER => {
                ffi::lv_obj_set_style_pad_left(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_right(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_top(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_style_pad_bottom(obj.as_ptr(), 0, SELECTOR);
                ffi::lv_obj_set_scrollbar_mode(obj.as_ptr(), ffi::LV_SCROLLBAR_MODE_OFF);
            }
            _ => return false,
        }
    }
    true
}
