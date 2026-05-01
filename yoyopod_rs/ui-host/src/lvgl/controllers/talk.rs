use anyhow::{anyhow, bail, Result};

use super::shared::{FooterBar, StatusBarWidgets};
use crate::lvgl::{LvglFacade, ScreenController, WidgetId};
use crate::screens::{ListScreenModel, ScreenModel};

#[derive(Default)]
pub struct TalkController {
    root: Option<WidgetId>,
    status: StatusBarWidgets,
    card_glow: Option<WidgetId>,
    card_panel: Option<WidgetId>,
    card_label: Option<WidgetId>,
    title: Option<WidgetId>,
    footer: FooterBar,
}

impl TalkController {
    fn ensure_widgets(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        if self.root.is_none() {
            self.root = Some(facade.create_root()?);
        }
        let root = self
            .root
            .ok_or_else(|| anyhow!("talk controller missing root widget"))?;

        if self.card_glow.is_none() {
            self.card_glow = Some(facade.create_container(root, "talk_card_glow")?);
        }
        if self.card_panel.is_none() {
            self.card_panel = Some(facade.create_container(root, "talk_card_panel")?);
        }
        let card_panel = self
            .card_panel
            .ok_or_else(|| anyhow!("talk controller missing card panel"))?;
        if self.card_label.is_none() {
            self.card_label = Some(facade.create_label(card_panel, "talk_card_label")?);
        }
        if self.title.is_none() {
            self.title = Some(facade.create_label(root, "talk_title")?);
        }
        Ok(())
    }
}

impl ScreenController for TalkController {
    fn sync(&mut self, facade: &mut dyn LvglFacade, model: &ScreenModel) -> Result<()> {
        let ScreenModel::Talk(list) = model else {
            bail!(
                "talk controller received non-talk screen model: {}",
                model.screen().as_str()
            );
        };
        let selected = selected_row(list);
        let title = selected
            .map(|row| row.title.as_str())
            .unwrap_or(&list.title);
        let icon_key = selected.map(|row| row.icon_key.as_str()).unwrap_or("talk");
        let accent = 0x00D4FF;

        self.ensure_widgets(facade)?;
        if let Some(root) = self.root {
            self.status.sync(facade, root, &list.chrome.status)?;
            self.footer
                .sync(facade, root, "talk_footer", &list.chrome.footer)?;
        }
        if let Some(card_glow) = self.card_glow {
            facade.set_accent(card_glow, accent)?;
        }
        if let Some(card_panel) = self.card_panel {
            facade.set_accent(card_panel, accent)?;
        }
        if let Some(card_label) = self.card_label {
            facade.set_icon(card_label, icon_key)?;
            facade.set_accent(card_label, 0xFFFFFF)?;
        }
        if let Some(title_label) = self.title {
            facade.set_text(title_label, title)?;
        }
        Ok(())
    }

    fn teardown(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        let root = self.root.take();
        self.status.clear();
        self.card_glow = None;
        self.card_panel = None;
        self.card_label = None;
        self.title = None;
        self.footer.clear();
        if let Some(root) = root {
            facade.destroy(root)?;
        }
        Ok(())
    }
}

fn selected_row(model: &ListScreenModel) -> Option<&crate::screens::ListRowModel> {
    model
        .rows
        .iter()
        .find(|row| row.selected)
        .or_else(|| model.rows.first())
}
