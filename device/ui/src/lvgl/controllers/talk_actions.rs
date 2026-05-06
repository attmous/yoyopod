use anyhow::{anyhow, bail, Result};

use super::shared::{FooterBar, StatusBarWidgets};
use crate::lvgl::{LvglFacade, ScreenController, WidgetId};
use crate::screens::{ScreenModel, TalkActionsViewModel};

const ACCENT: u32 = 0x00D4FF;
const BACKGROUND: u32 = 0x2A2D35;
const SUCCESS: u32 = 0x3DDD53;
const WARNING: u32 = 0xFFD549;
const ERROR: u32 = 0xFF675D;
const NEUTRAL: u32 = 0x9CA3AF;

#[derive(Default)]
pub struct TalkActionsController {
    root: Option<WidgetId>,
    status: StatusBarWidgets,
    header_box: Option<WidgetId>,
    header_label: Option<WidgetId>,
    header_name: Option<WidgetId>,
    buttons: Vec<WidgetId>,
    button_labels: Vec<WidgetId>,
    title_label: Option<WidgetId>,
    status_label: Option<WidgetId>,
    dots: Vec<WidgetId>,
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
        while self.buttons.len() < 3 {
            let button = facade.create_container(root, "talk_actions_primary_button")?;
            self.buttons.push(button);
            self.button_labels
                .push(facade.create_label(button, "talk_actions_button_label")?);
        }
        if self.title_label.is_none() {
            self.title_label = Some(facade.create_label(root, "talk_actions_title_label")?);
        }
        if self.status_label.is_none() {
            self.status_label = Some(facade.create_label(root, "talk_actions_status_label")?);
        }
        while self.dots.len() < 3 {
            self.dots.push(facade.create_container(root, "talk_dot")?);
        }
        Ok(())
    }
}

impl ScreenController for TalkActionsController {
    fn sync(&mut self, facade: &mut dyn LvglFacade, model: &ScreenModel) -> Result<()> {
        let actions = talk_actions_model(model)?;

        self.ensure_widgets(facade)?;
        if let Some(root) = self.root {
            self.status
                .sync(facade, root, &actions.chrome.status, true)?;
            self.footer
                .sync(facade, root, "talk_actions_footer", &actions.chrome.footer)?;
        }
        if let Some(header_box) = self.header_box {
            facade.set_accent(header_box, ACCENT)?;
        }
        if let Some(header_label) = self.header_label {
            facade.set_text(header_label, monogram(&actions.contact_name).as_str())?;
            facade.set_accent(header_label, ACCENT)?;
        }
        if let Some(header_name) = self.header_name {
            facade.set_text(header_name, &actions.contact_name)?;
        }

        let action_count = actions.buttons.len().min(3);
        let selected_index = actions.selected_index.min(action_count.saturating_sub(1));
        if actions.layout_kind == 1 {
            self.sync_primary_layout(facade, actions, action_count)?;
        } else {
            self.sync_action_row(facade, actions, action_count, selected_index)?;
        }
        Ok(())
    }

    fn teardown(&mut self, facade: &mut dyn LvglFacade) -> Result<()> {
        let root = self.root.take();
        self.status.clear();
        self.header_box = None;
        self.header_label = None;
        self.header_name = None;
        self.buttons.clear();
        self.button_labels.clear();
        self.title_label = None;
        self.status_label = None;
        self.dots.clear();
        self.footer.clear();
        if let Some(root) = root {
            facade.destroy(root)?;
        }
        Ok(())
    }
}

impl TalkActionsController {
    fn sync_primary_layout(
        &self,
        facade: &mut dyn LvglFacade,
        model: &TalkActionsViewModel,
        action_count: usize,
    ) -> Result<()> {
        if let Some(title_label) = self.title_label {
            facade.set_visible(title_label, false)?;
        }
        for dot in &self.dots {
            facade.set_visible(*dot, false)?;
        }

        for index in 0..self.buttons.len() {
            let visible = index == 0 && action_count > 0;
            facade.set_visible(self.buttons[index], visible)?;
            if !visible {
                continue;
            }
            let color = color_for_kind(model.buttons[0].color_kind);
            facade.set_geometry(self.buttons[index], 76, 126, 88, 88)?;
            facade.set_variant(self.buttons[index], "talk_action_primary", color)?;
            facade.set_geometry(self.button_labels[index], 24, 32, 40, 24)?;
            facade.set_icon(self.button_labels[index], &model.buttons[0].icon_key)?;
            facade.set_variant(self.button_labels[index], "talk_action_primary", color)?;
        }

        if let Some(status_label) = self.status_label {
            facade.set_geometry(status_label, 30, 220, 180, 16)?;
            facade.set_visible(status_label, true)?;
            facade.set_text(status_label, &model.status)?;
            facade.set_variant(
                status_label,
                "talk_action_status",
                color_for_kind(model.status_kind),
            )?;
        }
        Ok(())
    }

