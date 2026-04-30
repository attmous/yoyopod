use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::json;
use yoyopod_runtime::config::RuntimeConfig;

const CONFIG_ENV_KEYS: &[&str] = &[
    "YOYOPOD_DISPLAY",
    "YOYOPOD_WHISPLAY_RENDERER",
    "YOYOPOD_PID_FILE",
    "YOYOPOD_LOG_FILE",
    "YOYOPOD_SIP_SERVER",
    "YOYOPOD_SIP_USERNAME",
    "YOYOPOD_SIP_IDENTITY",
    "YOYOPOD_SIP_TRANSPORT",
    "YOYOPOD_SIP_PASSWORD",
    "YOYOPOD_SIP_PASSWORD_HA1",
    "YOYOPOD_STUN_SERVER",
    "YOYOPOD_PLAYBACK_DEVICE",
    "YOYOPOD_RINGER_DEVICE",
    "YOYOPOD_CAPTURE_DEVICE",
    "YOYOPOD_MEDIA_DEVICE",
    "YOYOPOD_RING_OUTPUT_DEVICE",
    "YOYOPOD_LIBLINPHONE_FACTORY_CONFIG",
    "YOYOPOD_CONFERENCE_FACTORY_URI",
    "YOYOPOD_FILE_TRANSFER_SERVER_URL",
    "YOYOPOD_LIME_SERVER_URL",
    "YOYOPOD_VOIP_ITERATE_INTERVAL_MS",
    "YOYOPOD_MESSAGE_STORE_DIR",
    "YOYOPOD_VOICE_NOTE_STORE_DIR",
    "YOYOPOD_AUTO_DOWNLOAD_INCOMING_VOICE_RECORDINGS",
    "YOYOPOD_MUSIC_DIR",
    "YOYOPOD_MPV_SOCKET",
    "YOYOPOD_MPV_BINARY",
    "YOYOPOD_AUTO_RESUME_AFTER_CALL",
    "YOYOPOD_DEFAULT_VOLUME",
    "YOYOPOD_RECENT_TRACKS_FILE",
    "YOYOPOD_REMOTE_CACHE_DIR",
    "YOYOPOD_REMOTE_CACHE_MAX_BYTES",
    "YOYOPOD_ALSA_DEVICE",
    "YOYOPOD_RUST_UI_HOST_WORKER",
    "YOYOPOD_RUST_UI_WORKER",
    "YOYOPOD_RUST_MEDIA_HOST_WORKER",
    "YOYOPOD_RUST_VOIP_HOST_WORKER",
];

struct EnvSnapshot {
    values: Vec<(&'static str, Option<OsString>)>,
}

impl Drop for EnvSnapshot {
    fn drop(&mut self) {
        for (key, value) in self.values.drain(..) {
            match value {
                Some(value) => std::env::set_var(key, value),
                None => std::env::remove_var(key),
            }
        }
    }
}

fn env_lock() -> &'static Mutex<()> {
    static ENV_LOCK: OnceLock<Mutex<()>> = OnceLock::new();
    ENV_LOCK.get_or_init(|| Mutex::new(()))
}

fn lock_env() -> MutexGuard<'static, ()> {
    env_lock().lock().unwrap_or_else(|error| error.into_inner())
}

fn clean_config_env() -> EnvSnapshot {
    let values = CONFIG_ENV_KEYS
        .iter()
        .map(|key| (*key, std::env::var_os(key)))
        .collect();
    for key in CONFIG_ENV_KEYS {
        std::env::remove_var(key);
    }
    EnvSnapshot { values }
}

fn temp_config_dir(test_name: &str) -> PathBuf {
    let unique = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("time")
        .as_nanos();
    std::env::temp_dir().join(format!("yoyopod-runtime-config-{test_name}-{unique}"))
}

fn write(path: &Path, contents: &str) {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).expect("parent dir");
    }
    fs::write(path, contents).expect("write config");
}

