use crate::animation::presets::MEDIA_WHEEL_PEEK_OPACITY;
use crate::components::primitives::{container, image, label};
use crate::engine::{Element, Key};
use crate::scene::deck::{WheelItemModel, WheelItemVariant};
use crate::scene::roles;

const INK: u32 = 0x1B1B1F;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WheelItemSlot {
    Standard,
    Previous,
    Focused,
    Next,
}

pub fn wheel_item(
    model: &WheelItemModel,
    selected: bool,
    slot: WheelItemSlot,
    key: Key,
) -> Element {
    match &model.variant {
        WheelItemVariant::Icon { icon_key } => container(roles::WHEEL_ITEM)
            .key(key)
            .selected(selected)
            .child(image(roles::WHEEL_ICON).icon(icon_key).accent(INK))
            .child(label(roles::WHEEL_LABEL).text(&model.title)),
        WheelItemVariant::Media { initial, plate_rgb } => match slot {
            WheelItemSlot::Previous => {
                media_peek(roles::MEDIA_WHEEL_PREVIOUS, model, initial, *plate_rgb, key)
            }
            WheelItemSlot::Next => {
                media_peek(roles::MEDIA_WHEEL_NEXT, model, initial, *plate_rgb, key)
            }
            WheelItemSlot::Focused => container(roles::MEDIA_WHEEL_FOCUS)
                .key(key)
                .selected(true)
                .child(
                    container(roles::MEDIA_WHEEL_FOCUS_PLATE)
                        .accent(*plate_rgb)
                        .child(label(roles::MEDIA_WHEEL_FOCUS_INITIAL).text(initial)),
                )
                .child(label(roles::MEDIA_WHEEL_FOCUS_TITLE).text(&model.title))
                .child(label(roles::MEDIA_WHEEL_FOCUS_SUB).text(&model.subtitle)),
            WheelItemSlot::Standard => {
                unreachable!("media wheel item requires a semantic slot")
            }
        },
    }
}

fn media_peek(
    role: &'static str,
    model: &WheelItemModel,
    initial: &str,
    plate_rgb: u32,
    key: Key,
) -> Element {
    container(role)
        .key(key)
        .opacity(MEDIA_WHEEL_PEEK_OPACITY)
        .child(
            container(roles::MEDIA_WHEEL_PEEK_PLATE)
                .accent(plate_rgb)
                .child(label(roles::MEDIA_WHEEL_PEEK_INITIAL).text(initial)),
        )
        .child(label(roles::MEDIA_WHEEL_PEEK_TITLE).text(&model.title))
}
