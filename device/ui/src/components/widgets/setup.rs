use crate::components::primitives::{container, image, label, qr};
use crate::engine::{Element, Key};
use crate::scene::{roles, SetupAboutModel, SetupCounterModel, SetupVolumeModel, WifiSetupModel};

const CORAL: u32 = 0xF37767;
const CREAM_2: u32 = 0xF7DBC2;
const INK: u32 = 0x1B1B1F;

pub fn setup_counter(model: &SetupCounterModel) -> Element {
    label(roles::SETUP_COUNTER)
        .key(Key::Static("setup_counter"))
        .text(&model.text)
}

pub fn setup_volume(model: &SetupVolumeModel) -> Element {
    let level = model.level.clamp(1, 10);
    let mut root = container(roles::SETUP_VOLUME)
        .key(Key::Static("setup_volume"))
        .child(
            image(roles::SETUP_VOLUME_ICON)
                .key(Key::Static("setup_volume_icon"))
                .icon("setup_volume")
                .accent(INK),
        )
        .child(
            label(roles::SETUP_VOLUME_VALUE)
                .key(Key::Static("setup_volume_value"))
                .text(format!("{level} / 10")),
        );
    let mut meter = container(roles::SETUP_VOLUME_METER).key(Key::Static("setup_volume_meter"));
    for index in 0..10 {
        meter = meter.child(
            container(roles::SETUP_VOLUME_BLOCK)
                .key(Key::String(format!("setup_volume_block:{index}")))
                .absolute(20 * index, 0, 16, 22)
                .accent(if index < level { CORAL } else { CREAM_2 }),
        );
    }
    root = root.child(meter);
    root
}

pub fn setup_about(model: &SetupAboutModel) -> Element {
    let mut root = container(roles::SETUP_ABOUT)
        .key(Key::Static("setup_about"))
        .child(
            label(roles::SETUP_ABOUT_BATTERY)
                .key(Key::Static("setup_about_battery"))
                .text(if model.charging { "BAT +" } else { "BAT" }),
        );
    for (index, (name, value)) in model.rows.iter().enumerate() {
        let y = 60 + index as i32 * 24;
        root = root
            .child(
                label(roles::SETUP_ABOUT_LABEL)
                    .key(Key::String(format!("setup_about_label:{index}")))
                    .text(name)
                    .absolute(24, y, 100, 14),
            )
            .child(
                label(roles::SETUP_ABOUT_VALUE)
                    .key(Key::String(format!("setup_about_value:{index}")))
                    .text(value)
                    .absolute(130, y, 90, 16),
            );
    }
    root.child(
        label(roles::SETUP_HINT)
            .key(Key::Static("setup_about_hint"))
            .text(format!("Battery {}%", model.battery_percent)),
    )
}

pub fn setup_wifi(model: &WifiSetupModel) -> Element {
    let mut root = container(roles::SETUP_ABOUT).key(Key::Static("setup_wifi"));

    // Once the hotspot is up the worker supplies a Wi‑Fi-join payload; show it as
    // a QR the phone scans to auto-join. Before that (starting/error) there is no
    // payload, so the screen shows the status line only.
    if !model.qr_payload.is_empty() {
        root = root.child(
            qr(roles::PAGE)
                .key(Key::Static("setup_wifi_qr"))
                .text(&model.qr_payload)
                .absolute(30, 12, 180, 180),
        );
    }

    if !model.ap_ssid.is_empty() {
        root = root.child(
            label(roles::SETUP_ABOUT_LABEL)
                .key(Key::Static("setup_wifi_ssid"))
                .text(format!("Join {}", model.ap_ssid))
                .absolute(12, 198, 216, 16),
        );
    }
    if !model.ap_password.is_empty() {
        root = root.child(
            label(roles::SETUP_ABOUT_VALUE)
                .key(Key::Static("setup_wifi_key"))
                .text(format!("Key {}", model.ap_password))
                .absolute(12, 218, 216, 16),
        );
    }

    let status = if model.status_text.is_empty() {
        "Preparing Wi‑Fi setup…".to_string()
    } else {
        model.status_text.clone()
    };
    root.child(
        label(roles::SETUP_HINT)
            .key(Key::Static("setup_wifi_status"))
            .text(status)
            .absolute(12, 240, 216, 34),
    )
}
