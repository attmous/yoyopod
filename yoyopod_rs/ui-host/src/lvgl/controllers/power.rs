use anyhow::{anyhow, bail, Result};

use super::shared::{FooterLabel, StatusBarWidgets};
use crate::lvgl::{LvglFacade, ScreenController, WidgetId};
use crate::screens::{PowerViewModel, ScreenModel};

#[derive(Default)]
pub struct PowerController {
    root: Option<WidgetId>,
    status: StatusBarWidgets,
    icon_halo: Option<WidgetId>,
    icon: Option<WidgetId>,
    title: Option<WidgetId>,
    footer: FooterLabel,
    row_containers: Vec<WidgetId>,
    row_titles: Vec<WidgetId>,
}

impl PowerController {
    fn ensure_base_widgets(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        if self.root.is_none() {
            self.root = Some(facade.create_root()?);
        }

        let root = self
            .root
            .ok_or_else(|| anyhow!("power controller missing root widget"))?;

        if self.icon_halo.is_none() {
            self.icon_halo = Some(facade.create_container(root, "power_icon_halo")?);
        }
        let icon_halo = self
            .icon_halo
            .ok_or_else(|| anyhow!("power controller missing icon halo"))?;
        if self.icon.is_none() {
            self.icon = Some(facade.create_label(icon_halo, "power_icon")?);
        }
        if self.title.is_none() {
            self.title = Some(facade.create_label(root, "power_title")?);
        }

        Ok(())
    }

    fn ensure_row_widgets(&mut self, facade: &mut dyn LvglFacade, row_count: usize) -> Result<()> {
        let root = self
            .root
            .ok_or_else(|| anyhow!("power controller missing root widget"))?;

        while self.row_titles.len() < row_count {
            let row = facade.create_container(root, "power_row")?;
            self.row_containers.push(row);
            self.row_titles
                .push(facade.create_label(row, "power_row_title")?);
        }

        Ok(())
    }
}

impl ScreenController for PowerController {
    fn sync(&mut self, facade: &mut dyn LvglFacade, model: &ScreenModel) -> Result<()> {
        let power = power_model(model)?;

        self.ensure_base_widgets(facade)?;
        self.ensure_row_widgets(facade, 5)?;
        let accent = 0x9CA3AF;

        if let Some(root) = self.root {
            self.status.sync(facade, root, &power.chrome.status)?;
            self.footer.sync_with_accent(
                facade,
                root,
                "power_footer",
                &power.chrome.footer,
                accent,
            )?;
        }
        if let Some(icon_halo) = self.icon_halo {
            facade.set_accent(icon_halo, accent)?;
        }
        if let Some(icon) = self.icon {
            facade.set_icon(icon, "battery")?;
        }

        if let Some(title) = self.title {
            facade.set_text(title, &power.title)?;
        }

        for index in 0..self.row_titles.len() {
            if let Some(row) = power.rows.get(index) {
                facade.set_visible(self.row_containers[index], true)?;
                facade.set_text(self.row_titles[index], &row.title)?;
            } else {
                facade.set_visible(self.row_containers[index], false)?;
            }
        }

        Ok(())
    }

    fn teardown(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        let root = self.root.take();
        self.status.clear();
        self.icon_halo = None;
        self.icon = None;
        self.title = None;
        self.footer.clear();
        self.row_containers.clear();
        self.row_titles.clear();
        if let Some(root) = root {
            facade.destroy(root)?;
        }
        Ok(())
    }
}

fn power_model(model: &ScreenModel) -> Result<&PowerViewModel> {
    match model {
        ScreenModel::Power(power) => Ok(power),
        _ => bail!(
            "power controller received non-power screen model: {}",
            model.screen().as_str()
        ),
    }
}
