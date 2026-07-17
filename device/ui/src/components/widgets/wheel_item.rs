use crate::components::primitives::{container, image, label};
use crate::engine::{Element, Key};
use crate::scene::deck::{WheelItemModel, WheelItemVariant};
use crate::scene::roles;

const INK: u32 = 0x1B1B1F;

pub fn wheel_item(model: &WheelItemModel, selected: bool, key: Key) -> Element {
    let root = container(roles::WHEEL_ITEM).key(key).selected(selected);
    match &model.variant {
        WheelItemVariant::Icon { icon_key } => root
            .child(image(roles::WHEEL_ICON).icon(icon_key).accent(INK))
            .child(label(roles::WHEEL_LABEL).text(&model.title)),
        WheelItemVariant::Media { initial, plate_rgb } => root
            .child(
                container(roles::WHEEL_PLATE)
                    .accent(*plate_rgb)
                    .child(label(roles::WHEEL_INITIAL).text(initial)),
            )
            .child(label(roles::WHEEL_LABEL_B).text(&model.title))
            .child(label(roles::WHEEL_SUB).text(&model.subtitle)),
    }
}
