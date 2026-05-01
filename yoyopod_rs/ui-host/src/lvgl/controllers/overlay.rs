use anyhow::{anyhow, bail, Result};

use super::shared::{FooterBar, StatusBarWidgets};
use crate::lvgl::{LvglFacade, ScreenController, WidgetId};
use crate::screens::{OverlayViewModel, ScreenModel};

#[derive(Default)]
pub struct OverlayController {
    root: Option<WidgetId>,
    status: StatusBarWidgets,
    title: Option<WidgetId>,
    subtitle: Option<WidgetId>,
    footer: FooterBar,
}

impl OverlayController {
    fn ensure_widgets(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        if self.root.is_none() {
            self.root = Some(facade.create_root()?);
        }

        let root = self
            .root
            .ok_or_else(|| anyhow!("overlay controller missing root widget"))?;

        if self.title.is_none() {
            self.title = Some(facade.create_label(root, "overlay_title")?);
        }
        if self.subtitle.is_none() {
            self.subtitle = Some(facade.create_label(root, "overlay_subtitle")?);
        }

        Ok(())
    }
}

impl ScreenController for OverlayController {
    fn sync(&mut self, facade: &mut dyn LvglFacade, model: &ScreenModel) -> Result<()> {
        let overlay = overlay_model(model)?;

        self.ensure_widgets(facade)?;
        if let Some(root) = self.root {
            self.status.sync(facade, root, &overlay.chrome.status)?;
            self.footer
                .sync(facade, root, "overlay_footer", &overlay.chrome.footer)?;
        }

        if let Some(title) = self.title {
            facade.set_text(title, &overlay.title)?;
        }
        if let Some(subtitle) = self.subtitle {
            facade.set_text(subtitle, &overlay.subtitle)?;
        }

        Ok(())
    }

    fn teardown(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        let root = self.root.take();
        self.status.clear();
        self.title = None;
        self.subtitle = None;
        self.footer.clear();
        if let Some(root) = root {
            facade.destroy(root)?;
        }
        Ok(())
    }
}

fn overlay_model(model: &ScreenModel) -> Result<&OverlayViewModel> {
    match model {
        ScreenModel::Loading(overlay) | ScreenModel::Error(overlay) => Ok(overlay),
        _ => bail!(
            "overlay controller received non-overlay screen model: {}",
            model.screen().as_str()
        ),
    }
}
