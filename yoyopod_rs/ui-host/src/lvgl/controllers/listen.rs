use anyhow::{anyhow, bail, Result};

use super::shared::{FooterLabel, StatusBarWidgets};
use crate::lvgl::{LvglFacade, ScreenController, WidgetId};
use crate::screens::{ListScreenModel, ScreenModel};

#[derive(Default)]
pub struct ListenController {
    root: Option<WidgetId>,
    status: StatusBarWidgets,
    title: Option<WidgetId>,
    subtitle: Option<WidgetId>,
    panel: Option<WidgetId>,
    footer: FooterLabel,
    row_containers: Vec<WidgetId>,
    row_icons: Vec<WidgetId>,
    row_titles: Vec<WidgetId>,
    row_subtitles: Vec<WidgetId>,
    empty_panel: Option<WidgetId>,
    empty_icon: Option<WidgetId>,
    empty_title: Option<WidgetId>,
    empty_subtitle: Option<WidgetId>,
}

impl ListenController {
    fn ensure_widgets(&mut self, facade: &mut dyn LvglFacade, row_count: usize) -> Result<()> {
        if self.root.is_none() {
            self.root = Some(facade.create_root()?);
        }
        let root = self
            .root
            .ok_or_else(|| anyhow!("listen controller missing root widget"))?;

        if self.title.is_none() {
            self.title = Some(facade.create_label(root, "listen_title")?);
        }
        if self.subtitle.is_none() {
            self.subtitle = Some(facade.create_label(root, "listen_subtitle")?);
        }
        if self.panel.is_none() {
            self.panel = Some(facade.create_container(root, "listen_panel")?);
        }
        let panel = self
            .panel
            .ok_or_else(|| anyhow!("listen controller missing panel"))?;

        while self.row_titles.len() < row_count {
            let row = facade.create_container(panel, "listen_row")?;
            self.row_containers.push(row);
            self.row_icons
                .push(facade.create_label(row, "listen_row_icon")?);
            self.row_titles
                .push(facade.create_label(row, "listen_row_title")?);
            self.row_subtitles
                .push(facade.create_label(row, "listen_row_subtitle")?);
        }
        if self.empty_panel.is_none() {
            self.empty_panel = Some(facade.create_container(root, "listen_empty_panel")?);
        }
        let empty_panel = self
            .empty_panel
            .ok_or_else(|| anyhow!("listen controller missing empty panel"))?;
        if self.empty_icon.is_none() {
            self.empty_icon = Some(facade.create_label(empty_panel, "listen_empty_icon")?);
        }
        if self.empty_title.is_none() {
            self.empty_title = Some(facade.create_label(empty_panel, "listen_empty_title")?);
        }
        if self.empty_subtitle.is_none() {
            self.empty_subtitle = Some(facade.create_label(empty_panel, "listen_empty_subtitle")?);
        }

        Ok(())
    }
}

impl ScreenController for ListenController {
    fn sync(&mut self, facade: &mut dyn LvglFacade, model: &ScreenModel) -> Result<()> {
        let ScreenModel::Listen(list) = model else {
            bail!(
                "listen controller received non-listen screen model: {}",
                model.screen().as_str()
            );
        };

        let accent = 0x00FF88;

        self.ensure_widgets(facade, 4)?;
        if let Some(root) = self.root {
            self.status.sync(facade, root, &list.chrome.status)?;
            self.footer.sync_with_accent(
                facade,
                root,
                "listen_footer",
                &list.chrome.footer,
                accent,
            )?;
        }
        if let Some(title) = self.title {
            facade.set_text(title, "Your Music")?;
        }
        if let Some(subtitle) = self.subtitle {
            facade.set_text(subtitle, "Local library")?;
        }
        let empty = list.rows.is_empty();
        if let Some(panel) = self.panel {
            facade.set_visible(panel, !empty)?;
        }
        if let Some(empty_panel) = self.empty_panel {
            facade.set_visible(empty_panel, empty)?;
        }
        if let Some(empty_icon) = self.empty_icon {
            facade.set_icon(empty_icon, "music_note")?;
            facade.set_accent(empty_icon, accent)?;
        }
        if let Some(empty_title) = self.empty_title {
            facade.set_text(empty_title, "No music items")?;
        }
        if let Some(empty_subtitle) = self.empty_subtitle {
            facade.set_text(empty_subtitle, "Add local music actions to fill this page.")?;
        }
        sync_rows(
            facade,
            list,
            accent,
            &self.row_containers,
            &self.row_icons,
            &self.row_titles,
            &self.row_subtitles,
        )
    }

    fn teardown(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        let root = self.root.take();
        self.status.clear();
        self.title = None;
        self.subtitle = None;
        self.panel = None;
        self.footer.clear();
        self.row_containers.clear();
        self.row_icons.clear();
        self.row_titles.clear();
        self.row_subtitles.clear();
        self.empty_panel = None;
        self.empty_icon = None;
        self.empty_title = None;
        self.empty_subtitle = None;
        if let Some(root) = root {
            facade.destroy(root)?;
        }
        Ok(())
    }
}

pub(super) fn sync_rows(
    facade: &mut dyn LvglFacade,
    list: &ListScreenModel,
    accent: u32,
    row_containers: &[WidgetId],
    row_icons: &[WidgetId],
    row_titles: &[WidgetId],
    row_subtitles: &[WidgetId],
) -> Result<()> {
    for index in 0..row_titles.len() {
        if let Some(row) = list.rows.get(index) {
            facade.set_visible(row_containers[index], true)?;
            facade.set_selected(row_containers[index], row.selected)?;
            facade.set_icon(row_icons[index], &row.icon_key)?;
            facade.set_accent(row_icons[index], accent)?;
            facade.set_selected(row_titles[index], row.selected)?;
            facade.set_selected(row_subtitles[index], row.selected)?;
            facade.set_text(row_titles[index], &row.title)?;
            facade.set_text(row_subtitles[index], &row.subtitle)?;
            facade.set_visible(row_subtitles[index], !row.subtitle.trim().is_empty())?;
        } else {
            facade.set_selected(row_containers[index], false)?;
            facade.set_visible(row_containers[index], false)?;
        }
    }
    Ok(())
}
