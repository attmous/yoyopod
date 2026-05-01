use anyhow::{anyhow, bail, Result};

use super::shared::{FooterBar, StatusBarWidgets};
use crate::lvgl::{LvglFacade, ScreenController, WidgetId};
use crate::screens::ScreenModel;

#[derive(Default)]
pub struct TalkActionsController {
    root: Option<WidgetId>,
    status: StatusBarWidgets,
    header_box: Option<WidgetId>,
    header_label: Option<WidgetId>,
    header_name: Option<WidgetId>,
    button: Option<WidgetId>,
    button_label: Option<WidgetId>,
    status_label: Option<WidgetId>,
    footer: FooterBar,
}

impl TalkActionsController {
    fn ensure_widgets(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        if self.root.is_none() {
            self.root = Some(facade.create_root()?);
        }
        let root = self
            .root
            .ok_or_else(|| anyhow!("talk-actions controller missing root widget"))?;

        if self.header_box.is_none() {
            self.header_box = Some(facade.create_container(root, "talk_actions_header_box")?);
        }
        let header_box = self
            .header_box
            .ok_or_else(|| anyhow!("talk-actions controller missing header"))?;
        if self.header_label.is_none() {
            self.header_label = Some(facade.create_label(header_box, "talk_actions_header_label")?);
        }
        if self.header_name.is_none() {
            self.header_name = Some(facade.create_label(root, "talk_actions_header_name")?);
        }
        if self.button.is_none() {
            self.button = Some(facade.create_container(root, "talk_actions_primary_button")?);
        }
        let button = self
            .button
            .ok_or_else(|| anyhow!("talk-actions controller missing button"))?;
        if self.button_label.is_none() {
            self.button_label = Some(facade.create_label(button, "talk_actions_button_label")?);
        }
        if self.status_label.is_none() {
            self.status_label = Some(facade.create_label(root, "talk_actions_status_label")?);
        }
        Ok(())
    }
}

impl ScreenController for TalkActionsController {
    fn sync(&mut self, facade: &mut dyn LvglFacade, model: &ScreenModel) -> Result<()> {
        let ScreenModel::VoiceNote(voice_note) = model else {
            bail!(
                "talk-actions controller received non-voice-note screen model: {}",
                model.screen().as_str()
            );
        };
        let accent = 0x00D4FF;

        self.ensure_widgets(facade)?;
        if let Some(root) = self.root {
            self.status.sync(facade, root, &voice_note.chrome.status)?;
            self.footer.sync(
                facade,
                root,
                "talk_actions_footer",
                &voice_note.chrome.footer,
            )?;
        }
        if let Some(header_box) = self.header_box {
            facade.set_accent(header_box, accent)?;
        }
        if let Some(header_label) = self.header_label {
            facade.set_text(header_label, monogram(&voice_note.title).as_str())?;
            facade.set_accent(header_label, accent)?;
        }
        if let Some(header_name) = self.header_name {
            facade.set_text(header_name, &voice_note.title)?;
        }
        if let Some(button) = self.button {
            facade.set_accent(button, accent)?;
        }
        if let Some(button_label) = self.button_label {
            facade.set_icon(button_label, &voice_note.icon_key)?;
            facade.set_accent(button_label, accent)?;
        }
        if let Some(status_label) = self.status_label {
            facade.set_text(status_label, &voice_note.subtitle)?;
            facade.set_accent(status_label, accent)?;
        }
        Ok(())
    }

    fn teardown(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        let root = self.root.take();
        self.status.clear();
        self.header_box = None;
        self.header_label = None;
        self.header_name = None;
        self.button = None;
        self.button_label = None;
        self.status_label = None;
        self.footer.clear();
        if let Some(root) = root {
            facade.destroy(root)?;
        }
        Ok(())
    }
}

fn monogram(text: &str) -> String {
    let words = text.split_whitespace().collect::<Vec<_>>();
    if words.is_empty() {
        return "T".to_string();
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
        "T".to_string()
    } else {
        result
    }
}