#[test]
fn loads_minimal_worker_and_audio_config() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("minimal");
    write(
        &dir.join("app/core.yaml"),
        r#"
logging:
  pid_file: "/tmp/yoyopod-test.pid"
"#,
    );
    write(
        &dir.join("device/hardware.yaml"),
        r#"
display:
  brightness: 65
communication_audio:
  playback_device_id: "ALSA: wm8960-soundcard"
  ringer_device_id: "ALSA: wm8960-soundcard"
  capture_device_id: "ALSA: wm8960-soundcard"
  media_device_id: "ALSA: wm8960-soundcard"
  mic_gain: 82
media_audio:
  alsa_device: "alsa/default"
"#,
    );
    write(
        &dir.join("audio/music.yaml"),
        r#"
audio:
  music_dir: "/srv/music"
  mpv_socket: "/tmp/yoyopod-mpv.sock"
  mpv_binary: "mpv"
  recent_tracks_file: "data/media/recent_tracks.json"
  default_volume: 77
"#,
    );
    write(
        &dir.join("communication/calling.yaml"),
        r#"
calling:
  account:
    sip_server: "sip.example.test"
    sip_username: "kid"
    sip_identity: "sip:kid@sip.example.test"
    transport: "tcp"
  network:
    stun_server: "stun.example.test"
integrations:
  liblinphone_factory_config_path: "config/communication/integrations/liblinphone_factory.conf"
"#,
    );
    write(
        &dir.join("communication/messaging.yaml"),
        r#"
messaging:
  iterate_interval_ms: 25
  message_store_dir: "data/communication/messages"
  voice_note_store_dir: "data/communication/voice_notes"
  file_transfer_server_url: "https://files.example.test/lft.php"
  lime_server_url: "https://lime.example.test"
  auto_download_incoming_voice_recordings: true
"#,
    );
    write(
        &dir.join("communication/calling.secrets.yaml"),
        r#"
secrets:
  sip_password: "secret"
"#,
    );

    let config = RuntimeConfig::load(&dir).expect("load runtime config");

    assert_eq!(config.ui.brightness, 0.65);
    assert_eq!(config.media.music_dir, "/srv/music");
    assert_eq!(config.media.default_volume, 77);
    assert_eq!(config.media.alsa_device, "alsa/default");
    assert_eq!(config.voip.sip_server, "sip.example.test");
    assert_eq!(config.voip.sip_password, "secret");
    assert_eq!(config.voip.iterate_interval_ms, 25);
    assert_eq!(config.pid_file, "/tmp/yoyopod-test.pid");
    assert_eq!(config.log_file, "logs/yoyopod.log");
    assert_eq!(
        config.worker_paths.ui,
        "yoyopod_rs/ui-host/build/yoyopod-ui-host"
    );
}

#[test]
fn missing_files_fall_back_to_dev_defaults() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("defaults");
    fs::create_dir_all(&dir).expect("config dir");

    let config = RuntimeConfig::load(&dir).expect("load defaults");

    assert_eq!(config.media.music_dir, "/home/pi/Music");
    assert_eq!(config.media.mpv_binary, "mpv");
    assert_eq!(config.voip.transport, "tcp");
    assert_eq!(config.ui.hardware, "auto");
    assert_eq!(config.pid_file, "/tmp/yoyopod.pid");
    assert_eq!(config.log_file, "logs/yoyopod.log");
}

#[test]
fn log_file_loads_from_yaml_and_env() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("log-file");
    write(
        &dir.join("app/core.yaml"),
        r#"
logging:
  file: "logs/from-yaml.log"
"#,
    );

    let yaml_config = RuntimeConfig::load(&dir).expect("load yaml config");
    assert_eq!(yaml_config.log_file, "logs/from-yaml.log");

    std::env::set_var("YOYOPOD_LOG_FILE", "/tmp/from-env.log");
    let env_config = RuntimeConfig::load(&dir).expect("load env config");
    assert_eq!(env_config.log_file, "/tmp/from-env.log");
}

