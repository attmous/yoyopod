use crate::animation::presets::{MEDIA_WHEEL_PEEK_OPACITY, SETUP_WHEEL_PEEK_OPACITY};
use crate::components::primitives::{container, image, label};
use crate::engine::{Element, Key};
use crate::scene::deck::{WheelBadgeKind, WheelItemModel, WheelItemVariant};
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
        WheelItemVariant::Contact {
            initial,
            avatar_rgb,
            badge,
        } => {
            assert_eq!(slot, WheelItemSlot::Standard);
            let root = container(roles::TALK_WHEEL_ITEM)
                .key(key)
                .selected(selected)
                .child(
                    container(roles::WHEEL_AVATAR)
                        .accent(*avatar_rgb)
                        .child(label(roles::WHEEL_AVATAR_INITIAL).text(initial)),
                )
                .child(label(roles::WHEEL_LABEL).text(&model.title));
            match badge {
                Some(badge) => root.child(
                    container(roles::WHEEL_BADGE)
                        .accent(match badge.kind {
                            WheelBadgeKind::Count => 0xF37767,
                            WheelBadgeKind::Stuck => 0xE5443B,
                        })
                        .child(
                            label(match badge.kind {
                                WheelBadgeKind::Count => roles::WHEEL_BADGE_LABEL,
                                WheelBadgeKind::Stuck => roles::WHEEL_BADGE_LABEL_STUCK,
                            })
                            .text(&badge.label),
                        ),
                ),
                None => root,
            }
        }
        WheelItemVariant::Action { icon_key, badge } => {
            assert_eq!(slot, WheelItemSlot::Standard);
            let root = container(roles::TALK_WHEEL_ITEM)
                .key(key)
                .selected(selected)
                .child(image(roles::WHEEL_ICON).icon(icon_key).accent(INK))
                .child(label(roles::WHEEL_LABEL).text(&model.title));
            match badge {
                Some(badge) => root.child(
                    container(roles::WHEEL_BADGE)
                        .accent(match badge.kind {
                            WheelBadgeKind::Count => 0xF37767,
                            WheelBadgeKind::Stuck => 0xE5443B,
                        })
                        .child(
                            label(match badge.kind {
                                WheelBadgeKind::Count => roles::WHEEL_BADGE_LABEL,
                                WheelBadgeKind::Stuck => roles::WHEEL_BADGE_LABEL_STUCK,
                            })
                            .text(&badge.label),
                        ),
                ),
                None => root,
            }
        }
        WheelItemVariant::Setup {
            icon_key,
            plate_rgb,
            round,
        } => match slot {
            WheelItemSlot::Previous => setup_peek(
                roles::SETUP_WHEEL_PREVIOUS,
                model,
                icon_key,
                *plate_rgb,
                *round,
                key,
            ),
            WheelItemSlot::Next => setup_peek(
                roles::SETUP_WHEEL_NEXT,
                model,
                icon_key,
                *plate_rgb,
                *round,
                key,
            ),
            WheelItemSlot::Focused => container(roles::SETUP_WHEEL_ITEM)
                .key(key)
                .selected(true)
                .child(
                    container(if *round {
                        roles::SETUP_TILE_PLATE_ROUND
                    } else {
                        roles::SETUP_TILE_PLATE
                    })
                    .accent(*plate_rgb)
                    .child(image(roles::SETUP_TILE_ICON).icon(icon_key).accent(INK)),
                )
                .child(label(roles::SETUP_TILE_NAME).text(&model.title))
                .child(label(roles::SETUP_TILE_SUB).text(&model.subtitle)),
            WheelItemSlot::Standard => {
                unreachable!("setup wheel item requires a semantic slot")
            }
        },
    }
}

fn setup_peek(
    role: &'static str,
    model: &WheelItemModel,
    icon_key: &str,
    plate_rgb: u32,
    round: bool,
    key: Key,
) -> Element {
    container(role)
        .key(key)
        .opacity(SETUP_WHEEL_PEEK_OPACITY)
        .child(
            container(if round {
                roles::SETUP_PEEK_PLATE_ROUND
            } else {
                roles::SETUP_PEEK_PLATE
            })
            .accent(plate_rgb)
            .child(
                image(roles::SETUP_PEEK_ICON)
                    .icon(icon_key)
                    .accent(INK)
                    .scale_permille(500),
            ),
        )
        .child(label(roles::SETUP_PEEK_TITLE).text(&model.title))
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
