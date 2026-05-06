use serde_json::json;
use yoyopod_power::snapshot::{BatterySnapshot, PowerStatusSnapshot};

#[test]
fn power_snapshot_serializes_runtime_compatible_shape() {
    let snapshot = PowerStatusSnapshot {
        available: true,
        checked_at_ms: 1234,
        source: "pisugar".to_string(),
        battery: BatterySnapshot {
            level_percent: Some(87.6),
            voltage_volts: Some(4.05),
            charging: Some(true),
            power_plugged: Some(true),
            allow_charging: Some(true),
            output_enabled: Some(true),
            temperature_celsius: Some(31.5),
        },
        error: String::new(),
        ..PowerStatusSnapshot::default()
    };

    let payload = serde_json::to_value(snapshot).expect("serialize snapshot");

    assert_eq!(payload["available"], json!(true));
    assert_eq!(payload["source"], json!("pisugar"));
    assert_eq!(payload["battery"]["level_percent"], json!(87.6));
    assert_eq!(payload["battery"]["charging"], json!(true));
    assert_eq!(payload["battery"]["power_plugged"], json!(true));
}
