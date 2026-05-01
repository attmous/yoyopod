use anyhow::{anyhow, Result};
use time::OffsetDateTime;

use crate::lvgl::{LvglFacade, WidgetId};
use crate::screens::StatusBarModel;

const LV_SYMBOL_WIFI: &str = "\u{f1eb}";
const SIGNAL_ACTIVE_RGB: u32 = 0x3DDD53;
const SIGNAL_INACTIVE_RGB: u32 = 0x3C3F46;
const STATUS_MUTED_RGB: u32 = 0xB4B7BE;
const STATUS_INK_RGB: u32 = 0xFFFFFF;
const STATUS_ERROR_RGB: u32 = 0xFF675D;
const STATUS_SIGNAL_ROLES: [&str; 4] = [
    "status_signal_bar_0",
    "status_signal_bar_1",
    "status_signal_bar_2",
    "status_signal_bar_3",
];

#[derive(Default)]
pub(crate) struct StatusBarWidgets {
    bar: Option<WidgetId>,
    signal_bars: Vec<WidgetId>,
    wifi: Option<WidgetId>,
    gps_ring: Option<WidgetId>,
    gps_center: Option<WidgetId>,
    gps_tail: Option<WidgetId>,
    voip_left: Option<WidgetId>,
    voip_after_gps: Option<WidgetId>,
    time: Option<WidgetId>,
    battery_outline: Option<WidgetId>,
    battery_fill: Option<WidgetId>,
    battery_tip: Option<WidgetId>,
    battery_label: Option<WidgetId>,
}

impl StatusBarWidgets {
    pub(crate) fn sync(
        &mut self,
        facade: &mut dyn LvglFacade,
        root: WidgetId,
        status: &StatusBarModel,
        show_time: bool,
    ) -> Result<()> {
        self.ensure_widgets(facade, root)?;

        let cellular_connected =
            status.network_connected && status.connection_type.eq_ignore_ascii_case("4g");
        let wifi_connected =
            status.network_connected && status.connection_type.eq_ignore_ascii_case("wifi");
        let signal_active = if cellular_connected {
            SIGNAL_ACTIVE_RGB
        } else {
            STATUS_MUTED_RGB
        };
        for (index, signal_bar) in self.signal_bars.iter().copied().enumerate() {
            facade.set_visible(signal_bar, status.network_enabled)?;
            let active = (index as i32) < status.signal_strength.clamp(0, 4);
            facade.set_accent(
                signal_bar,
                if active {
                    signal_active
                } else {
                    SIGNAL_INACTIVE_RGB
                },
            )?;
        }

        if let Some(wifi) = self.wifi {
            facade.set_text(wifi, LV_SYMBOL_WIFI)?;
            facade.set_visible(wifi, wifi_connected)?;
            facade.set_accent(wifi, SIGNAL_ACTIVE_RGB)?;
        }

        let gps_color = if status.gps_has_fix {
            SIGNAL_ACTIVE_RGB
        } else {
            STATUS_MUTED_RGB
        };
        for gps_widget in [self.gps_ring, self.gps_center, self.gps_tail]
            .into_iter()
            .flatten()
        {
            facade.set_visible(gps_widget, status.network_enabled)?;
            facade.set_accent(gps_widget, gps_color)?;
        }

        self.sync_voip_dot(facade, status)?;

        if let Some(time) = self.time {
            facade.set_visible(time, show_time)?;
            if show_time {
                facade.set_text(time, &current_time_text())?;
            }
        }

        if let Some(label) = self.battery_label {
            facade.set_text(label, &format!("{}%", status.battery_percent.clamp(0, 100)))?;
        }
        if let Some(outline) = self.battery_outline {
            facade.set_accent(outline, STATUS_MUTED_RGB)?;
        }
        if let Some(tip) = self.battery_tip {
            facade.set_accent(tip, STATUS_MUTED_RGB)?;
        }
        if let Some(fill) = self.battery_fill {
            facade.set_progress(fill, status.battery_percent.clamp(0, 100))?;
            facade.set_accent(fill, battery_fill_color(status))?;
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

        while self.signal_bars.len() < STATUS_SIGNAL_ROLES.len() {
            let role = STATUS_SIGNAL_ROLES[self.signal_bars.len()];
            self.signal_bars.push(facade.create_container(bar, role)?);
        }
        if self.wifi.is_none() {
            self.wifi = Some(facade.create_label(bar, "status_wifi")?);
        }
        if self.gps_ring.is_none() {
            self.gps_ring = Some(facade.create_container(bar, "status_gps_ring")?);
        }
        if self.gps_center.is_none() {
            self.gps_center = Some(facade.create_container(bar, "status_gps_center")?);
        }
        if self.gps_tail.is_none() {
            self.gps_tail = Some(facade.create_container(bar, "status_gps_tail")?);
        }
        if self.voip_left.is_none() {
            self.voip_left = Some(facade.create_container(bar, "status_voip_dot_left")?);
        }
        if self.voip_after_gps.is_none() {
            self.voip_after_gps = Some(facade.create_container(bar, "status_voip_dot_after_gps")?);
        }
        if self.time.is_none() {
            self.time = Some(facade.create_label(bar, "status_time")?);
        }
        if self.battery_outline.is_none() {
            self.battery_outline = Some(facade.create_container(bar, "status_battery_outline")?);
        }
        let battery_outline = self
            .battery_outline
            .ok_or_else(|| anyhow!("status bar missing battery outline"))?;
        if self.battery_fill.is_none() {
            self.battery_fill =
                Some(facade.create_container(battery_outline, "status_battery_fill")?);
        }
        if self.battery_tip.is_none() {
            self.battery_tip = Some(facade.create_container(bar, "status_battery_tip")?);
        }
        if self.battery_label.is_none() {
            self.battery_label = Some(facade.create_label(bar, "status_battery_label")?);
        }

        Ok(())
    }

    fn sync_voip_dot(&self, facade: &mut dyn LvglFacade, status: &StatusBarModel) -> Result<()> {
        let active_dot = if status.network_enabled {
            self.voip_after_gps
        } else {
            self.voip_left
        };
        let inactive_dot = if status.network_enabled {
            self.voip_left
        } else {
            self.voip_after_gps
        };
        if let Some(dot) = inactive_dot {
            facade.set_visible(dot, false)?;
        }
        if let Some(dot) = active_dot {
            facade.set_visible(dot, status.voip_state != 0)?;
            facade.set_accent(
                dot,
                if status.voip_state == 2 {
                    STATUS_ERROR_RGB
                } else {
                    SIGNAL_ACTIVE_RGB
                },
            )?;
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

fn battery_fill_color(status: &StatusBarModel) -> u32 {
    if !status.power_available {
        return STATUS_MUTED_RGB;
    }
    if status.battery_percent <= 20 {
        STATUS_ERROR_RGB
    } else if status.charging {
        SIGNAL_ACTIVE_RGB
    } else {
        STATUS_INK_RGB
    }
}

fn current_time_text() -> String {
    let now = OffsetDateTime::now_local().unwrap_or_else(|_| OffsetDateTime::now_utc());
    format!("{:02}:{:02}", now.hour(), now.minute())
}
