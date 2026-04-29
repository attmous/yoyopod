use crate::runtime::{ListItemSnapshot, RuntimeSnapshot, UiScreen, UiView};

pub fn view(snapshot: &RuntimeSnapshot, focus_index: usize) -> UiView {
    UiView {
        screen: UiScreen::Power,
        title: "Status".to_string(),
        subtitle: format!("Battery {}%", snapshot.power.battery_percent),
        footer: "Tap = Next | Hold = Back".to_string(),
        items: items(snapshot),
        focus_index,
    }
}

pub fn items(snapshot: &RuntimeSnapshot) -> Vec<ListItemSnapshot> {
    if !snapshot.power.rows.is_empty() {
        return snapshot
            .power
            .rows
            .iter()
            .enumerate()
            .map(|(index, row)| {
                ListItemSnapshot::new(format!("power-{index}"), row.clone(), "", "battery")
            })
            .collect();
    }

    let charging = if snapshot.power.charging {
        "Charging"
    } else {
        "On battery"
    };
    let network = if snapshot.network.connected {
        "Connected"
    } else if snapshot.network.enabled {
        "Searching"
    } else {
        "Offline"
    };

    vec![
        ListItemSnapshot::new(
            "battery",
            format!("Battery {}%", snapshot.power.battery_percent),
            charging,
            "battery",
        ),
        ListItemSnapshot::new("network", "Network", network, "network"),
    ]
}
