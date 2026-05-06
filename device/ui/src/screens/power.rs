use crate::runtime::{ListItemSnapshot, RuntimeSnapshot, UiScreen, UiView};
use crate::screens::{chrome, ListRowModel, PowerViewModel};

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SetupPageModel {
    pub title: String,
    pub icon_key: String,
    pub rows: Vec<String>,
}

pub fn model(snapshot: &RuntimeSnapshot, focus_index: usize) -> PowerViewModel {
    let pages = pages(snapshot);
    let active_index = active_page_index(&pages, focus_index);
    let page = &pages[active_index];
    PowerViewModel {
        chrome: chrome::chrome(snapshot, "Tap page / Hold back"),
        title: page.title.clone(),
        subtitle: String::new(),
        icon_key: page.icon_key.clone(),
        rows: page
            .rows
            .iter()
            .enumerate()
            .map(|(index, row)| ListRowModel {
                id: format!("setup-{active_index}-{index}"),
                title: row.clone(),
                subtitle: String::new(),
                icon_key: page.icon_key.clone(),
                selected: false,
            })
            .collect(),
        current_page_index: active_index,
        total_pages: pages.len(),
    }
}

pub fn view(snapshot: &RuntimeSnapshot, focus_index: usize) -> UiView {
    let pages = pages(snapshot);
    let active_index = active_page_index(&pages, focus_index);
    let page = &pages[active_index];
    UiView {
        screen: UiScreen::Power,
        title: page.title.clone(),
        subtitle: String::new(),
        footer: "Tap page / Hold back".to_string(),
        items: page
            .rows
            .iter()
            .enumerate()
            .map(|(index, row)| {
                ListItemSnapshot::new(
                    format!("setup-{active_index}-{index}"),
                    row.clone(),
                    "",
                    page.icon_key.clone(),
                )
            })
            .collect(),
        focus_index: active_index,
    }
}

pub fn items(snapshot: &RuntimeSnapshot) -> Vec<ListItemSnapshot> {
    let pages = pages(snapshot);
    let active_index = active_page_index(&pages, 0);
    let page = &pages[active_index];
    page.rows
        .iter()
        .enumerate()
        .map(|(index, row)| {
            ListItemSnapshot::new(
                format!("setup-{active_index}-{index}"),
                row.clone(),
                "",
                page.icon_key.clone(),
            )
        })
        .collect()
}

pub fn page_count(snapshot: &RuntimeSnapshot) -> usize {
    pages(snapshot).len().max(1)
}

pub fn pages(snapshot: &RuntimeSnapshot) -> Vec<SetupPageModel> {
    if !snapshot.power.pages.is_empty() {
        return snapshot
            .power
            .pages
            .iter()
            .map(|page| SetupPageModel {
                title: if page.title.trim().is_empty() {
                    "Setup".to_string()
                } else {
                    page.title.clone()
                },
                icon_key: if page.icon_key.trim().is_empty() {
                    page_icon_key(&page.title).to_string()
                } else {
                    page.icon_key.clone()
                },
                rows: page.rows.iter().take(5).cloned().collect(),
            })
            .collect();
    }

    if !snapshot.power.rows.is_empty() {
        return vec![SetupPageModel {
            title: "Power".to_string(),
            icon_key: "battery".to_string(),
            rows: snapshot
                .power
                .rows
                .iter()
                .take(5)
                .map(format_legacy_row)
                .collect(),
        }];
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
        SetupPageModel {
            title: "Power".to_string(),
            icon_key: "battery".to_string(),
            rows: vec![
                format!("Battery: {}%", snapshot.power.battery_percent),
                format!("Charging: {charging}"),
                format!(
                    "External: {}",
                    if snapshot.power.power_available {
                        "Available"
                    } else {
                        "Unavailable"
                    }
                ),
            ],
        },
        SetupPageModel {
            title: "Time".to_string(),
            icon_key: "clock".to_string(),
            rows: vec![
                "RTC: Unknown".to_string(),
                "Alarm: Unknown".to_string(),
                "Uptime: --".to_string(),
                "Screen: Awake".to_string(),
            ],
        },
        SetupPageModel {
            title: "Care".to_string(),
            icon_key: "care".to_string(),
            rows: vec![
                format!("Network: {network}"),
                "VoIP: Offline".to_string(),
                "Watchdog: Off".to_string(),
            ],
        },
        SetupPageModel {
            title: "Voice".to_string(),
            icon_key: "voice_note".to_string(),
            rows: vec![
                "Voice Cmds: Unknown".to_string(),
                "AI Requests: Unknown".to_string(),
                "Screen Read: Unknown".to_string(),
                "Mic: Unknown".to_string(),
                "Volume: --".to_string(),
            ],
        },
    ]
}

fn active_page_index(pages: &[SetupPageModel], focus_index: usize) -> usize {
    if pages.is_empty() {
        0
    } else {
        focus_index % pages.len()
    }
}

fn format_legacy_row(row: &String) -> String {
    if row.contains(':') {
        row.clone()
    } else {
        row.to_string()
    }
}

fn page_icon_key(title: &str) -> &'static str {
    match title {
        "Power" => "battery",
        "Time" => "clock",
        "Voice" => "voice_note",
        "Network" => "signal",
        "GPS" | "Care" => "care",
        _ => "care",
    }
}
