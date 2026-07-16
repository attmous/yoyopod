use crate::components::primitives::{container, label};
use crate::engine::Element;
use crate::engine::Key;
use crate::scene::roles;
use crate::scene::RegionId;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StatusBarProps {
    pub time: String,
    pub battery_label: String,
    pub battery_percent: u8,
    pub signal_strength: u8,
    pub network_online: bool,
}

pub fn status_bar(props: &StatusBarProps) -> Element {
    let mut status_bar = container(roles::STATUS_BAR)
        .key(Key::Static("status_bar"))
        .region(RegionId::StatusBar);

    for bar in signal_bars(props.signal_strength) {
        status_bar = status_bar.child(bar);
    }

    status_bar
        .child(gps_ring(props.network_online))
        .child(gps_center(props.network_online))
        .child(gps_tail(props.network_online))
        .child(
            label(roles::STATUS_TIME)
                .key(Key::Static("status_time"))
                .text(&props.time),
        )
        .child(
            label(roles::STATUS_BATTERY_LABEL)
                .key(Key::Static("status_battery_label"))
                .text(&props.battery_label),
        )
        .child(battery_outline(props.battery_percent))
        .child(container(roles::STATUS_BATTERY_TIP).key(Key::Static("battery_tip")))
}

fn signal_bars(strength: u8) -> [Element; 4] {
    core::array::from_fn(|index| {
        container(signal_bar_role(index))
            .key(Key::Indexed(index))
            .visible(index < usize::from(strength.min(4)))
    })
}

fn gps_ring(active: bool) -> Element {
    container(roles::STATUS_GPS_RING)
        .key(Key::Static("gps_ring"))
        .selected(active)
}

fn gps_center(active: bool) -> Element {
    container(roles::STATUS_GPS_CENTER)
        .key(Key::Static("gps_center"))
        .visible(active)
}

fn gps_tail(active: bool) -> Element {
    container(roles::STATUS_GPS_TAIL)
        .key(Key::Static("gps_tail"))
        .visible(active)
}

fn battery_outline(percent: u8) -> Element {
    container(roles::STATUS_BATTERY_OUTLINE)
        .key(Key::Static("battery_outline"))
        .child(
            container(roles::STATUS_BATTERY_FILL)
                .key(Key::Static("battery_fill"))
                .progress(i32::from(percent.min(100))),
        )
}

const fn signal_bar_role(index: usize) -> &'static str {
    match index {
        0 => roles::STATUS_SIGNAL_BAR_0,
        1 => roles::STATUS_SIGNAL_BAR_1,
        2 => roles::STATUS_SIGNAL_BAR_2,
        _ => roles::STATUS_SIGNAL_BAR_3,
    }
}
