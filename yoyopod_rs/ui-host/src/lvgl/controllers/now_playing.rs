use anyhow::{anyhow, bail, Result};

use super::shared::{FooterLabel, StatusBarWidgets};
use crate::lvgl::{LvglFacade, ScreenController, WidgetId};
use crate::screens::{NowPlayingViewModel, ScreenModel};

#[derive(Default)]
pub struct NowPlayingController {
    root: Option<WidgetId>,
    status: StatusBarWidgets,
    panel: Option<WidgetId>,
    icon_halo: Option<WidgetId>,
    icon_label: Option<WidgetId>,
    state_chip: Option<WidgetId>,
    state_label: Option<WidgetId>,
    title: Option<WidgetId>,
    artist: Option<WidgetId>,
    progress_track: Option<WidgetId>,
    progress_fill: Option<WidgetId>,
    footer: FooterLabel,
}

impl NowPlayingController {
    fn ensure_widgets(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        if self.root.is_none() {
            self.root = Some(facade.create_root()?);
        }

        let root = self
            .root
            .ok_or_else(|| anyhow!("now-playing controller missing root widget"))?;

        if self.panel.is_none() {
            self.panel = Some(facade.create_container(root, "now_playing_panel")?);
        }
        let panel = self
            .panel
            .ok_or_else(|| anyhow!("now-playing controller missing panel"))?;
        if self.icon_halo.is_none() {
            self.icon_halo = Some(facade.create_container(panel, "now_playing_icon_halo")?);
        }
        let icon_halo = self
            .icon_halo
            .ok_or_else(|| anyhow!("now-playing controller missing icon halo"))?;
        if self.icon_label.is_none() {
            self.icon_label = Some(facade.create_label(icon_halo, "now_playing_icon_label")?);
        }
        if self.state_chip.is_none() {
            self.state_chip = Some(facade.create_container(panel, "now_playing_state_chip")?);
        }
        let state_chip = self
            .state_chip
            .ok_or_else(|| anyhow!("now-playing controller missing state chip"))?;
        if self.state_label.is_none() {
            self.state_label = Some(facade.create_label(state_chip, "now_playing_state_label")?);
        }
        if self.title.is_none() {
            self.title = Some(facade.create_label(panel, "now_playing_title")?);
        }
        if self.artist.is_none() {
            self.artist = Some(facade.create_label(panel, "now_playing_artist")?);
        }
        if self.progress_track.is_none() {
            self.progress_track =
                Some(facade.create_container(panel, "now_playing_progress_track")?);
        }
        let progress_track = self
            .progress_track
            .ok_or_else(|| anyhow!("now-playing controller missing progress track"))?;
        if self.progress_fill.is_none() {
            self.progress_fill =
                Some(facade.create_container(progress_track, "now_playing_progress_fill")?);
        }

        Ok(())
    }
}

impl ScreenController for NowPlayingController {
    fn sync(&mut self, facade: &mut dyn LvglFacade, model: &ScreenModel) -> Result<()> {
        let now_playing = now_playing_model(model)?;
        let progress_value = now_playing.progress_permille.clamp(0, 1000);

        self.ensure_widgets(facade)?;
        let accent = 0x00FF88;

        if let Some(root) = self.root {
            self.status.sync(facade, root, &now_playing.chrome.status)?;
            self.footer.sync_with_accent(
                facade,
                root,
                "now_playing_footer",
                &now_playing.chrome.footer,
                accent,
            )?;
        }
        if let Some(icon_halo) = self.icon_halo {
            facade.set_accent(icon_halo, accent)?;
        }
        if let Some(icon_label) = self.icon_label {
            facade.set_icon(icon_label, "music_note")?;
            facade.set_accent(icon_label, accent)?;
        }
        if let Some(state_chip) = self.state_chip {
            facade.set_accent(state_chip, accent)?;
        }
        if let Some(state_label) = self.state_label {
            facade.set_text(state_label, &now_playing.state_text)?;
            facade.set_accent(state_label, accent)?;
        }

        if let Some(title) = self.title {
            facade.set_text(title, &now_playing.title)?;
        }
        if let Some(artist) = self.artist {
            facade.set_text(artist, &now_playing.artist)?;
        }
        if let Some(progress_fill) = self.progress_fill {
            facade.set_progress(progress_fill, progress_value)?;
            facade.set_accent(progress_fill, accent)?;
        }

        Ok(())
    }

    fn teardown(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        let root = self.root.take();
        self.status.clear();
        self.panel = None;
        self.icon_halo = None;
        self.icon_label = None;
        self.state_chip = None;
        self.state_label = None;
        self.title = None;
        self.artist = None;
        self.progress_track = None;
        self.progress_fill = None;
        self.footer.clear();
        if let Some(root) = root {
            facade.destroy(root)?;
        }
        Ok(())
    }
}

fn now_playing_model(model: &ScreenModel) -> Result<&NowPlayingViewModel> {
    match model {
        ScreenModel::NowPlaying(now_playing) => Ok(now_playing),
        _ => bail!(
            "now-playing controller received non-now-playing screen model: {}",
            model.screen().as_str()
        ),
    }
}
