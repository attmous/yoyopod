use crate::scene::roles;

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub enum ColorScheme {
    #[default]
    Light,
    Dark,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ColorUse {
    Fill,
    Text,
    Border,
    Outline,
    Arc,
}

pub const SURFACE_0_LIGHT: u32 = 0xFCE6D2;
pub const SURFACE_1_LIGHT: u32 = 0xF7DBC2;
pub const STAGE_LIME_LIGHT: u32 = 0xE6FDE0;
pub const STAGE_PERI_LIGHT: u32 = 0xE7E5F7;
pub const STAGE_BUTTER_LIGHT: u32 = 0xFFF0CC;
pub const STAGE_CORAL_LIGHT: u32 = 0xFDE2D8;
pub const INK_LIGHT: u32 = 0x1B1B1F;
pub const INK_SOFT_LIGHT: u32 = 0x3A3A40;
pub const INK_300_LIGHT: u32 = 0x8A8076;

pub const SURFACE_0_DARK: u32 = 0x1B1B1F;
pub const SURFACE_1_DARK: u32 = 0x2A2A30;
pub const STAGE_LIME_DARK: u32 = 0x1F2A1E;
pub const STAGE_PERI_DARK: u32 = 0x1F1F2A;
pub const STAGE_BUTTER_DARK: u32 = 0x2A271B;
pub const STAGE_CORAL_DARK: u32 = 0x2A1F1D;
pub const INK_DARK: u32 = 0xF2E8DA;
pub const INK_SOFT_DARK: u32 = 0xB8AC9A;
pub const INK_300_DARK: u32 = 0x6E665C;
pub const INK_ON_ACCENT: u32 = 0x1B1B1F;

impl ColorScheme {
    /// Resolve the stored setting using panel-local time. Auto is light from
    /// 07:00 through 18:59 and dark from 19:00 through 06:59.
    pub fn resolve(setting: &str, local_hour: u8) -> Self {
        match setting.trim().to_ascii_lowercase().as_str() {
            "dark" => Self::Dark,
            "auto" if !(7..19).contains(&local_hour) => Self::Dark,
            _ => Self::Light,
        }
    }

    pub const fn background(self) -> u32 {
        match self {
            Self::Light => SURFACE_0_LIGHT,
            Self::Dark => SURFACE_0_DARK,
        }
    }

    pub fn resolve_role_color(
        self,
        role: &'static str,
        color_use: ColorUse,
        selected: bool,
        rgb: u32,
    ) -> u32 {
        if self == Self::Light {
            return rgb;
        }

        if rgb == INK_LIGHT {
            if color_use == ColorUse::Fill && role == roles::SYS_SCRIM {
                return INK_ON_ACCENT;
            }
            if color_use == ColorUse::Text && (selected || uses_ink_on_accent(role)) {
                return INK_ON_ACCENT;
            }
            return INK_DARK;
        }

        if rgb == SURFACE_0_LIGHT {
            return match color_use {
                ColorUse::Text => INK_DARK,
                ColorUse::Fill if matches!(role, roles::VOICE_METER | roles::VOICE_METER_LEVEL) => {
                    INK_DARK
                }
                _ => SURFACE_0_DARK,
            };
        }

        resolve_dark_token(rgb)
    }

    pub fn resolve_accent(self, role: &'static str, rgb: u32) -> u32 {
        if self == Self::Light {
            return rgb;
        }
        if rgb == INK_LIGHT {
            return if uses_ink_on_accent(role) {
                INK_ON_ACCENT
            } else {
                INK_DARK
            };
        }
        if rgb == SURFACE_0_LIGHT {
            return if role == roles::SCENE_BACKDROP {
                SURFACE_0_DARK
            } else {
                SURFACE_0_LIGHT
            };
        }
        resolve_dark_token(rgb)
    }
}

fn resolve_dark_token(rgb: u32) -> u32 {
    match rgb {
        SURFACE_0_LIGHT => SURFACE_0_DARK,
        SURFACE_1_LIGHT | 0xF6F2EB => SURFACE_1_DARK,
        STAGE_LIME_LIGHT => STAGE_LIME_DARK,
        STAGE_PERI_LIGHT => STAGE_PERI_DARK,
        STAGE_BUTTER_LIGHT => STAGE_BUTTER_DARK,
        STAGE_CORAL_LIGHT => STAGE_CORAL_DARK,
        INK_SOFT_LIGHT => INK_SOFT_DARK,
        INK_300_LIGHT => INK_300_DARK,
        _ => rgb,
    }
}

fn uses_ink_on_accent(role: &'static str) -> bool {
    matches!(
        role,
        roles::DECK_GLYPH
            | roles::WHEEL_ICON
            | roles::WHEEL_AVATAR_INITIAL
            | roles::WHEEL_BADGE_LABEL
            | roles::EMPTY_PLUS_ICON
            | roles::MEDIA_WHEEL_PEEK_INITIAL
            | roles::MEDIA_WHEEL_FOCUS_INITIAL
            | roles::SETUP_TILE_ICON
            | roles::HERO_ART_ICON
            | roles::HERO_AVATAR_INITIAL
            | roles::HERO_PLAY_ICON
            | roles::REPLAY_DELETE_ICON
            | roles::REPLAY_PLAY_ICON
            | roles::REPLAY_NEXT_ICON
            | roles::CALL_AVATAR_INITIAL
            | roles::CALL_AVATAR_INITIAL_SM
            | roles::CALL_BUTTON_ICON
            | roles::SYS_BADGE
            | roles::ASK_HERO_ICON
    )
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn explicit_and_auto_preferences_resolve_deterministically() {
        assert_eq!(ColorScheme::resolve("Light", 23), ColorScheme::Light);
        assert_eq!(ColorScheme::resolve("Dark", 12), ColorScheme::Dark);
        assert_eq!(ColorScheme::resolve("Auto", 6), ColorScheme::Dark);
        assert_eq!(ColorScheme::resolve("Auto", 7), ColorScheme::Light);
        assert_eq!(ColorScheme::resolve("Auto", 18), ColorScheme::Light);
        assert_eq!(ColorScheme::resolve("Auto", 19), ColorScheme::Dark);
    }

    #[test]
    fn dark_scheme_swaps_surfaces_and_ink_but_preserves_accent_foregrounds() {
        assert_eq!(
            ColorScheme::Dark.resolve_accent(roles::SCENE_BACKDROP, STAGE_LIME_LIGHT),
            STAGE_LIME_DARK
        );
        assert_eq!(
            ColorScheme::Dark.resolve_accent(roles::STATUS_NETWORK_ICON, INK_LIGHT),
            INK_DARK
        );
        assert_eq!(
            ColorScheme::Dark.resolve_accent(roles::DECK_GLYPH, INK_LIGHT),
            INK_ON_ACCENT
        );
        assert_eq!(
            ColorScheme::Dark.resolve_role_color(
                roles::HERO_PLAY,
                ColorUse::Outline,
                true,
                INK_LIGHT,
            ),
            INK_DARK
        );
        assert_eq!(
            ColorScheme::Dark.resolve_role_color(
                roles::RECORDING_CONTEXT,
                ColorUse::Text,
                false,
                SURFACE_0_LIGHT,
            ),
            INK_DARK
        );
        assert_eq!(
            ColorScheme::Dark.resolve_accent(roles::ASK_HERO, SURFACE_0_LIGHT),
            SURFACE_0_LIGHT
        );
    }
}
