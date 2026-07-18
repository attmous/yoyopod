use anyhow::{anyhow, Result};

use crate::renderer::assets::{RenderAssets, ThemeRole};
use crate::renderer::styling::style::{self, WidgetStyle};

pub struct ThemeResolver<'a> {
    assets: &'a RenderAssets,
}

impl<'a> ThemeResolver<'a> {
    pub const fn new(assets: &'a RenderAssets) -> Self {
        Self { assets }
    }

    pub fn style_for_role(&self, role: &str) -> Result<WidgetStyle> {
        let theme_role = self
            .assets
            .theme_role(role)
            .ok_or_else(|| anyhow!("missing LVGL theme asset for role {role}"))?;
        Ok(style_from_theme_role(theme_role))
    }

    pub fn style_for_selected_role(&self, role: &str, selected: bool) -> Result<WidgetStyle> {
        if selected {
            let theme_role = self
                .assets
                .selected_theme_role(role)
                .ok_or_else(|| anyhow!("missing selected LVGL theme asset for role {role}"))?;
            Ok(style_from_theme_role(theme_role))
        } else {
            self.style_for_role(role)
        }
    }
}

fn style_from_theme_role(theme_role: &ThemeRole) -> WidgetStyle {
    WidgetStyle {
        bg_color: theme_role.fill_rgb,
        bg_opa: theme_role.opacity.unwrap_or(style::OPA_TRANSP),
        text_color: theme_role.text_rgb,
        border_color: theme_role.border_rgb,
        border_width: theme_role.border_width,
        radius: theme_role.radius,
        outline_width: theme_role.outline_width,
        outline_color: theme_role.outline_rgb,
        outline_pad: theme_role.outline_pad,
        arc_color: theme_role.arc_rgb,
        arc_width: theme_role.arc_width,
        arc_rounded: theme_role.arc_rounded,
        shadow_width: theme_role.shadow_width,
    }
}
