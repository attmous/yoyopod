use anyhow::{anyhow, bail, Result};

use super::shared::{FooterBar, StatusBarWidgets};
use crate::lvgl::{LvglFacade, ScreenController, WidgetId};
use crate::screens::{CallViewModel, ScreenModel};

#[derive(Default)]
pub struct CallController {
    root: Option<WidgetId>,
    status: StatusBarWidgets,
    icon_halo: Option<WidgetId>,
    panel: Option<WidgetId>,
    icon_label: Option<WidgetId>,
    title: Option<WidgetId>,
    state_chip: Option<WidgetId>,
    state_label: Option<WidgetId>,
    footer: FooterBar,
    mute_badge: Option<WidgetId>,
    mute_label: Option<WidgetId>,
}

impl CallController {
    fn ensure_widgets(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        if self.root.is_none() {
            self.root = Some(facade.create_root()?);
        }

        let root = self
            .root
            .ok_or_else(|| anyhow!("call controller missing root widget"))?;

        if self.icon_halo.is_none() {
            self.icon_halo = Some(facade.create_container(root, "call_icon_halo")?);
        }
        if self.panel.is_none() {
            self.panel = Some(facade.create_container(root, "call_panel")?);
        }
        let panel = self
            .panel
            .ok_or_else(|| anyhow!("call controller missing panel widget"))?;
        if self.icon_label.is_none() {
            self.icon_label = Some(facade.create_label(panel, "call_state_icon")?);
        }
        if self.title.is_none() {
            self.title = Some(facade.create_label(root, "call_title")?);
        }
        if self.state_chip.is_none() {
            self.state_chip = Some(facade.create_container(root, "call_state_chip")?);
        }
        let state_chip = self
            .state_chip
            .ok_or_else(|| anyhow!("call controller missing state chip"))?;
        if self.state_label.is_none() {
            self.state_label = Some(facade.create_label(state_chip, "call_state_label")?);
        }
        if self.mute_badge.is_none() {
            self.mute_badge = Some(facade.create_container(root, "call_mute_badge")?);
        }
        let mute_badge = self
            .mute_badge
            .ok_or_else(|| anyhow!("call controller missing mute badge"))?;
        if self.mute_label.is_none() {
            self.mute_label = Some(facade.create_label(mute_badge, "call_mute_label")?);
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
        if let Some(icon_halo) = self.icon_halo {
            facade.set_accent(icon_halo, accent)?;
        }
        if let Some(panel) = self.panel {
            facade.set_accent(panel, call_panel_accent(model))?;
        }

        if let Some(title) = self.title {
            facade.set_text(title, &call.title)?;
        }
        if let Some(icon_label) = self.icon_label {
            facade.set_text(icon_label, &monogram(&call.title))?;
            facade.set_accent(icon_label, call_icon_accent(model))?;
        }
        if let Some(state_chip) = self.state_chip {
            facade.set_accent(state_chip, call_state_accent(model))?;
        }
        if let Some(state_label) = self.state_label {
            let state_text = call_state_text(model, call);
            facade.set_text(state_label, &state_text)?;
            facade.set_accent(state_label, call_state_accent(model))?;
        }
        if let Some(mute_badge) = self.mute_badge {
            facade.set_visible(mute_badge, call.muted)?;
        }
        if let Some(mute_label) = self.mute_label {
            facade.set_text(mute_label, "MUTED")?;
        }

        Ok(())
    }

    fn teardown(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        let root = self.root.take();
        self.status.clear();
        self.icon_halo = None;
        self.panel = None;
        self.icon_label = None;
        self.title = None;
        self.state_chip = None;
        self.state_label = None;
        self.footer.clear();
        self.mute_badge = None;
        self.mute_label = None;
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

fn call_state_text(model: &ScreenModel, call: &CallViewModel) -> String {
    match model {
        ScreenModel::IncomingCall(_) => "INCOMING CALL".to_string(),
        ScreenModel::OutgoingCall(_) => "CALLING...".to_string(),
        ScreenModel::InCall(_) => {
            if call.subtitle.contains("IN CALL") {
                call.subtitle.clone()
            } else if call.subtitle.trim().is_empty() {
                "IN CALL".to_string()
            } else {
                format!("IN CALL | {}", call.subtitle)
            }
        }
        _ => String::new(),
    }
}

fn call_state_accent(model: &ScreenModel) -> u32 {
    match model {
        ScreenModel::InCall(_) => 0x3DDD53,
        _ => 0x00D4FF,
    }
}

fn call_panel_accent(model: &ScreenModel) -> u32 {
    match model {
        ScreenModel::OutgoingCall(_) => 0x214E5D,
        _ => 0x00D4FF,
    }
}

fn call_icon_accent(model: &ScreenModel) -> u32 {
    match model {
        ScreenModel::OutgoingCall(_) => 0x00D4FF,
        _ => 0xFFFFFF,
    }
}

fn monogram(text: &str) -> String {
    let words = text.split_whitespace().collect::<Vec<_>>();
    if words.is_empty() {
        return "?".to_string();
    }

    let mut result = String::new();
    if words.len() > 1 {
        for word in words.iter().take(2) {
            if let Some(letter) = word.chars().next() {
                result.push(letter.to_ascii_uppercase());
            }
        }
    } else {
        for letter in words[0].chars().take(2) {
            result.push(letter.to_ascii_uppercase());
        }
    }

    if result.is_empty() {
        "?".to_string()
    } else {
        result
    }
}
