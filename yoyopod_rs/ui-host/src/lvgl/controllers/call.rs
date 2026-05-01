use anyhow::{anyhow, bail, Result};

use super::shared::{FooterBar, StatusBarWidgets};
use crate::lvgl::{LvglFacade, ScreenController, WidgetId};
use crate::screens::{CallViewModel, ScreenModel};

#[derive(Default)]
pub struct CallController {
    root: Option<WidgetId>,
    status: StatusBarWidgets,
    panel: Option<WidgetId>,
    title: Option<WidgetId>,
    subtitle: Option<WidgetId>,
    detail: Option<WidgetId>,
    footer: FooterBar,
    state_icon: Option<WidgetId>,
    mute_badge: Option<WidgetId>,
}

impl CallController {
    fn ensure_widgets(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        if self.root.is_none() {
            self.root = Some(facade.create_root()?);
        }

        let root = self
            .root
            .ok_or_else(|| anyhow!("call controller missing root widget"))?;

        if self.panel.is_none() {
            self.panel = Some(facade.create_container(root, "call_panel")?);
        }
        let panel = self
            .panel
            .ok_or_else(|| anyhow!("call controller missing panel widget"))?;
        if self.state_icon.is_none() {
            self.state_icon = Some(facade.create_label(panel, "call_state_icon")?);
        }
        if self.title.is_none() {
            self.title = Some(facade.create_label(root, "call_title")?);
        }
        if self.subtitle.is_none() {
            self.subtitle = Some(facade.create_label(root, "call_subtitle")?);
        }
        if self.detail.is_none() {
            self.detail = Some(facade.create_label(root, "call_detail")?);
        }
        if self.mute_badge.is_none() {
            self.mute_badge = Some(facade.create_label(root, "call_mute_badge")?);
        }

        Ok(())
    }
}

impl ScreenController for CallController {
    fn sync(&mut self, facade: &mut dyn LvglFacade, model: &ScreenModel) -> Result<()> {
        let call = call_model(model)?;

        self.ensure_widgets(facade)?;
        let accent = 0x00D4FF;

        if let Some(root) = self.root {
            self.status.sync(facade, root, &call.chrome.status)?;
            self.footer
                .sync(facade, root, "call_footer", &call.chrome.footer)?;
        }
        if let Some(panel) = self.panel {
            facade.set_accent(panel, accent)?;
        }

        if let Some(title) = self.title {
            facade.set_text(title, &call.title)?;
        }
        if let Some(subtitle) = self.subtitle {
            facade.set_text(subtitle, &call.subtitle)?;
        }
        if let Some(detail) = self.detail {
            facade.set_text(detail, &call.detail)?;
        }
        if let Some(state_icon) = self.state_icon {
            facade.set_icon(state_icon, call_icon_key(model))?;
            facade.set_accent(state_icon, accent)?;
        }
        if let Some(mute_badge) = self.mute_badge {
            facade.set_text(mute_badge, "Muted")?;
            facade.set_visible(mute_badge, call.muted)?;
        }

        Ok(())
    }

    fn teardown(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        let root = self.root.take();
        self.status.clear();
        self.panel = None;
        self.title = None;
        self.subtitle = None;
        self.detail = None;
        self.footer.clear();
        self.state_icon = None;
        self.mute_badge = None;
        if let Some(root) = root {
            facade.destroy(root)?;
        }
        Ok(())
    }
}

fn call_model(model: &ScreenModel) -> Result<&CallViewModel> {
    match model {
        ScreenModel::IncomingCall(call)
        | ScreenModel::OutgoingCall(call)
        | ScreenModel::InCall(call) => Ok(call),
        _ => bail!(
            "call controller received non-call screen model: {}",
            model.screen().as_str()
        ),
    }
}

fn call_icon_key(model: &ScreenModel) -> &'static str {
    match model {
        ScreenModel::IncomingCall(_) => "call_incoming",
        ScreenModel::OutgoingCall(_) => "call_outgoing",
        ScreenModel::InCall(_) => "call_active",
        _ => "call",
    }
}
