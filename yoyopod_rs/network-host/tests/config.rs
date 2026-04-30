use std::fs;
use std::sync::{Mutex, OnceLock};

use yoyopod_network_host::config::NetworkHostConfig;

fn env_lock() -> &'static Mutex<()> {
    static LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    LOCK.get_or_init(|| Mutex::new(()))
}

#[test]
fn load_config_reads_nested_network_payload_and_applies_env_overrides() {
    let _guard = env_lock().lock().expect("env lock");
    let temp = tempfile::tempdir().expect("tempdir");
    let config_dir = temp.path().join("config");
    let network_dir = config_dir.join("network");
    fs::create_dir_all(&network_dir).expect("network dir");
    fs::write(
        network_dir.join("cellular.yaml"),
        concat!(
            "network:\n",
            "  enabled: false\n",
            "  serial_port: /dev/ttyUSB2\n",
            "  ppp_port: /dev/ttyUSB3\n",
            "  baud_rate: 115200\n",
            "  apn: old-apn\n",
            "  gps_enabled: true\n",
            "  ppp_timeout: 30\n"
        ),
    )
    .expect("write config");

    std::env::set_var("YOYOPOD_NETWORK_ENABLED", "true");
    std::env::set_var("YOYOPOD_MODEM_APN", "internet");
    std::env::set_var("YOYOPOD_MODEM_GPS_ENABLED", "false");
    let config = NetworkHostConfig::load(&config_dir).expect("load config");
    std::env::remove_var("YOYOPOD_NETWORK_ENABLED");
    std::env::remove_var("YOYOPOD_MODEM_APN");
    std::env::remove_var("YOYOPOD_MODEM_GPS_ENABLED");

    assert!(config.enabled);
    assert_eq!(config.apn, "internet");
    assert!(!config.gps_enabled);
    assert_eq!(config.serial_port, "/dev/ttyUSB2");
    assert_eq!(config.ppp_port, "/dev/ttyUSB3");
}

#[test]
fn load_config_applies_board_overlay_from_domain_relative_path() {
    let _guard = env_lock().lock().expect("env lock");
    let temp = tempfile::tempdir().expect("tempdir");
    let config_dir = temp.path().join("config");
    let network_dir = config_dir.join("network");
    let board_dir = config_dir
        .join("boards")
        .join("rpi-zero-2w")
        .join("network");
    fs::create_dir_all(&network_dir).expect("network dir");
    fs::create_dir_all(&board_dir).expect("board dir");
    fs::write(
        network_dir.join("cellular.yaml"),
        concat!(
            "network:\n",
            "  enabled: false\n",
            "  serial_port: /dev/ttyUSB2\n",
            "  ppp_port: /dev/ttyUSB3\n",
            "  baud_rate: 115200\n",
            "  apn: base-apn\n",
            "  gps_enabled: false\n",
            "  ppp_timeout: 30\n"
        ),
    )
    .expect("write base config");
    fs::write(
        board_dir.join("cellular.yaml"),
        concat!(
            "network:\n",
            "  enabled: true\n",
            "  gps_enabled: true\n",
            "  apn: board-apn\n"
        ),
    )
    .expect("write board config");

    std::env::set_var("YOYOPOD_CONFIG_BOARD", "rpi-zero-2w");
    let config = NetworkHostConfig::load(&config_dir).expect("load config");
    std::env::remove_var("YOYOPOD_CONFIG_BOARD");

    assert!(config.enabled);
    assert!(config.gps_enabled);
    assert_eq!(config.apn, "board-apn");
    assert_eq!(config.serial_port, "/dev/ttyUSB2");
}
