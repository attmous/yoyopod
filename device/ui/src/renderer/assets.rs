use std::collections::{BTreeMap, BTreeSet};

use serde::Deserialize;
use thiserror::Error;

use crate::scene::roles;

const LAYOUTS_RON: &str = include_str!("../../assets/layouts.ron");
const THEME_RON: &str = include_str!("../../assets/theme.ron");

#[derive(Debug, Error)]
pub enum RenderAssetError {
    #[error("failed to parse {asset}: {source}")]
    Parse {
        asset: &'static str,
        #[source]
        source: ron::error::SpannedError,
    },
    #[error("{asset} missing role coverage: {roles:?}")]
    MissingRoles {
        asset: &'static str,
        roles: Vec<&'static str>,
    },
    #[error("{asset} has unknown roles: {roles:?}")]
    UnknownRoles {
        asset: &'static str,
        roles: Vec<String>,
    },
    #[error("{asset} has duplicate roles: {roles:?}")]
    DuplicateRoles {
        asset: &'static str,
        roles: Vec<String>,
    },
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct LayoutAsset {
    pub roles: Vec<LayoutRole>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct LayoutRole {
    pub role: String,
    pub x: i32,
    pub y: i32,
    pub width: i32,
    pub height: i32,
    #[serde(default)]
    pub repeat_x: Option<i32>,
    #[serde(default)]
    pub repeat_y: Option<i32>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct ThemeAsset {
    pub roles: Vec<ThemeRole>,
    #[serde(default)]
    pub selected_roles: Vec<ThemeRole>,
}

#[derive(Debug, Clone, PartialEq, Eq, Deserialize)]
pub struct ThemeRole {
    pub role: String,
    #[serde(default)]
    pub fill_rgb: Option<u32>,
    #[serde(default)]
    pub text_rgb: Option<u32>,
    #[serde(default)]
    pub opacity: Option<u8>,
    #[serde(default)]
    pub border_rgb: Option<u32>,
    #[serde(default)]
    pub border_width: i32,
    #[serde(default)]
    pub radius: i32,
    #[serde(default)]
    pub outline_width: i32,
    #[serde(default)]
    pub outline_rgb: Option<u32>,
    #[serde(default)]
    pub outline_pad: i32,
    #[serde(default)]
    pub arc_rgb: Option<u32>,
    #[serde(default)]
    pub arc_width: i32,
    #[serde(default)]
    pub arc_rounded: bool,
    #[serde(default)]
    pub shadow_width: i32,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct RenderAssets {
    layouts: BTreeMap<String, LayoutRole>,
    theme: BTreeMap<String, ThemeRole>,
    selected_theme: BTreeMap<String, ThemeRole>,
}

impl RenderAssets {
    pub fn layout_role(&self, role: &str) -> Option<&LayoutRole> {
        self.layouts.get(role)
    }

    pub fn theme_role(&self, role: &str) -> Option<&ThemeRole> {
        self.theme.get(role)
    }

    pub fn selected_theme_role(&self, role: &str) -> Option<&ThemeRole> {
        self.selected_theme.get(role)
    }
}

pub fn load_render_assets() -> Result<RenderAssets, RenderAssetError> {
    let layouts = parse_layout_asset()?;
    let theme = parse_theme_asset()?;
    Ok(RenderAssets {
        layouts: layouts
            .roles
            .into_iter()
            .map(|role| (role.role.clone(), role))
            .collect(),
        theme: theme
            .roles
            .into_iter()
            .map(|role| (role.role.clone(), role))
            .collect(),
        selected_theme: theme
            .selected_roles
            .into_iter()
            .map(|role| (role.role.clone(), role))
            .collect(),
    })
}

pub fn parse_layout_asset() -> Result<LayoutAsset, RenderAssetError> {
    let asset = ron::from_str(LAYOUTS_RON).map_err(|source| RenderAssetError::Parse {
        asset: "layouts.ron",
        source,
    })?;
    validate_layout_asset(&asset)?;
    Ok(asset)
}

pub fn parse_theme_asset() -> Result<ThemeAsset, RenderAssetError> {
    let asset = ron::from_str(THEME_RON).map_err(|source| RenderAssetError::Parse {
        asset: "theme.ron",
        source,
    })?;
    validate_theme_asset(&asset)?;
    Ok(asset)
}

pub fn validate_layout_asset(asset: &LayoutAsset) -> Result<(), RenderAssetError> {
    validate_role_coverage(
        "layouts.ron",
        required_layout_roles(),
        asset.roles.iter().map(|role| role.role.as_str()),
    )
}

pub fn validate_theme_asset(asset: &ThemeAsset) -> Result<(), RenderAssetError> {
    validate_role_coverage(
        "theme.ron",
        required_theme_roles(),
        asset.roles.iter().map(|role| role.role.as_str()),
    )?;
    validate_role_coverage(
        "theme.ron selected_roles",
        required_selected_theme_roles(),
        asset.selected_roles.iter().map(|role| role.role.as_str()),
    )
}

fn validate_role_coverage<'a>(
    asset: &'static str,
    required_roles: Vec<&'static str>,
    role_iter: impl IntoIterator<Item = &'a str>,
) -> Result<(), RenderAssetError> {
    let mut roles: BTreeSet<&str> = BTreeSet::new();
    let mut duplicates = BTreeSet::new();
    for role in role_iter {
        if !roles.insert(role) {
            duplicates.insert(role.to_string());
        }
    }
    if !duplicates.is_empty() {
        return Err(RenderAssetError::DuplicateRoles {
            asset,
            roles: duplicates.into_iter().collect(),
        });
    }

    let required = required_roles.into_iter().collect::<BTreeSet<_>>();
    let missing = required
        .iter()
        .copied()
        .into_iter()
        .filter(|role| !roles.contains(role))
        .collect::<Vec<_>>();
    if !missing.is_empty() {
        return Err(RenderAssetError::MissingRoles {
            asset,
            roles: missing,
        });
    }

    let unknown = roles
        .into_iter()
        .filter(|role| !required.contains(role))
        .map(str::to_string)
        .collect::<Vec<_>>();
    if !unknown.is_empty() {
        return Err(RenderAssetError::UnknownRoles {
            asset,
            roles: unknown,
        });
    }

    Ok(())
}

fn required_layout_roles() -> Vec<&'static str> {
    let roles = vec![
        roles::BUTTON,
        roles::BUTTON_ICON,
        roles::BUTTON_TITLE,
        roles::CALL_MUTE_LABEL,
        roles::CALL_PANEL,
        roles::CALL_STATE_LABEL,
        roles::CALL_TITLE,
        roles::CARD,
        roles::CARD_ICON,
        roles::CARD_SUBTITLE,
        roles::CARD_TITLE,
        roles::CURSOR_DOT,
        roles::CURSOR_DOTS,
        roles::CURSOR_ROW_GLOW,
        roles::DECK_BAR,
        roles::DECK_GLYPH,
        roles::DECK_PILL,
        roles::DECK_SLOT,
        roles::DECK_BUTTONS,
        roles::DECK_CARD_ROW,
        roles::DECK_GRID,
        roles::DECK_LIST,
        roles::DECK_WHEEL,
        roles::DECK_PAGE,
        roles::DECK_REGION,
        roles::FX_GLOW,
        roles::FX_HALO,
        roles::FX_PARTICLE,
        roles::FX_PULSE,
        roles::FX_SPINNER,
        roles::FOOTER_BAR,
        roles::FOOTER_LABEL,
        roles::COMPANION,
        roles::COMPANION_BODY,
        roles::COMPANION_CATCHLIGHT,
        roles::COMPANION_EYE,
        roles::COMPANION_MOUTH,
        roles::HUD,
        roles::LIST_ROW,
        roles::LIST_ROW_ICON,
        roles::LIST_ROW_SUBTITLE,
        roles::LIST_ROW_TITLE,
        roles::WHEEL_ITEM,
        roles::WHEEL_ICON,
        roles::WHEEL_LABEL,
        roles::TALK_WHEEL_ITEM,
        roles::WHEEL_AVATAR,
        roles::WHEEL_AVATAR_INITIAL,
        roles::WHEEL_BADGE,
        roles::WHEEL_BADGE_LABEL,
        roles::WHEEL_BADGE_LABEL_STUCK,
        roles::CONTEXT_LABEL,
        roles::EMPTY_STATE,
        roles::EMPTY_PLUS,
        roles::EMPTY_PLUS_ICON,
        roles::EMPTY_HINT,
        roles::MEDIA_WHEEL_HEADER,
        roles::MEDIA_WHEEL_HEADER_TITLE,
        roles::MEDIA_WHEEL_HEADER_COUNTER,
        roles::MEDIA_WHEEL_HEADER_DIVIDER,
        roles::MEDIA_WHEEL_PREVIOUS,
        roles::MEDIA_WHEEL_NEXT,
        roles::MEDIA_WHEEL_PEEK_PLATE,
        roles::MEDIA_WHEEL_PEEK_INITIAL,
        roles::MEDIA_WHEEL_PEEK_TITLE,
        roles::MEDIA_WHEEL_FOCUS,
        roles::MEDIA_WHEEL_FOCUS_PLATE,
        roles::MEDIA_WHEEL_FOCUS_INITIAL,
        roles::MEDIA_WHEEL_FOCUS_TITLE,
        roles::MEDIA_WHEEL_FOCUS_SUB,
        roles::HERO_PLAYER,
        roles::HERO_CONTEXT,
        roles::HERO_ARC,
        roles::HERO_ART,
        roles::HERO_ART_ICON,
        roles::HERO_AVATAR,
        roles::HERO_AVATAR_INITIAL,
        roles::HERO_PREV,
        roles::HERO_PLAY,
        roles::HERO_PLAY_ICON,
        roles::HERO_NEXT,
        roles::HERO_TIME_L,
        roles::HERO_TIME_R,
        roles::HERO_TITLE,
        roles::MODAL,
        roles::MODAL_MESSAGE,
        roles::MODAL_STACK,
        roles::MODAL_TITLE,
        roles::PAGE,
        roles::PAGE_BODY,
        roles::PAGE_TITLE,
        roles::PROGRESS_SWEEP,
        roles::PROGRESS_SWEEP_FILL,
        roles::SCENE_BACKDROP,
        roles::SCENE_DECKS,
        roles::SCENE_FX,
        roles::SCENE_GRAPH,
        roles::SCENE_ROOT,
        roles::SCENE_STAGE,
        roles::STATUS_BAR,
        roles::STATUS_LEFT_CLUSTER,
        roles::STATUS_NETWORK_ICON,
        roles::STATUS_GPS_ICON,
        roles::STATUS_VOIP_ICON,
        roles::STATUS_TIME,
        roles::STATUS_RIGHT_CLUSTER,
        roles::STATUS_BATTERY_LABEL,
        roles::STATUS_CHARGE_ICON,
        roles::STATUS_BATTERY_ICON,
        roles::VOICE_METER,
        roles::VOICE_METER_LEVEL,
        roles::RECORDING_PANEL,
        roles::RECORDING_CONTEXT,
        roles::RECORDING_TIMER_DOT,
        roles::RECORDING_TIMER,
        roles::RECORDING_HINT,
    ];
    roles
}

fn required_theme_roles() -> Vec<&'static str> {
    let mut roles = required_layout_roles();
    roles.push(roles::ROOT);
    roles.sort_unstable();
    roles.dedup();
    roles
}

fn required_selected_theme_roles() -> Vec<&'static str> {
    vec![
        roles::CURSOR_DOT,
        roles::LIST_ROW,
        roles::LIST_ROW_SUBTITLE,
        roles::LIST_ROW_TITLE,
        roles::WHEEL_ITEM,
        roles::TALK_WHEEL_ITEM,
        roles::MEDIA_WHEEL_FOCUS,
        roles::HERO_PREV,
        roles::HERO_PLAY,
        roles::HERO_NEXT,
    ]
}

