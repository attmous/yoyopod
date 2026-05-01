use anyhow::{anyhow, Result};

use crate::lvgl::{LvglFacade, WidgetId};
use crate::screens::StatusBarModel;

#[derive(Default)]
pub(crate) struct StatusBarWidgets {
    bar: Option<WidgetId>,
    network: Option<WidgetId>,
    signal: Option<WidgetId>,
    battery: Option<WidgetId>,
}

impl StatusBarWidgets {
    pub(crate) fn sync(
        &mut self,
        facade: &mut dyn LvglFacade,
        root: WidgetId,
        status: &StatusBarModel,
    ) -> Result<()> {
        self.ensure_widgets(facade, root)?;

        if let Some(network) = self.network {
            facade.set_text(network, network_text(status))?;
        }
        if let Some(signal) = self.signal {
            facade.set_text(signal, signal_text(status.signal_strength))?;
        }
        if let Some(battery) = self.battery {
            facade.set_text(battery, &battery_text(status))?;
        }

        Ok(())
    }

    fn ensure_widgets(&mut self, facade: &mut dyn LvglFacade, root: WidgetId) -> Result<()> {
        if self.bar.is_none() {
            self.bar = Some(facade.create_container(root, "status_bar")?);
        }
        let bar = self
            .bar
            .ok_or_else(|| anyhow!("status bar missing root widget"))?;

        if self.network.is_none() {
            self.network = Some(facade.create_label(bar, "status_network")?);
        }
        if self.signal.is_none() {
            self.signal = Some(facade.create_label(bar, "status_signal")?);
        }
        if self.battery.is_none() {
            self.battery = Some(facade.create_label(bar, "status_battery")?);
        }

        Ok(())
    }

    pub(crate) fn clear(&mut self) {
        *self = Self::default();
    }
}

#[derive(Default)]
pub(crate) struct FooterBar {
    bar: Option<WidgetId>,
    label: Option<WidgetId>,
}

impl FooterBar {
    pub(crate) fn sync(
        &mut self,
        facade: &mut dyn LvglFacade,
        root: WidgetId,
        label_role: &'static str,
        text: &str,
    ) -> Result<()> {
        self.ensure_widgets(facade, root, label_role)?;
        if let Some(label) = self.label {
            facade.set_text(label, text)?;
            facade.set_visible(label, !text.trim().is_empty())?;
        }
        Ok(())
    }

    fn ensure_widgets(
        &mut self,
        facade: &mut dyn LvglFacade,
        root: WidgetId,
        label_role: &'static str,
    ) -> Result<()> {
        if self.bar.is_none() {
            self.bar = Some(facade.create_container(root, "footer_bar")?);
        }
        let bar = self
            .bar
            .ok_or_else(|| anyhow!("footer bar missing root widget"))?;

        if self.label.is_none() {
            self.label = Some(facade.create_label(bar, label_role)?);
        }

        Ok(())
    }

    pub(crate) fn clear(&mut self) {
        *self = Self::default();
    }
}

#[derive(Default)]
pub(crate) struct FooterLabel {
    label: Option<WidgetId>,
}

impl FooterLabel {
    pub(crate) fn sync(
        &mut self,
        facade: &mut dyn LvglFacade,
        root: WidgetId,
        label_role: &'static str,
        text: &str,
    ) -> Result<()> {
        if self.label.is_none() {
            self.label = Some(facade.create_label(root, label_role)?);
        }
        if let Some(label) = self.label {
            facade.set_text(label, text)?;
            facade.set_visible(label, !text.trim().is_empty())?;
        }
        Ok(())
    }

    pub(crate) fn sync_with_accent(
        &mut self,
        facade: &mut dyn LvglFacade,
        root: WidgetId,
        label_role: &'static str,
        text: &str,
        accent: u32,
    ) -> Result<()> {
        self.sync(facade, root, label_role, text)?;
        if let Some(label) = self.label {
            facade.set_accent(label, accent)?;
        }
        Ok(())
    }

    pub(crate) fn clear(&mut self) {
        *self = Self::default();
    }
}

fn network_text(status: &StatusBarModel) -> &'static str {
    if !status.network_enabled {
        "OFF"
    } else if status.network_connected {
        "NET"
    } else {
        "..."
    }
}

fn signal_text(strength: i32) -> &'static str {
    match strength.clamp(0, 4) {
        0 => "----",
        1 => "|---",
        2 => "||--",
        3 => "|||-",
        _ => "||||",
    }
}

fn battery_text(status: &StatusBarModel) -> String {
    if status.charging {
        format!("{}%+", status.battery_percent.clamp(0, 100))
    } else {
        format!("{}%", status.battery_percent.clamp(0, 100))
    }
}
