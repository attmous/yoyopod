use yoyopod_protocol::ui::{RuntimeSnapshot, UiScreen};

use crate::engine::Key;
use crate::scene::{
    Backdrop, ContextLabelModel, Deck, DeckItem, DeckItemAnim, DeckKind, FocusPolicy, ItemRender,
    RegionId, Scene, SceneContext, SceneDefaults, SceneId, SetupAboutModel, SetupCounterModel,
    SetupVolumeModel, WheelItemModel, WheelItemVariant,
};

const STAGE_CORAL: u32 = 0xFDE2D8;
const CREAM_2: u32 = 0xF7DBC2;
const PERI: u32 = 0xA9A6E5;

pub fn scene(
    screen: UiScreen,
    snapshot: &RuntimeSnapshot,
    focus: usize,
    defaults: SceneDefaults,
) -> Scene {
    match screen {
        UiScreen::Setup => wheel_scene(
            screen,
            defaults,
            setup_root_items(snapshot),
            focus,
            Some(SceneContext::SetupCounter(SetupCounterModel {
                text: format!("{}/6", focus % 6 + 1),
            })),
        ),
        UiScreen::SetupCompanion => wheel_scene(
            screen,
            defaults,
            companion_items(snapshot),
            focus,
            context("COMPANION"),
        ),
        UiScreen::SetupContacts => wheel_scene(
            screen,
            defaults,
            contact_items(snapshot),
            focus,
            context("CONTACTS"),
        ),
        UiScreen::SetupTheme => wheel_scene(
            screen,
            defaults,
            theme_items(snapshot),
            focus,
            context("THEME"),
        ),
        UiScreen::SetupVolume => leaf_scene(
            screen,
            defaults,
            "VOLUME",
            ItemRender::SetupVolume(SetupVolumeModel {
                level: snapshot.settings.volume_level,
            }),
        ),
        UiScreen::SetupAbout => leaf_scene(
            screen,
            defaults,
            "ABOUT",
            ItemRender::SetupAbout(about_model(snapshot)),
        ),
        _ => unreachable!("setup scene requested for {}", screen.as_str()),
    }
}

fn wheel_scene(
    screen: UiScreen,
    defaults: SceneDefaults,
    items: Vec<WheelItemModel>,
    focus: usize,
    context: Option<SceneContext>,
) -> Scene {
    Scene {
        id: SceneId::new(screen),
        backdrop: Backdrop::Solid(STAGE_CORAL),
        stage: defaults.stage,
        context,
        decks: vec![Deck {
            kind: DeckKind::Wheel,
            region: RegionId::Auto,
            items: items
                .into_iter()
                .enumerate()
                .map(|(index, item)| DeckItem {
                    key: Key::Indexed(index),
                    render: ItemRender::Wheel(item),
                })
                .collect(),
            focus_index: focus,
            focus_policy: FocusPolicy::Wrap,
            item_anim: DeckItemAnim::ScaleOnFocus {
                from_permille: 700,
                to_permille: 1000,
            },
            swap_anim: None,
            recycle_window: Some(3),
        }],
        cursor: None,
        fx: Default::default(),
        modal: None,
        timelines: Vec::new(),
    }
}

fn leaf_scene(screen: UiScreen, defaults: SceneDefaults, label: &str, render: ItemRender) -> Scene {
    Scene {
        id: SceneId::new(screen),
        backdrop: Backdrop::Solid(STAGE_CORAL),
        stage: defaults.stage,
        context: context(label),
        decks: vec![Deck {
            kind: DeckKind::Page,
            region: RegionId::Auto,
            items: vec![DeckItem {
                key: Key::Static("setup_leaf"),
                render,
            }],
            focus_index: 0,
            focus_policy: FocusPolicy::None,
            item_anim: DeckItemAnim::None,
            swap_anim: None,
            recycle_window: None,
        }],
        cursor: None,
        fx: Default::default(),
        modal: None,
        timelines: Vec::new(),
    }
}

fn context(value: &str) -> Option<SceneContext> {
    Some(SceneContext::Label(ContextLabelModel::new(value)))
}

fn setup_root_items(snapshot: &RuntimeSnapshot) -> Vec<WheelItemModel> {
    let battery = format!("{}%", snapshot.power.battery_percent.clamp(0, 100));
    let contacts = snapshot.call.contacts.len().to_string();
    vec![
        setup_item(
            "Volume",
            snapshot.settings.volume_level.to_string(),
            "setup_volume",
            CREAM_2,
            false,
        ),
        setup_item(
            "Companion",
            &snapshot.settings.companion,
            "setup_companion",
            companion_color(&snapshot.settings.companion),
            false,
        ),
        setup_item("Contacts", contacts, "setup_contacts", PERI, false),
        setup_item(
            "Theme",
            &snapshot.settings.theme,
            "setup_theme",
            CREAM_2,
            false,
        ),
        setup_item(
            "Speak names",
            if snapshot.settings.speak_names {
                "On"
            } else {
                "Off"
            },
            "setup_speak",
            CREAM_2,
            false,
        ),
        setup_item("About", battery, "setup_about", CREAM_2, false),
    ]
}

