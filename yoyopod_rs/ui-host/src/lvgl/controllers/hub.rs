use anyhow::{anyhow, bail, Result};

use super::shared::{FooterBar, StatusBarWidgets};
use crate::lvgl::chrome;
use crate::lvgl::{LvglFacade, ScreenController, WidgetId};
use crate::screens::ScreenModel;

#[derive(Default)]
pub struct HubController {
    root: Option<WidgetId>,
    status: StatusBarWidgets,
    icon_glow: Option<WidgetId>,
    card_panel: Option<WidgetId>,
    icon: Option<WidgetId>,
    title: Option<WidgetId>,
    subtitle: Option<WidgetId>,
    dots: Vec<WidgetId>,
    footer: FooterBar,
}

impl HubController {
    fn ensure_widgets(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        if self.root.is_none() {
            self.root = Some(facade.create_root()?);
        }
        let root = self
            .root
            .ok_or_else(|| anyhow!("hub controller missing root widget"))?;

        if self.icon_glow.is_none() {
            self.icon_glow = Some(facade.create_container(root, "hub_icon_glow")?);
        }
        if self.card_panel.is_none() {
            self.card_panel = Some(facade.create_container(root, "hub_card_panel")?);
        }
        let card_panel = self
            .card_panel
            .ok_or_else(|| anyhow!("hub controller missing card panel"))?;
        if self.icon.is_none() {
            self.icon = Some(facade.create_label(card_panel, "hub_icon")?);
        }
        if self.title.is_none() {
            self.title = Some(facade.create_label(root, "hub_title")?);
        }
        if self.subtitle.is_none() {
            self.subtitle = Some(facade.create_label(root, "hub_subtitle")?);
        }
        while self.dots.len() < 4 {
            self.dots.push(facade.create_container(root, "hub_dot")?);
        }
        Ok(())
    }
}

impl ScreenController for HubController {
    fn sync(&mut self, facade: &mut dyn LvglFacade, model: &ScreenModel) -> Result<()> {
        let ScreenModel::Hub(model) = model else {
            bail!(
                "hub controller received non-hub screen model: {}",
                model.screen().as_str()
            );
        };

        self.ensure_widgets(facade)?;
        let selected = chrome::focused_hub_card(model);
        let accent = selected.map(|card| card.accent).unwrap_or(0x00FF88);
        let icon_key = selected.map(|card| card.key.as_str()).unwrap_or("listen");

        if let Some(root) = self.root {
            self.status.sync(facade, root, &model.chrome.status)?;
            self.footer
                .sync(facade, root, "hub_footer", &model.chrome.footer)?;
        }
        if let Some(icon_glow) = self.icon_glow {
            facade.set_accent(icon_glow, accent)?;
        }
        if let Some(card_panel) = self.card_panel {
            facade.set_accent(card_panel, accent)?;
        }
        if let Some(icon) = self.icon {
            facade.set_icon(icon, icon_key)?;
            facade.set_accent(icon, accent)?;
        }

        if let Some(title) = self.title {
            facade.set_text(title, chrome::focused_hub_title(model))?;
        }
        if let Some(subtitle) = self.subtitle {
            facade.set_text(
                subtitle,
                selected
                    .map(|card| card.subtitle.as_str())
                    .unwrap_or("Music and calls"),
            )?;
        }
        let total_cards = model.cards.len().clamp(1, 4);
        let selected_index = model.selected_index % total_cards;
        for index in 0..4 {
            if let Some(dot) = self.dots.get(index).copied() {
                facade.set_selected(dot, index == selected_index)?;
                facade.set_visible(dot, index < total_cards)?;
            }
        }

        Ok(())
    }

    fn teardown(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        let root = self.root.take();
        self.status.clear();
        self.icon_glow = None;
        self.card_panel = None;
        self.icon = None;
        self.title = None;
        self.subtitle = None;
        self.dots.clear();
        self.footer.clear();
        if let Some(root) = root {
            facade.destroy(root)?;
        }
        Ok(())
    }
}