    fn sync_action_row(
        &self,
        facade: &mut dyn LvglFacade,
        model: &TalkActionsViewModel,
        action_count: usize,
        selected_index: usize,
    ) -> Result<()> {
        if let Some(status_label) = self.status_label {
            facade.set_visible(status_label, false)?;
        }

        let diameter = if model.button_size_kind == 1 { 64 } else { 56 };
        let gap = if model.button_size_kind == 1 { 16 } else { 12 };
        let center_y = if model.button_size_kind == 1 {
            154
        } else {
            156
        };
        let row_width =
            (action_count as i32 * diameter) + (action_count.saturating_sub(1) as i32 * gap);
        let start_x = 120 - (row_width / 2);
        let title_y = center_y + (diameter / 2) + 16;

        for index in 0..self.buttons.len() {
            if index >= action_count {
                facade.set_visible(self.buttons[index], false)?;
                continue;
            }
            let selected = index == selected_index;
            let color = color_for_kind(model.buttons[index].color_kind);
            facade.set_visible(self.buttons[index], true)?;
            facade.set_geometry(
                self.buttons[index],
                start_x + (index as i32 * (diameter + gap)),
                center_y - (diameter / 2),
                diameter,
                diameter,
            )?;
            facade.set_variant(
                self.buttons[index],
                if selected {
                    "talk_action_selected"
                } else {
                    "talk_action_unselected"
                },
                color,
            )?;
            let label_xy = (diameter - 40) / 2;
            facade.set_geometry(self.button_labels[index], label_xy, label_xy + 1, 40, 24)?;
            facade.set_icon(self.button_labels[index], &model.buttons[index].icon_key)?;
            facade.set_variant(
                self.button_labels[index],
                if selected {
                    "talk_action_selected"
                } else {
                    "talk_action_unselected"
                },
                color,
            )?;
        }

        if let Some(title_label) = self.title_label {
            facade.set_geometry(title_label, 30, title_y, 180, 22)?;
            facade.set_visible(title_label, true)?;
            facade.set_text(title_label, &model.title)?;
        }

        for (index, dot) in self.dots.iter().copied().enumerate() {
            if index >= action_count {
                facade.set_visible(dot, false)?;
                continue;
            }
            let selected = index == selected_index;
            let size = if selected { 8 } else { 6 };
            facade.set_visible(dot, true)?;
            facade.set_geometry(
                dot,
                120 - ((action_count as i32 * 14) / 2) + (index as i32 * 14),
                title_y + 30,
                size,
                size,
            )?;
            facade.set_selected(dot, selected)?;
            facade.set_accent(
                dot,
                if selected {
                    ACCENT
                } else {
                    mix_u24(ACCENT, BACKGROUND, 68)
                },
            )?;
        }
        Ok(())
    }
}

fn talk_actions_model(model: &ScreenModel) -> Result<&TalkActionsViewModel> {
    match model {
        ScreenModel::TalkContact(actions) | ScreenModel::VoiceNote(actions) => Ok(actions),
        _ => bail!(
            "talk-actions controller received non-talk-action screen model: {}",
            model.screen().as_str()
        ),
    }
}

fn color_for_kind(kind: i32) -> u32 {
    match kind {
        1 => SUCCESS,
        2 => WARNING,
        3 => ERROR,
        4 => NEUTRAL,
        _ => ACCENT,
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

fn mix_u24(primary_rgb: u32, secondary_rgb: u32, secondary_ratio_percent: u8) -> u32 {
    let secondary_ratio = u32::from(secondary_ratio_percent.min(100));
    let primary_ratio = 100 - secondary_ratio;
    let red = ((((primary_rgb >> 16) & 0xFF) * primary_ratio
        + ((secondary_rgb >> 16) & 0xFF) * secondary_ratio)
        / 100)
        & 0xFF;
    let green = ((((primary_rgb >> 8) & 0xFF) * primary_ratio
        + ((secondary_rgb >> 8) & 0xFF) * secondary_ratio)
        / 100)
        & 0xFF;
    let blue = (((primary_rgb & 0xFF) * primary_ratio + (secondary_rgb & 0xFF) * secondary_ratio)
        / 100)
        & 0xFF;
    (red << 16) | (green << 8) | blue
}