fn companion_items(snapshot: &RuntimeSnapshot) -> Vec<WheelItemModel> {
    ["Blob", "Owl", "Cat", "Bunny", "Robot"]
        .into_iter()
        .map(|name| {
            setup_item(
                name,
                if name.eq_ignore_ascii_case(&snapshot.settings.companion) {
                    "current"
                } else {
                    ""
                },
                &format!("setup_{}", name.to_ascii_lowercase()),
                companion_color(name),
                true,
            )
        })
        .collect()
}

fn contact_items(snapshot: &RuntimeSnapshot) -> Vec<WheelItemModel> {
    snapshot
        .call
        .contacts
        .iter()
        .enumerate()
        .map(|(index, contact)| {
            setup_item(
                &contact.title,
                "companion app",
                "setup_contacts",
                [0xA9A6E5, 0xF3A9A2, 0x9FB89A, 0xE8B66A][index % 4],
                true,
            )
        })
        .collect()
}

fn theme_items(snapshot: &RuntimeSnapshot) -> Vec<WheelItemModel> {
    [
        ("Light", "setup_light", 0xF6F2EB),
        ("Dark", "setup_dark", 0x1B1B1F),
        ("Auto", "setup_auto", CREAM_2),
    ]
    .into_iter()
    .map(|(name, icon, color)| {
        setup_item(
            name,
            if name.eq_ignore_ascii_case(&snapshot.settings.theme) {
                "current"
            } else {
                ""
            },
            icon,
            color,
            true,
        )
    })
    .collect()
}

fn setup_item(
    title: impl Into<String>,
    subtitle: impl Into<String>,
    icon_key: impl Into<String>,
    plate_rgb: u32,
    round: bool,
) -> WheelItemModel {
    WheelItemModel {
        title: title.into(),
        subtitle: subtitle.into(),
        variant: WheelItemVariant::Setup {
            icon_key: icon_key.into(),
            plate_rgb,
            round,
        },
    }
}

fn companion_color(name: &str) -> u32 {
    match name.trim().to_ascii_lowercase().as_str() {
        "blob" => 0xF3A9A2,
        "owl" => 0xE8B66A,
        "cat" => 0xA9A6E5,
        "robot" => 0x9CB7C9,
        _ => 0x9FB89A,
    }
}

fn about_model(snapshot: &RuntimeSnapshot) -> SetupAboutModel {
    let charge = if snapshot.power.charging {
        "Charging"
    } else {
        "Battery"
    };
    let network = if snapshot.network.connected {
        snapshot.network.connection_type.clone()
    } else {
        "Offline".to_string()
    };
    SetupAboutModel {
        battery_percent: snapshot.power.battery_percent.clamp(0, 100),
        charging: snapshot.power.charging,
        rows: vec![
            (
                "BATTERY".to_string(),
                format!("{}%", snapshot.power.battery_percent.clamp(0, 100)),
            ),
            ("POWER".to_string(), charge.to_string()),
            (
                "FIRMWARE".to_string(),
                snapshot.settings.firmware_version.clone(),
            ),
            ("NETWORK".to_string(), network),
            ("DEVICE".to_string(), snapshot.settings.device_name.clone()),
        ],
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::scene::defaults_for;

    #[test]
    fn setup_root_is_a_six_item_coral_wheel() {
        let snapshot = RuntimeSnapshot::default();
        let scene = scene(UiScreen::Setup, &snapshot, 0, defaults_for(UiScreen::Setup));
        assert_eq!(scene.backdrop, Backdrop::Solid(STAGE_CORAL));
        assert_eq!(scene.decks[0].items.len(), 6);
        assert_eq!(scene.decks[0].recycle_window, Some(3));
        assert_eq!(
            scene
                .context
                .as_ref()
                .and_then(SceneContext::setup_counter)
                .map(|value| value.text.as_str()),
            Some("1/6")
        );
    }

    #[test]
    fn volume_leaf_uses_runtime_level() {
        let mut snapshot = RuntimeSnapshot::default();
        snapshot.settings.volume_level = 7;
        let scene = scene(
            UiScreen::SetupVolume,
            &snapshot,
            0,
            defaults_for(UiScreen::SetupVolume),
        );
        assert!(matches!(
            scene.decks[0].items[0].render,
            ItemRender::SetupVolume(SetupVolumeModel { level: 7 })
        ));
    }
}
