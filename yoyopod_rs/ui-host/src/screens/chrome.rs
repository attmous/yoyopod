use crate::runtime::{ListItemSnapshot, RuntimeSnapshot};

use super::{ChromeModel, ListRowModel, StatusBarModel};

pub(crate) fn chrome(snapshot: &RuntimeSnapshot, footer: &str) -> ChromeModel {
    ChromeModel {
        status: StatusBarModel {
            network_connected: snapshot.network.connected,
            network_enabled: snapshot.network.enabled,
            connection_type: snapshot.network.connection_type.clone(),
            signal_strength: snapshot.network.signal_strength,
            gps_has_fix: snapshot.network.gps_has_fix,
            battery_percent: snapshot.power.battery_percent,
            charging: snapshot.power.charging,
            power_available: snapshot.power.power_available,
            voip_state: voip_state(snapshot),
        },
        footer: footer.to_string(),
    }
}

pub(crate) fn list_rows(items: &[ListItemSnapshot], focus_index: usize) -> Vec<ListRowModel> {
    items
        .iter()
        .enumerate()
        .map(|(index, item)| ListRowModel {
            id: item.id.clone(),
            title: item.title.clone(),
            subtitle: item.subtitle.clone(),
            icon_key: item.icon_key.clone(),
            selected: index == focus_index,
        })
        .collect()
}

fn voip_state(snapshot: &RuntimeSnapshot) -> i32 {
    match snapshot.call.state.as_str() {
        "incoming" | "outgoing" | "active" => 2,
        _ => 1,
    }
}