#[cfg(test)]
mod tests {
    use super::*;

    fn layout<'a>(asset: &'a LayoutAsset, role: &str) -> &'a LayoutRole {
        asset
            .roles
            .iter()
            .find(|layout| layout.role == role)
            .unwrap_or_else(|| panic!("missing layout role {role}"))
    }

    fn theme<'a>(asset: &'a ThemeAsset, role: &str) -> &'a ThemeRole {
        asset
            .roles
            .iter()
            .find(|theme| theme.role == role)
            .unwrap_or_else(|| panic!("missing theme role {role}"))
    }

    fn selected_theme<'a>(asset: &'a ThemeAsset, role: &str) -> &'a ThemeRole {
        asset
            .selected_roles
            .iter()
            .find(|theme| theme.role == role)
            .unwrap_or_else(|| panic!("missing selected theme role {role}"))
    }

    #[test]
    fn shipped_layout_and_theme_cover_every_runtime_role() {
        let layouts = parse_layout_asset().expect("layouts.ron should be valid");
        let theme = parse_theme_asset().expect("theme.ron should be valid");

        assert!(layouts
            .roles
            .iter()
            .any(|role| role.role == roles::DECK_BAR));
        assert!(layouts
            .roles
            .iter()
            .any(|role| role.role == roles::COMPANION));
        assert!(theme.roles.iter().any(|role| role.role == roles::DECK_PILL));
        assert!(theme
            .roles
            .iter()
            .any(|role| role.role == roles::COMPANION_BODY));
    }

    #[test]
    fn recording_palette_uses_cream_content_and_a_coral_signal() {
        let asset = parse_theme_asset().expect("theme.ron should be valid");
        let meter = theme(&asset, roles::VOICE_METER);
        let meter_level = theme(&asset, roles::VOICE_METER_LEVEL);
        let timer_dot = theme(&asset, roles::RECORDING_TIMER_DOT);

        assert_eq!(meter.fill_rgb, Some(0xFCE6D2));
        assert_eq!(meter.opacity, Some(51));
        assert_eq!(meter_level.fill_rgb, Some(0xFCE6D2));
        assert_eq!(timer_dot.fill_rgb, Some(0xF37767));
        for role in [
            roles::RECORDING_CONTEXT,
            roles::RECORDING_TIMER,
            roles::RECORDING_HINT,
        ] {
            assert_eq!(theme(&asset, role).text_rgb, Some(0xFCE6D2));
        }
    }

    #[test]
    fn hero_focus_outline_does_not_override_the_semantic_accent() {
        let asset = parse_theme_asset().expect("theme.ron should be valid");
        let focused_play = selected_theme(&asset, roles::HERO_PLAY);

        assert_eq!(focused_play.fill_rgb, None);
        assert_eq!(focused_play.outline_rgb, Some(0x1B1B1F));
        assert_eq!(focused_play.outline_width, 2);
    }

    #[test]
    fn status_bar_is_centered_and_fits_the_charging_worst_case() {
        let layouts = parse_layout_asset().expect("layouts.ron should be valid");
        let left = layout(&layouts, roles::STATUS_LEFT_CLUSTER);
        let time = layout(&layouts, roles::STATUS_TIME);
        let right = layout(&layouts, roles::STATUS_RIGHT_CLUSTER);
        let label = layout(&layouts, roles::STATUS_BATTERY_LABEL);
        let charge = layout(&layouts, roles::STATUS_CHARGE_ICON);
        let battery = layout(&layouts, roles::STATUS_BATTERY_ICON);

        assert_eq!(left.x, 28);
        assert_eq!(240 - (right.x + right.width), 28);
        assert_eq!(time.x * 2 + time.width, 240);
        assert!(left.x + left.width <= time.x);
        assert!(time.x + time.width <= right.x);

        let two_flex_gaps = 2 * 3;
        assert!(label.width + charge.width + battery.width + two_flex_gaps <= right.width);
    }

    #[test]
    fn media_wheel_regions_do_not_overlap() {
        let layouts = parse_layout_asset().expect("layouts.ron should be valid");
        let header = layout(&layouts, roles::MEDIA_WHEEL_HEADER);
        let title = layout(&layouts, roles::MEDIA_WHEEL_HEADER_TITLE);
        let counter = layout(&layouts, roles::MEDIA_WHEEL_HEADER_COUNTER);
        let divider = layout(&layouts, roles::MEDIA_WHEEL_HEADER_DIVIDER);
        let previous = layout(&layouts, roles::MEDIA_WHEEL_PREVIOUS);
        let focus = layout(&layouts, roles::MEDIA_WHEEL_FOCUS);
        let next = layout(&layouts, roles::MEDIA_WHEEL_NEXT);
        let navigation = layout(&layouts, roles::DECK_BAR);

        assert!(title.x + title.width <= counter.x);
        assert!(divider.y + divider.height <= header.height);
        assert!(header.y + header.height <= previous.y);
        assert!(previous.y + previous.height <= focus.y);
        assert!(focus.y + focus.height <= next.y);
        assert!(next.y + next.height <= navigation.y);
        for region in [header, previous, focus, next] {
            assert!(region.x >= 0);
            assert!(region.x + region.width <= 240);
        }
    }
}