#[test]
fn env_overrides_win_for_existing_python_config_keys() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("env-overrides");
    write(
        &dir.join("device/hardware.yaml"),
        r#"
media_audio:
  alsa_device: "yaml/alsa"
"#,
    );
    write(
        &dir.join("audio/music.yaml"),
        r#"
audio:
  music_dir: "/yaml/music"
  default_volume: 44
"#,
    );
    write(
        &dir.join("communication/calling.yaml"),
        r#"
calling:
  account:
    sip_server: "sip.yaml.test"
"#,
    );
    write(
        &dir.join("communication/calling.secrets.yaml"),
        r#"
secrets:
  sip_password: "yaml-secret"
"#,
    );
    std::env::set_var("YOYOPOD_SIP_SERVER", "sip.env.test");
    std::env::set_var("YOYOPOD_SIP_PASSWORD", "env-secret");
    std::env::set_var("YOYOPOD_MUSIC_DIR", "/env/music");
    std::env::set_var("YOYOPOD_DEFAULT_VOLUME", "33");
    std::env::set_var("YOYOPOD_ALSA_DEVICE", "env/alsa");

    let config = RuntimeConfig::load(&dir).expect("load runtime config");

    assert_eq!(config.voip.sip_server, "sip.env.test");
    assert_eq!(config.voip.sip_password, "env-secret");
    assert_eq!(config.media.music_dir, "/env/music");
    assert_eq!(config.media.default_volume, 33);
    assert_eq!(config.media.alsa_device, "env/alsa");
}

#[test]
fn invalid_env_values_fall_back_to_yaml_or_defaults() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("invalid-env");
    write(
        &dir.join("audio/music.yaml"),
        r#"
audio:
  default_volume: 66
  auto_resume_after_call: true
"#,
    );
    std::env::set_var("YOYOPOD_DEFAULT_VOLUME", "not-a-number");
    std::env::set_var("YOYOPOD_AUTO_RESUME_AFTER_CALL", "maybe");

    let config = RuntimeConfig::load(&dir).expect("load runtime config");

    assert_eq!(config.media.default_volume, 66);
    assert!(config.media.auto_resume_after_call);
}

#[test]
fn serializes_worker_payloads() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("payloads");
    write(
        &dir.join("audio/music.yaml"),
        r#"
audio:
  music_dir: "/srv/music"
  default_volume: 71
"#,
    );
    write(
        &dir.join("communication/calling.yaml"),
        r#"
calling:
  account:
    sip_server: "sip.payload.test"
    sip_identity: "sip:kid@sip.payload.test"
"#,
    );

    let config = RuntimeConfig::load(&dir).expect("load runtime config");

    assert_eq!(
        config.media.to_worker_payload(),
        json!({
            "music_dir": "/srv/music",
            "mpv_socket": "/tmp/yoyopod-mpv.sock",
            "mpv_binary": "mpv",
            "alsa_device": "default",
            "default_volume": 71,
            "recent_tracks_file": "data/media/recent_tracks.json",
            "remote_cache_dir": "data/media/remote_cache",
            "remote_cache_max_bytes": 536_870_912
        })
    );
    assert_eq!(
        config.voip.to_worker_payload()["sip_server"],
        json!("sip.payload.test")
    );
}

#[test]
fn hosted_linphone_worker_payload_uses_effective_defaults_without_storing_them() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("hosted-linphone-defaults");
    fs::create_dir_all(&dir).expect("config dir");

    let config = RuntimeConfig::load(&dir).expect("load runtime config");
    let payload = config.voip.to_worker_payload();

    assert_eq!(config.voip.sip_server, "sip.linphone.org");
    assert_eq!(config.voip.conference_factory_uri, "");
    assert_eq!(config.voip.file_transfer_server_url, "");
    assert_eq!(config.voip.lime_server_url, "");
    assert_eq!(
        payload["conference_factory_uri"],
        json!("sip:conference-factory@sip.linphone.org")
    );
    assert_eq!(
        payload["file_transfer_server_url"],
        json!("https://files.linphone.org/lft.php")
    );
    assert_eq!(
        payload["lime_server_url"],
        json!("https://lime.linphone.org/lime-server/lime-server.php")
    );
}

