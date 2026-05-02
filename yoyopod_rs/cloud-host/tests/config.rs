use std::fs;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use yoyopod_cloud_host::config::CloudHostConfig;

#[test]
fn loads_cloud_backend_and_runtime_secrets() {
    let dir = temp_dir("cloud-config");
    write(
        &dir.join("cloud/backend.yaml"),
        r#"
backend:
  mqtt_broker_host: "mqtt.example.test"
  mqtt_broker_port: 443
  mqtt_use_tls: true
  mqtt_transport: "websockets"
  mqtt_username: "device-user"
  mqtt_password: "device-pass"
  battery_report_interval_seconds: 12
  status_file: "data/cloud/status.json"
"#,
    );
    write(
        &dir.join("cloud/device.secrets.yaml"),
        r#"
secrets:
  device_id: "device-123"
  device_secret: "secret-456"
"#,
    );

    let config = CloudHostConfig::load(&dir).expect("load cloud config");

    assert_eq!(config.mqtt_broker_host, "mqtt.example.test");
    assert_eq!(config.mqtt_broker_port, 443);
    assert!(config.mqtt_use_tls);
    assert_eq!(config.mqtt_transport, "websockets");
    assert_eq!(config.mqtt_username, "device-user");
    assert_eq!(config.mqtt_password, "device-pass");
    assert_eq!(config.battery_report_interval_seconds, 12);
    assert_eq!(config.device_id, "device-123");
    assert_eq!(config.device_secret, "secret-456");
    assert!(config.provisioned());
    assert_eq!(config.device_event_topic(), "yoyopod/device-123/evt");
    assert_eq!(config.device_ack_topic(), "yoyopod/device-123/ack");
    assert_eq!(config.device_command_topic(), "yoyopod/device-123/cmd");
}

#[test]
fn partial_provisioning_is_marked_invalid() {
    let dir = temp_dir("partial-secrets");
    write(
        &dir.join("cloud/device.secrets.yaml"),
        r#"
device_id: "device-only"
"#,
    );

    let config = CloudHostConfig::load(&dir).expect("load cloud config");

    assert!(!config.provisioned());
    assert!(config
        .secrets_error
        .contains("both device_id and device_secret"));
}

fn temp_dir(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-cloud-host-{test_name}-{unique}"))
}

fn write(path: &Path, contents: &str) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("parent dir");
    }
    fs::write(path, contents).expect("write file");
}
