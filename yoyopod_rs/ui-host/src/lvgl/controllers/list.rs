use anyhow::{anyhow, bail, Result};

use super::shared::{FooterBar, StatusBarWidgets};
use crate::lvgl::{LvglFacade, ScreenController, WidgetId};
use crate::screens::{ListScreenModel, ScreenModel};

#[derive(Default)]
pub struct ListController {
    root: Option<WidgetId>,
    status: StatusBarWidgets,
    title: Option<WidgetId>,
    subtitle: Option<WidgetId>,
    footer: FooterBar,
    row_containers: Vec<WidgetId>,
    row_icons: Vec<WidgetId>,
    row_titles: Vec<WidgetId>,
    row_subtitles: Vec<WidgetId>,
}

impl ListController {
    fn ensure_base_widgets(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        if self.root.is_none() {
            self.root = Some(facade.create_root()?);
        }

        let root = self
            .root
            .ok_or_else(|| anyhow!("list controller missing root widget"))?;

        if self.title.is_none() {
            self.title = Some(facade.create_label(root, "list_title")?);
        }
        if self.subtitle.is_none() {
            self.subtitle = Some(facade.create_label(root, "list_subtitle")?);
        }

        Ok(())
    }

    fn ensure_row_widgets(&mut self, facade: &mut dyn LvglFacade, row_count: usize) -> Result<()> {
        let root = self
            .root
            .ok_or_else(|| anyhow!("list controller missing root widget"))?;

        while self.row_titles.len() < row_count {
            let row = facade.create_container(root, "list_row")?;
            self.row_containers.push(row);
            self.row_icons
                .push(facade.create_label(row, "list_row_icon")?);
            self.row_titles
                .push(facade.create_label(row, "list_row_title")?);
            self.row_subtitles
                .push(facade.create_label(row, "list_row_subtitle")?);
        }

        Ok(())
    }
}

impl ScreenController for ListController {
    fn sync(&mut self, facade: &mut dyn LvglFacade, model: &ScreenModel) -> Result<()> {
        let list = list_model(model)?;

        self.ensure_base_widgets(facade)?;
        self.ensure_row_widgets(facade, list.rows.len())?;

        if let Some(title) = self.title {
            facade.set_text(title, &list.title)?;
        }
        if let Some(subtitle) = self.subtitle {
            facade.set_text(subtitle, &list.subtitle)?;
        }
        if let Some(root) = self.root {
            self.status.sync(facade, root, &list.chrome.status)?;
            self.footer
                .sync(facade, root, "list_footer", &list.chrome.footer)?;
        }

        let accent = accent_for_list(list);
        for index in 0..self.row_titles.len() {
            if let Some(row) = list.rows.get(index) {
                facade.set_visible(self.row_containers[index], true)?;
                facade.set_selected(self.row_containers[index], row.selected)?;
                facade.set_accent(self.row_containers[index], accent)?;
                facade.set_icon(self.row_icons[index], &row.icon_key)?;
                facade.set_accent(self.row_icons[index], accent)?;
                facade.set_text(self.row_titles[index], &row.title)?;
                facade.set_text(self.row_subtitles[index], &row.subtitle)?;
            } else {
                facade.set_selected(self.row_containers[index], false)?;
                facade.set_visible(self.row_containers[index], false)?;
            }
        }

        Ok(())
    }

    fn teardown(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        let root = self.root.take();
        self.status.clear();
        self.title = None;
        self.subtitle = None;
        self.footer.clear();
        self.row_containers.clear();
        self.row_icons.clear();
        self.row_titles.clear();
        self.row_subtitles.clear();
        if let Some(root) = root {
            facade.destroy(root)?;
        }
        Ok(())
    }
}

fn list_model(model: &ScreenModel) -> Result<&ListScreenModel> {
    match model {
        ScreenModel::Listen(list)
        | ScreenModel::Playlists(list)
        | ScreenModel::RecentTracks(list)
        | ScreenModel::Talk(list)
        | ScreenModel::Contacts(list)
        | ScreenModel::CallHistory(list) => Ok(list),
        _ => bail!(
            "list controller received non-list screen model: {}",
            model.screen().as_str()
        ),
    }
}

fn accent_for_list(model: &ListScreenModel) -> u32 {
    match model.title.to_ascii_lowercase().as_str() {
        "talk" | "contacts" | "history" | "recents" => 0x00D4FF,
        _ => 0x00FF88,
    }
}
