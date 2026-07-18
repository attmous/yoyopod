use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

use crate::engine::Key;
use crate::scene::{
    Cursor, Deck, DeckItem, DeckItemAnim, DeckKind, ItemRender, PageModel, RegionId, Scene,
    SceneDefaults, SceneId,
};

pub struct PowerProps {
    pub defaults: SceneDefaults,
    pub pages: Vec<DeckItem>,
    pub focus: usize,
}

pub fn props_from(snapshot: &RuntimeSnapshot, focus: usize, defaults: SceneDefaults) -> PowerProps {
    PowerProps {
        defaults,
        pages: pages(snapshot),
        focus,
    }
}

pub fn scene(props: &PowerProps) -> Scene {
    let page_count = props.pages.len();
    Scene {
        id: SceneId::new(UiScreen::Power),
        backdrop: props.defaults.backdrop(0x3ddd53),
        stage: props.defaults.stage,
        context: None,
        decks: vec![Deck {
            kind: DeckKind::Page,
            region: RegionId::ListBody,
            items: props.pages.clone(),
            focus_index: props.focus,
            focus_policy: crate::scene::FocusPolicy::Wrap,
            item_anim: DeckItemAnim::None,
            swap_anim: None,
            recycle_window: None,
        }],
        cursor: Some(Cursor::UnderlineDots {
            count: page_count,
            focus: props.focus,
        }),
        fx: props.defaults.fx_layer(0x3ddd53),
        modal: None,
        timelines: props.defaults.fx_timelines(),
    }
}

fn pages(snapshot: &RuntimeSnapshot) -> Vec<DeckItem> {
    if !snapshot.power.pages.is_empty() {
        return snapshot
            .power
            .pages
            .iter()
            .enumerate()
            .map(|(index, page)| {
                page_item(
                    format!("power-page-{index}"),
                    title_or_default(&page.title, "Setup"),
                    page.rows.join("\n"),
                )
            })
            .collect();
    }

    if !snapshot.power.rows.is_empty() {
        return vec![page_item(
            "power-rows",
            "Power".to_string(),
            snapshot.power.rows.join("\n"),
        )];
    }

    default_pages(snapshot)
}

fn default_pages(snapshot: &RuntimeSnapshot) -> Vec<DeckItem> {
    let charging = if snapshot.power.charging {
        "Charging"
    } else {
        "On battery"
    };
    let external = if snapshot.power.power_available {
        "Available"
    } else {
        "Unavailable"
    };
    let network = if snapshot.network.connected {
        "Connected"
    } else if snapshot.network.enabled {
        "Searching"
    } else {
        "Offline"
    };
    vec![
        page_item(
            "power",
            "Power".to_string(),
            format!(
                "Battery: {}%\nCharging: {charging}\nExternal: {external}",
                snapshot.power.battery_percent
            ),
        ),
        page_item(
            "time",
            "Time".to_string(),
            "RTC: Unknown\nAlarm: Unknown\nUptime: --\nScreen: Awake".to_string(),
        ),
        page_item(
            "care",
            "Care".to_string(),
            format!("Network: {network}\nVoIP: Offline\nWatchdog: Off"),
        ),
        page_item(
            "voice",
            "Voice".to_string(),
            "Voice Cmds: Unknown\nAI Requests: Unknown\nMic: Unknown\nVolume: --".to_string(),
        ),
    ]
}

fn page_item(key: impl Into<String>, title: String, body: String) -> DeckItem {
    DeckItem {
        key: Key::String(key.into()),
        render: ItemRender::Page(PageModel { title, body }),
    }
}

fn title_or_default(value: &str, default: &str) -> String {
    if value.trim().is_empty() {
        default.to_string()
    } else {
        value.to_string()
    }
}
