use serde_json::json;
use yoyopod_ui_host::hub::{HubCommand, HubRenderer};

#[test]
fn default_snapshot_matches_python_hub_sync_contract() {
    let command = HubCommand::from_payload(&json!({})).expect("default hub command");

    assert_eq!(command.renderer, HubRenderer::Auto);
    assert_eq!(command.snapshot.icon_key, "listen");
    assert_eq!(command.snapshot.title, "Listen");
    assert_eq!(command.snapshot.subtitle, "");
    assert_eq!(command.snapshot.footer, "Tap = Next | 2x Tap = Open");
    assert_eq!(command.snapshot.time_text, "12:00");
    assert_eq!(command.snapshot.accent, 0x00FF88);
    assert_eq!(command.snapshot.selected_index, 0);
    assert_eq!(command.snapshot.total_cards, 4);
    assert_eq!(command.snapshot.voip_state, 1);
    assert_eq!(command.snapshot.battery_percent, 100);
    assert!(!command.snapshot.charging);
    assert!(command.snapshot.power_available);
}

#[test]
fn parses_explicit_python_hub_sync_fields() {
    let command = HubCommand::from_payload(&json!({
        "renderer": "lvgl",
        "icon_key": "talk",
        "title": "Talk",
        "subtitle": "Ready",
        "footer": "Tap = Next | 2x Tap = Open",
        "time_text": "17:42",
        "accent": 0x00D4FF,
        "selected_index": 1,
        "total_cards": 4,
        "voip_state": 2,
        "battery_percent": 77,
        "charging": true,
        "power_available": false
    }))
    .expect("hub command");

    assert_eq!(command.renderer, HubRenderer::Lvgl);
    assert_eq!(command.snapshot.icon_key, "talk");
    assert_eq!(command.snapshot.title, "Talk");
    assert_eq!(command.snapshot.subtitle, "Ready");
    assert_eq!(command.snapshot.time_text, "17:42");
    assert_eq!(command.snapshot.accent, 0x00D4FF);
    assert_eq!(command.snapshot.selected_index, 1);
    assert_eq!(command.snapshot.voip_state, 2);
    assert_eq!(command.snapshot.battery_percent, 77);
    assert!(command.snapshot.charging);
    assert!(!command.snapshot.power_available);
}

#[test]
fn rejects_unknown_renderer() {
    let error = HubCommand::from_payload(&json!({"renderer": "slint"}))
        .expect_err("unknown renderer must fail");

    assert!(error.to_string().contains("unknown Hub renderer"));
}
