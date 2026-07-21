use anyhow::{anyhow, Result};

use crate::renderer::assets::{RenderAssets, ThemeRole};
use crate::renderer::styling::style::{self, WidgetStyle};
use crate::theme::{ColorScheme, ColorUse};

pub struct ThemeResolver<'a> {
    assets: &'a RenderAssets,
    color_scheme: ColorScheme,
}

impl<'a> ThemeResolver<'a> {
    pub const fn new(assets: &'a RenderAssets, color_scheme: ColorScheme) -> Self {
        Self {
            assets,
            color_scheme,
        }
    }

    pub fn style_for_role(&self, role: &'static str) -> Result<WidgetStyle> {
        let theme_role = self
            .assets
            .theme_role(role)
            .ok_or_else(|| anyhow!("missing LVGL theme asset for role {role}"))?;
        Ok(style_from_theme_role(
            role,
            theme_role,
            self.color_scheme,
            false,
        ))
    }

    pub fn style_for_selected_role(
        &self,
        role: &'static str,
        selected: bool,
    ) -> Result<WidgetStyle> {
        if selected {
            let theme_role = self
                .assets
                .selected_theme_role(role)
                .ok_or_else(|| anyhow!("missing selected LVGL theme asset for role {role}"))?;
            Ok(style_from_theme_role(
                role,
                theme_role,
                self.color_scheme,
                true,
            ))
        } else {
            self.style_for_role(role)
        }
    }
}

fn style_from_theme_role(
    role: &'static str,
    theme_role: &ThemeRole,
    color_scheme: ColorScheme,
    selected: bool,
) -> WidgetStyle {
    let resolve = |color_use, rgb: Option<u32>| {
        rgb.map(|rgb| color_scheme.resolve_role_color(role, color_use, selected, rgb))
    };
    WidgetStyle {
        bg_color: resolve(ColorUse::Fill, theme_role.fill_rgb),
        bg_opa: theme_role.opacity.unwrap_or(style::OPA_TRANSP),
        text_color: resolve(ColorUse::Text, theme_role.text_rgb),
        border_color: resolve(ColorUse::Border, theme_role.border_rgb),
        border_width: theme_role.border_width,
        radius: theme_role.radius,
        outline_width: theme_role.outline_width,
        outline_color: resolve(ColorUse::Outline, theme_role.outline_rgb),
        outline_pad: theme_role.outline_pad,
        arc_color: resolve(ColorUse::Arc, theme_role.arc_rgb),
        arc_width: theme_role.arc_width,
        arc_rounded: theme_role.arc_rounded,
        shadow_width: theme_role.shadow_width,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::renderer::assets::load_render_assets;
    use crate::scene::roles;
    use crate::theme::{INK_300_DARK, INK_DARK, INK_ON_ACCENT, INK_SOFT_LIGHT, STAGE_LIME_DARK};

    #[test]
    fn dark_role_resolution_is_semantic_and_selected_content_stays_legible() {
        let assets = load_render_assets().expect("render assets");
        let dark = ThemeResolver::new(&assets, ColorScheme::Dark);

        let backdrop = dark
            .style_for_role(roles::SCENE_BACKDROP)
            .expect("backdrop style");
        assert_eq!(backdrop.bg_color, Some(crate::theme::SURFACE_0_DARK));

        for role in [
            roles::WHEEL_FOCUS_LABEL,
            roles::LIST_ROW_FOCUS_TITLE,
            roles::MEDIA_WHEEL_FOCUS_TITLE,
            roles::SETUP_TILE_NAME,
        ] {
            let style = dark.style_for_role(role).expect("focus foreground style");
            assert_eq!(
                style.text_color,
                Some(INK_ON_ACCENT),
                "{role} must use dark ink on an accent surface"
            );
        }
        for role in [
            roles::LIST_ROW_FOCUS_SUBTITLE,
            roles::MEDIA_WHEEL_FOCUS_SUB,
            roles::SETUP_TILE_SUB,
        ] {
            let style = dark.style_for_role(role).expect("focus secondary style");
            assert_eq!(
                style.text_color,
                Some(INK_SOFT_LIGHT),
                "{role} must keep soft dark ink on an accent surface"
            );
        }
        for role in [
            roles::WHEEL_PEEK_LABEL,
            roles::LIST_ROW_IDLE_TITLE,
            roles::MEDIA_WHEEL_PEEK_TITLE,
        ] {
            let style = dark.style_for_role(role).expect("stage foreground style");
            assert_eq!(
                style.text_color,
                Some(INK_DARK),
                "{role} must use warm light ink on the dark stage"
            );
        }
        let setup_peek_title = dark
            .style_for_role(roles::SETUP_PEEK_TITLE)
            .expect("setup peek title style");
        assert_eq!(
            setup_peek_title.text_color,
            Some(crate::theme::INK_SOFT_DARK)
        );
        let idle_secondary = dark
            .style_for_role(roles::LIST_ROW_IDLE_SUBTITLE)
            .expect("idle list secondary style");
        assert_eq!(idle_secondary.text_color, Some(INK_300_DARK));

        let setup_peek_icon =
            ColorScheme::Dark.resolve_accent(roles::SETUP_PEEK_ICON, crate::theme::INK_LIGHT);
        assert_eq!(setup_peek_icon, INK_ON_ACCENT);

        let focused_transport = dark
            .style_for_selected_role(roles::HERO_PLAY, true)
            .expect("focused transport style");
        assert_eq!(focused_transport.outline_color, Some(INK_DARK));

        assert_eq!(
            ColorScheme::Dark.resolve_accent(roles::SCENE_BACKDROP, 0xE6FDE0),
            STAGE_LIME_DARK
        );
    }
}
