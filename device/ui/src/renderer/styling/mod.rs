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
pub(crate) use base::{apply_style_raw, hide_widget_raw, reset_style_raw};
#[cfg(feature = "native-lvgl")]
pub(crate) use icons::icon_label;
#[cfg(feature = "native-lvgl")]
pub(crate) use tuning::apply_role_tuning_raw;
#[cfg(feature = "native-lvgl")]
pub(crate) use variants::apply_variant_raw;

/// Accent share (percent) mixed into the dark background for
/// accent-driven backdrops. Kept subtle so status chrome and hero
/// content stay legible on the 240x280 panel.
const BACKDROP_ACCENT_PERCENT: u8 = 22;

/// Resolve the background fill for a scene backdrop from its variant.
///
/// `solid` and `vignette` backdrops carry the base color in their accent
/// prop (see `scene::Backdrop::element`), so they pass through. Gradient
/// carries its `from` color the same way until a scene actually uses the
/// preset and the `to` stop is threaded through the prop pipeline.
/// `accent_drift` is the fix for the flood-filled hub/talk/ask screens:
/// the card accent tints the dark base instead of replacing it.
#[cfg_attr(not(feature = "native-lvgl"), allow(dead_code))]
pub(crate) fn backdrop_bg_rgb(variant: &str, accent_rgb: u32) -> u32 {
    match variant {
        "accent_drift" => mix_u24(
            accent_rgb & 0xFFFFFF,
            style::BACKGROUND_RGB,
            100 - BACKDROP_ACCENT_PERCENT,
        ),
        _ => accent_rgb & 0xFFFFFF,
    }
}

#[cfg_attr(not(feature = "native-lvgl"), allow(dead_code))]
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mix_full_secondary_returns_secondary() {
        assert_eq!(mix_u24(0x00FF88, 0x2A2D35, 100), 0x2A2D35);
    }

    #[test]
    fn mix_zero_secondary_returns_primary() {
        assert_eq!(mix_u24(0x00FF88, 0x2A2D35, 0), 0x00FF88);
    }

    #[test]
    fn accent_drift_tints_the_dark_base() {
        // listen accent 0x00FF88 at 22% over 0x2A2D35:
        // r = (0*22 + 42*78) / 100 = 32  (0x20)
        // g = (255*22 + 45*78) / 100 = 91 (0x5B)
        // b = (136*22 + 53*78) / 100 = 71 (0x47)
        assert_eq!(backdrop_bg_rgb("accent_drift", 0x00FF88), 0x205B47);
    }

    #[test]
    fn accent_drift_stays_near_the_base() {
        let tinted = backdrop_bg_rgb("accent_drift", 0x00FF88);
        let green = (tinted >> 8) & 0xFF;
        // The old bug flood-filled the raw accent (green channel 255).
        assert!(
            green < 0x80,
            "backdrop should be a subtle tint: {tinted:#08x}"
        );
    }

    #[test]
    fn solid_and_vignette_pass_the_base_through() {
        assert_eq!(backdrop_bg_rgb("solid", 0x2A2D35), 0x2A2D35);
        assert_eq!(backdrop_bg_rgb("vignette", 0x2A2D35), 0x2A2D35);
    }

    #[test]
    fn alpha_bits_are_stripped() {
        assert_eq!(backdrop_bg_rgb("solid", 0xFF2A2D35), 0x2A2D35);
    }
}