#[test]
fn non_linphone_worker_payload_leaves_optional_endpoints_empty() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("non-linphone-empty");
    write(
        &dir.join("communication/calling.yaml"),
        r#"
calling:
  account:
    sip_server: "sip.example.test"
"#,
    );

    let config = RuntimeConfig::load(&dir).expect("load runtime config");
    let payload = config.voip.to_worker_payload();

    assert_eq!(config.voip.file_transfer_server_url, "");
    assert_eq!(config.voip.lime_server_url, "");
    assert_eq!(payload["conference_factory_uri"], json!(""));
    assert_eq!(payload["file_transfer_server_url"], json!(""));
    assert_eq!(payload["lime_server_url"], json!(""));
}

#[test]
fn configured_optional_voip_endpoints_win_in_worker_payload() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("configured-voip-endpoints");
    write(
        &dir.join("communication/messaging.yaml"),
        r#"
messaging:
  conference_factory_uri: "sip:conference@example.test"
  file_transfer_server_url: "https://files.example.test/lft.php"
  lime_server_url: "https://lime.example.test"
"#,
    );

    let config = RuntimeConfig::load(&dir).expect("load runtime config");
    let payload = config.voip.to_worker_payload();

    assert_eq!(
        payload["conference_factory_uri"],
        json!("sip:conference@example.test")
    );
    assert_eq!(
        payload["file_transfer_server_url"],
        json!("https://files.example.test/lft.php")
    );
    assert_eq!(
        payload["lime_server_url"],
        json!("https://lime.example.test")
    );
}

#[test]
fn public_serialization_and_debug_redact_sip_secrets_but_worker_payload_keeps_them() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("redacted-secrets");
    write(
        &dir.join("communication/calling.secrets.yaml"),
        r#"
secrets:
  sip_password: "super-secret"
  sip_password_ha1: "ha1-secret"
"#,
    );

    let config = RuntimeConfig::load(&dir).expect("load runtime config");
    let serialized = serde_json::to_string(&config).expect("serialize config");
    let debug = format!("{config:?}");
    let worker_payload = config.voip.to_worker_payload();

    assert!(!serialized.contains("super-secret"));
    assert!(!serialized.contains("ha1-secret"));
    assert!(serialized.contains("<redacted>"));
    assert!(!debug.contains("super-secret"));
    assert!(!debug.contains("ha1-secret"));
    assert!(debug.contains("<redacted>"));
    assert_eq!(worker_payload["sip_password"], json!("super-secret"));
    assert_eq!(worker_payload["sip_password_ha1"], json!("ha1-secret"));
}

#[test]
fn legacy_ui_worker_env_is_used_when_host_worker_is_default_or_empty() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("legacy-ui-worker");
    fs::create_dir_all(&dir).expect("config dir");

    std::env::set_var("YOYOPOD_RUST_UI_WORKER", "/legacy/yoyopod-ui-host");
    let legacy_config = RuntimeConfig::load(&dir).expect("load runtime config");
    assert_eq!(legacy_config.worker_paths.ui, "/legacy/yoyopod-ui-host");

    std::env::set_var(
        "YOYOPOD_RUST_UI_HOST_WORKER",
        "yoyopod_rs/ui-host/build/yoyopod-ui-host",
    );
    let default_host_config = RuntimeConfig::load(&dir).expect("load runtime config");
    assert_eq!(
        default_host_config.worker_paths.ui,
        "/legacy/yoyopod-ui-host"
    );

    std::env::set_var("YOYOPOD_RUST_UI_HOST_WORKER", "/host/yoyopod-ui-host");
    let host_config = RuntimeConfig::load(&dir).expect("load runtime config");
    assert_eq!(host_config.worker_paths.ui, "/host/yoyopod-ui-host");
}
