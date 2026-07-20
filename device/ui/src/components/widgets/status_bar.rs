use crate::components::primitives::{container, image, label};
use crate::engine::{Element, Key};
use crate::scene::roles;
use crate::scene::{HudConnectivityKind, HudStatus};

const INK: u32 = 0x1B1B1F;
const INK_MUTED: u32 = 0x8A8076;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StatusBarProps {
    pub status: HudStatus,
    pub opacity: u8,
}

pub fn status_bar(props: &StatusBarProps) -> Element {
    let status = &props.status;
    container(roles::STATUS_BAR)
        .key(Key::Static("status_bar"))
        .opacity(props.opacity)
        .child(
            container(roles::STATUS_LEFT_CLUSTER)
                .key(Key::Static("status_left_cluster"))
                .child(status_icon(
                    roles::STATUS_NETWORK_ICON,
                    "status_network",
                    network_icon_key(status),
                    status.connectivity.connected,
                ))
                .child(status_icon(
                    roles::STATUS_GPS_ICON,
                    "status_gps",
                    "status_gps",
                    status.gps_has_fix,
                ))
                .child(status_icon(
                    roles::STATUS_VOIP_ICON,
                    "status_voip",
                    "status_voip",
                    status.voip_registered,
                )),
        )
        .child(
            label(roles::STATUS_TIME)
                .key(Key::Static("status_time"))
                .text(&status.time),
        )
        .child(
            container(roles::STATUS_RIGHT_CLUSTER)
                .key(Key::Static("status_right_cluster"))
                .child(
                    label(roles::STATUS_BATTERY_LABEL)
                        .key(Key::Static("status_battery_label"))
                        .text(battery_label(status)),
                )
                .child(
                    image(roles::STATUS_CHARGE_ICON)
                        .key(Key::Static("status_charge"))
                        .icon("status_charge")
                        .accent(INK)
                        .visible(status.battery.available && status.battery.charging),
                )
                .child(
                    image(roles::STATUS_BATTERY_ICON)
                        .key(Key::Static("status_battery"))
                        .icon(battery_icon_key(status.battery.percent))
                        .accent(if status.battery.available {
                            INK
                        } else {
                            INK_MUTED
                        }),
                ),
        )
}

fn status_icon(
    role: &'static str,
    key: &'static str,
    icon_key: &'static str,
    active: bool,
) -> Element {
    image(role)
        .key(Key::Static(key))
        .icon(icon_key)
        .accent(if active { INK } else { INK_MUTED })
}

fn network_icon_key(status: &HudStatus) -> &'static str {
    match status.connectivity.kind {
        HudConnectivityKind::Wifi => "status_wifi",
        HudConnectivityKind::Cellular | HudConnectivityKind::Unknown => {
            match status.connectivity.strength.min(4) {
                0 => "status_cellular_0",
                1 => "status_cellular_1",
                2 => "status_cellular_2",
                3 => "status_cellular_3",
                _ => "status_cellular_4",
            }
        }
    }
}

fn battery_icon_key(percent: u8) -> &'static str {
    match percent.min(100) {
        0 => "status_battery_empty",
        1..=25 => "status_battery_1",
        26..=50 => "status_battery_2",
        51..=75 => "status_battery_3",
        _ => "status_battery_full",
    }
}

fn battery_label(status: &HudStatus) -> String {
    if status.battery.available {
        format!("{}%", status.battery.percent.min(100))
    } else {
        "--".to_string()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::engine::Layout;
    use crate::scene::{HudBattery, HudConnectivity};

    #[test]
    fn battery_symbols_follow_quartiles() {
        assert_eq!(battery_icon_key(0), "status_battery_empty");
        assert_eq!(battery_icon_key(25), "status_battery_1");
        assert_eq!(battery_icon_key(50), "status_battery_2");
        assert_eq!(battery_icon_key(75), "status_battery_3");
        assert_eq!(battery_icon_key(100), "status_battery_full");
    }

    #[test]
    fn connectivity_selects_one_image_source() {
        let mut status = HudStatus {
            connectivity: HudConnectivity {
                kind: HudConnectivityKind::Cellular,
                connected: true,
                strength: 3,
            },
            battery: HudBattery {
                available: true,
                ..HudBattery::default()
            },
            ..HudStatus::default()
        };
        assert_eq!(network_icon_key(&status), "status_cellular_3");

        status.connectivity.kind = HudConnectivityKind::Wifi;
        assert_eq!(network_icon_key(&status), "status_wifi");
    }

    #[test]
    fn status_bar_uses_the_renderer_asset_layout() {
        let element = status_bar(&StatusBarProps {
            status: HudStatus::default(),
            opacity: 255,
        });

        assert_eq!(element.layout, Layout::Region(crate::scene::RegionId::Auto));
    }
}
