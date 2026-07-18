#[cfg(feature = "native-lvgl")]
mod accent;
#[cfg(feature = "native-lvgl")]
mod base;
#[cfg(feature = "native-lvgl")]
mod icons;
pub mod layout;
pub mod style;
pub mod theme;
#[cfg(feature = "native-lvgl")]
mod tuning;
#[cfg(feature = "native-lvgl")]
mod variants;

#[cfg(feature = "native-lvgl")]
pub(crate) use accent::apply_accent_raw;
#[cfg(feature = "native-lvgl")]
pub(crate) use base::{
    apply_arc_indicator_style_raw, apply_style_raw, reset_style_raw, set_widget_hidden_raw,
};
#[cfg(feature = "native-lvgl")]
pub(crate) use icons::icon_label;
#[cfg(feature = "native-lvgl")]
pub(crate) use tuning::apply_role_tuning_raw;
#[cfg(feature = "native-lvgl")]
pub(crate) use variants::apply_variant_raw;

#[cfg(feature = "native-lvgl")]
pub(crate) fn mix_u24(primary_rgb: u32, secondary_rgb: u32, secondary_ratio_percent: u8) -> u32 {
    let secondary_ratio = u32::from(secondary_ratio_percent.min(100));
    let primary_ratio = 100 - secondary_ratio;
    let red = ((((primary_rgb >> 16) & 0xFF) * primary_ratio
        + ((secondary_rgb >> 16) & 0xFF) * secondary_ratio)
        / 100)
        & 0xFF;
    let green = ((((primary_rgb >> 8) & 0xFF) * primary_ratio
        + ((secondary_rgb >> 8) & 0xFF) * secondary_ratio)
        / 100)
        & 0xFF;
    let blue = (((primary_rgb & 0xFF) * primary_ratio + (secondary_rgb & 0xFF) * secondary_ratio)
        / 100)
        & 0xFF;
    (red << 16) | (green << 8) | blue
}
