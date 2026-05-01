use anyhow::{anyhow, bail, Result};

use super::shared::{FooterBar, StatusBarWidgets};
use crate::lvgl::{LvglFacade, ScreenController, WidgetId};
use crate::screens::{AskViewModel, ScreenModel};

#[derive(Default)]
pub struct AskController {
    root: Option<WidgetId>,
    status: StatusBarWidgets,
    icon_glow: Option<WidgetId>,
    icon_halo: Option<WidgetId>,
    title: Option<WidgetId>,
    subtitle: Option<WidgetId>,
    footer: FooterBar,
    icon: Option<WidgetId>,
}

impl AskController {
    fn ensure_widgets(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        if self.root.is_none() {
            self.root = Some(facade.create_root()?);
        }

        let root = self
            .root
            .ok_or_else(|| anyhow!("ask controller missing root widget"))?;

        if self.icon_glow.is_none() {
            self.icon_glow = Some(facade.create_container(root, "ask_icon_glow")?);
        }
        if self.icon_halo.is_none() {
            self.icon_halo = Some(facade.create_container(root, "ask_icon_halo")?);
        }
        let icon_halo = self
            .icon_halo
            .ok_or_else(|| anyhow!("ask controller missing icon halo"))?;
        if self.icon.is_none() {
            self.icon = Some(facade.create_label(icon_halo, "ask_icon")?);
        }
        if self.title.is_none() {
            self.title = Some(facade.create_label(root, "ask_title")?);
        }
        if self.subtitle.is_none() {
            self.subtitle = Some(facade.create_label(root, "ask_subtitle")?);
        }

        Ok(())
    }
}

impl ScreenController for AskController {
    fn sync(&mut self, facade: &mut dyn LvglFacade, model: &ScreenModel) -> Result<()> {
        let ask = ask_model(model)?;

        self.ensure_widgets(facade)?;

        let accent = if matches!(model, ScreenModel::VoiceNote(_)) {
            0x00D4FF
        } else {
            0xFFD000
        };
        if let Some(root) = self.root {
            self.status.sync(facade, root, &ask.chrome.status)?;
            self.footer
                .sync(facade, root, "ask_footer", &ask.chrome.footer)?;
        }
        if let Some(icon_halo) = self.icon_halo {
            facade.set_accent(icon_halo, accent)?;
        }
        if let Some(icon_glow) = self.icon_glow {
            facade.set_accent(icon_glow, accent)?;
        }
        if let Some(title) = self.title {
            facade.set_text(title, &ask.title)?;
        }
        if let Some(subtitle) = self.subtitle {
            facade.set_text(subtitle, &ask.subtitle)?;
        }
        if let Some(icon) = self.icon {
            facade.set_icon(icon, &ask.icon_key)?;
            facade.set_accent(icon, accent)?;
        }

        Ok(())
    }

    fn teardown(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        let root = self.root.take();
        self.status.clear();
        self.icon_glow = None;
        self.icon_halo = None;
        self.title = None;
        self.subtitle = None;
        self.footer.clear();
        self.icon = None;
        if let Some(root) = root {
            facade.destroy(root)?;
        }
        Ok(())
    }
}

fn ask_model(model: &ScreenModel) -> Result<&AskViewModel> {
    match model {
        ScreenModel::Ask(ask) | ScreenModel::VoiceNote(ask) => Ok(ask),
        _ => bail!(
            "ask controller received non-ask screen model: {}",
            model.screen().as_str()
        ),
    }
}
