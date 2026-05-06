use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::{Mutex, MutexGuard, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::json;
use yoyopod_runtime::config::{resolve_worker_program_for_config_dir, RuntimeConfig};
use yoyopod_runtime::voice::{route_voice_transcript, VoiceCommandIntent, VoiceRouteKind};

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
    "YOYOPOD_RUST_CLOUD_HOST_WORKER",
    "YOYOPOD_RUST_MEDIA_HOST_WORKER",
    "YOYOPOD_RUST_POWER_HOST_WORKER",
    "YOYOPOD_RUST_VOIP_HOST_WORKER",
    "YOYOPOD_RUST_NETWORK_HOST_WORKER",
    "YOYOPOD_RUST_VOICE_WORKER",
    "YOYOPOD_VOICE_WORKER_ENABLED",
    "YOYOPOD_VOICE_COMMAND_DICTIONARY",
    "YOYOPOD_POWER_ENABLED",
    "YOYOPOD_LOW_BATTERY_WARNING_PERCENT",
    "YOYOPOD_LOW_BATTERY_WARNING_COOLDOWN_SECONDS",
    "YOYOPOD_AUTO_SHUTDOWN_ENABLED",
    "YOYOPOD_CRITICAL_BATTERY_SHUTDOWN_PERCENT",
    "YOYOPOD_POWER_SHUTDOWN_DELAY_SECONDS",
    "YOYOPOD_POWER_SHUTDOWN_COMMAND",
    "YOYOPOD_POWER_SHUTDOWN_STATE_FILE",
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

fn yaml_path(path: &Path) -> String {
    path.to_string_lossy().replace('\\', "/")
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
    assert!(Path::new(&config.log_file).ends_with(Path::new("logs/yoyopod.log")));
    assert!(Path::new(&config.log_file).is_absolute());
    assert_eq!(config.worker_paths.ui, "device/ui/build/yoyopod-ui-host");
    assert_eq!(
        config.worker_paths.cloud,
        "device/cloud/build/yoyopod-cloud-host"
    );
    assert_eq!(
        config.worker_paths.network,
        "device/network/build/yoyopod-network-host"
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
    assert!(Path::new(&config.log_file).ends_with(Path::new("logs/yoyopod.log")));
    assert!(Path::new(&config.log_file).is_absolute());
}

#[test]
fn relative_worker_programs_resolve_against_packaged_app_root() {
    let root = temp_config_dir("slot-worker-root");
    let config_dir = root.join("config");
    fs::create_dir_all(root.join("app/device")).expect("packaged app dir");

    let resolved =
        resolve_worker_program_for_config_dir(&config_dir, "device/ui/build/yoyopod-ui-host");

    assert_eq!(
        PathBuf::from(resolved),
        root.join("app/device/ui/build/yoyopod-ui-host")
    );
}

#[test]
fn relative_worker_programs_resolve_against_checkout_root_without_packaged_app() {
    let root = temp_config_dir("checkout-worker-root");
    let config_dir = root.join("config");

    let resolved =
        resolve_worker_program_for_config_dir(&config_dir, "device/ui/build/yoyopod-ui-host");

    assert_eq!(
        PathBuf::from(resolved),
        root.join("device/ui/build/yoyopod-ui-host")
    );
}

#[test]
fn worker_program_resolution_preserves_absolute_paths_and_path_commands() {
    let root = temp_config_dir("worker-path-command");
    let config_dir = root.join("config");
    fs::create_dir_all(root.join("app/device")).expect("packaged app dir");

    assert_eq!(
        resolve_worker_program_for_config_dir(&config_dir, "/opt/yoyopod/yoyopod-ui-host"),
        "/opt/yoyopod/yoyopod-ui-host"
    );
    assert_eq!(
        resolve_worker_program_for_config_dir(&config_dir, "yoyopod-ui-host"),
        "yoyopod-ui-host"
    );
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
    assert!(Path::new(&yaml_config.log_file).ends_with(Path::new("logs/from-yaml.log")));
    assert!(Path::new(&yaml_config.log_file).is_absolute());

    std::env::set_var("YOYOPOD_LOG_FILE", "/tmp/from-env.log");
    let env_config = RuntimeConfig::load(&dir).expect("load env config");
    assert_eq!(env_config.log_file, "/tmp/from-env.log");
}

#[test]
fn relative_logging_paths_resolve_against_config_root_parent() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let root = temp_config_dir("relative-logging-root");
    let config_dir = root.join("config");
    write(
        &config_dir.join("app/core.yaml"),
        r#"
logging:
  pid_file: "run/yoyopod.pid"
  file: "logs/runtime.log"
"#,
    );

    let config = RuntimeConfig::load(&config_dir).expect("load runtime config");

    assert_eq!(
        PathBuf::from(&config.pid_file),
        root.join("run/yoyopod.pid")
    );
    assert_eq!(
        PathBuf::from(&config.log_file),
        root.join("logs/runtime.log")
    );
}

#[test]
fn absolute_logging_paths_stay_absolute() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let root = temp_config_dir("absolute-logging-root");
    let config_dir = root.join("config");
    let pid_file = root.join("absolute/yoyopod.pid");
    let log_file = root.join("absolute/yoyopod.log");
    write(
        &config_dir.join("app/core.yaml"),
        &format!(
            r#"
logging:
  pid_file: "{}"
  file: "{}"
"#,
            yaml_path(&pid_file),
            yaml_path(&log_file)
        ),
    );

    let config = RuntimeConfig::load(&config_dir).expect("load runtime config");

    assert_eq!(PathBuf::from(&config.pid_file), pid_file);
    assert_eq!(PathBuf::from(&config.log_file), log_file);
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
fn people_contacts_load_from_mutable_file_or_seed_with_python_display_names() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let root = temp_config_dir("people-contacts");
    let config_dir = root.join("config");
    write(
        &config_dir.join("people/directory.yaml"),
        r#"
contacts_file: "data/people/contacts.yaml"
contacts_seed_file: "config/people/contacts.seed.yaml"
"#,
    );
    write(
        &config_dir.join("people/contacts.seed.yaml"),
        r#"
contacts:
  - name: "Hagar"
    sip_address: "sip:hagar@example.test"
    favorite: true
    notes: "Mama"
    aliases:
      - "mom"
      - "mommy"
  - name: "Ignored"
    sip_address: ""
  - name: "Baba"
    sip_address: "sip:baba@example.test"
    favorite: false
"#,
    );

    let seed_config = RuntimeConfig::load(&config_dir).expect("load seed contacts");

    assert_eq!(seed_config.people.contacts.len(), 2);
    assert_eq!(seed_config.people.contacts[0].name, "Hagar");
    assert_eq!(seed_config.people.contacts[0].display_name, "Mama");
    assert_eq!(
        seed_config.people.contacts[0].aliases,
        vec!["mom".to_string(), "mommy".to_string()]
    );
    assert_eq!(seed_config.people.to_contact_items()[0].icon_key, "mono:MA");

    write(
        &root.join("data/people/contacts.yaml"),
        r#"
contacts:
  - name: "Local"
    sip_address: "sip:local@example.test"
    notes: "Local Name"
"#,
    );
    let mutable_config = RuntimeConfig::load(&config_dir).expect("load mutable contacts");

    assert_eq!(mutable_config.people.contacts.len(), 1);
    assert_eq!(mutable_config.people.contacts[0].display_name, "Local Name");
    assert_eq!(
        mutable_config.people.contacts[0].sip_address,
        "sip:local@example.test"
    );
}

#[test]
fn voice_assistant_config_loads_command_routing_and_worker_defaults() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("voice-assistant");
    write(
        &dir.join("voice/assistant.yaml"),
        r#"
assistant:
  commands_enabled: true
  ai_requests_enabled: false
  activation_prefixes:
    - "yoyo"
    - "hey yoyo"
  command_routing:
    ask_fallback_enabled: false
  worker:
    ignored: true
worker:
  enabled: true
  provider: "mock"
  argv:
    - "device/speech/build/yoyopod-speech-host"
  request_timeout_seconds: 12.0
  max_audio_seconds: 30.0
  stt_model: "gpt-4o-mini-transcribe"
  stt_language: "en"
  stt_prompt: "Transcribe this YoYoPod voice command."
  tts_model: "gpt-4o-mini-tts"
  tts_voice: "coral"
  tts_instructions: "Speak warmly for a child."
  ask_model: "gpt-4.1-mini"
  ask_max_history_turns: 3
  ask_max_response_chars: 321
  ask_instructions: "Kid-safe answers."
"#,
    );

    let config = RuntimeConfig::load(&dir).expect("load runtime config");

    assert!(config.voice.worker_enabled);
    assert!(config.voice.commands_enabled);
    assert!(!config.voice.ai_requests_enabled);
    assert!(!config.voice.ask_fallback_enabled);
    assert_eq!(
        config.voice.activation_prefixes,
        vec!["yoyo".to_string(), "hey yoyo".to_string()]
    );
    assert_eq!(config.voice.ask_model, "gpt-4.1-mini");
    assert_eq!(config.voice.request_timeout_ms, 12_000);
    assert_eq!(config.voice.max_audio_ms, 30_000);
    assert_eq!(config.voice.sample_rate_hz, 16_000);
    assert_eq!(config.voice.stt_model, "gpt-4o-mini-transcribe");
    assert_eq!(config.voice.stt_language, "en");
    assert_eq!(
        config.voice.stt_prompt,
        "Transcribe this YoYoPod voice command."
    );
    assert_eq!(config.voice.tts_model, "gpt-4o-mini-tts");
    assert_eq!(config.voice.tts_voice, "coral");
    assert_eq!(config.voice.tts_instructions, "Speak warmly for a child.");
    assert_eq!(config.voice.ask_max_history_turns, 3);
    assert_eq!(config.voice.ask_max_response_chars, 321);
    assert_eq!(config.voice.ask_instructions, "Kid-safe answers.");
    assert_eq!(
        config.worker_paths.voice,
        "device/speech/build/yoyopod-speech-host"
    );
}

#[test]
fn voice_command_dictionary_extends_rust_command_router() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let root = temp_config_dir("voice-command-dictionary");
    let config_dir = root.join("config");
    write(
        &config_dir.join("voice/assistant.yaml"),
        r#"
assistant:
  commands_enabled: true
  ai_requests_enabled: true
  activation_prefixes:
    - "yoyo"
    - "hey yoyo"
  command_dictionary_path: "data/voice/commands.yaml"
  command_routing:
    ask_fallback_enabled: true
worker:
  enabled: true
"#,
    );
    write(
        &root.join("data/voice/commands.yaml"),
        r#"
version: 1
intents:
  volume_up:
    aliases:
      - "boost sound"
actions:
  open_talk:
    aliases:
      - "open talk"
    route: "open_talk"
"#,
    );

    let config = RuntimeConfig::load(&config_dir).expect("load runtime config");
    let settings = config.voice.to_command_settings();

    let command = route_voice_transcript("hey yoyo boost sound", &settings);
    assert_eq!(command.kind, VoiceRouteKind::Command);
    assert_eq!(
        command.command.expect("command").intent,
        VoiceCommandIntent::VolumeUp
    );

    let action = route_voice_transcript("hey yoyo open talk", &settings);
    assert_eq!(action.reason, "action_match");
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
        "device/ui/build/yoyopod-ui-host",
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

#[test]
fn network_worker_path_can_be_overridden_by_env() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("network-worker-env");
    fs::create_dir_all(&dir).expect("config dir");

    std::env::set_var(
        "YOYOPOD_RUST_NETWORK_HOST_WORKER",
        "/host/yoyopod-network-host",
    );

    let config = RuntimeConfig::load(&dir).expect("load runtime config");

    assert_eq!(config.worker_paths.network, "/host/yoyopod-network-host");
}

#[test]
fn cloud_worker_path_can_be_overridden_by_env() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("cloud-worker-env");
    fs::create_dir_all(&dir).expect("config dir");

    std::env::set_var("YOYOPOD_RUST_CLOUD_HOST_WORKER", "/host/yoyopod-cloud-host");

    let config = RuntimeConfig::load(&dir).expect("load runtime config");

    assert_eq!(config.worker_paths.cloud, "/host/yoyopod-cloud-host");
}

#[test]
fn power_worker_path_can_be_overridden_by_env() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("power-worker-env");
    fs::create_dir_all(&dir).expect("config dir");

    std::env::set_var("YOYOPOD_RUST_POWER_HOST_WORKER", "/host/yoyopod-power-host");

    let config = RuntimeConfig::load(&dir).expect("load runtime config");

    assert_eq!(config.worker_paths.power, "/host/yoyopod-power-host");
}

#[test]
fn power_policy_config_loads_from_yaml_and_env() {
    let _lock = lock_env();
    let _env = clean_config_env();
    let dir = temp_config_dir("power-policy");
    write(
        &dir.join("power/backend.yaml"),
        r#"
power:
  enabled: true
  low_battery_warning_percent: 18.0
  low_battery_warning_cooldown_seconds: 120.0
  auto_shutdown_enabled: true
  critical_shutdown_percent: 7.5
  shutdown_delay_seconds: 20.0
  shutdown_command: "test-poweroff --now"
  shutdown_state_file: "data/custom_shutdown_state.json"
"#,
    );

    let yaml_config = RuntimeConfig::load(&dir).expect("load yaml power policy");

    assert!(yaml_config.power.enabled);
    assert_eq!(yaml_config.power.low_battery_warning_percent, 18.0);
    assert_eq!(
        yaml_config.power.low_battery_warning_cooldown_seconds,
        120.0
    );
    assert!(yaml_config.power.auto_shutdown_enabled);
    assert_eq!(yaml_config.power.critical_shutdown_percent, 7.5);
    assert_eq!(yaml_config.power.shutdown_delay_seconds, 20.0);
    assert_eq!(
        serde_json::to_value(&yaml_config.power).expect("power json")["shutdown_command"],
        "test-poweroff --now"
    );
    assert!(Path::new(&yaml_config.power.shutdown_state_file)
        .ends_with(Path::new("data/custom_shutdown_state.json")));
    assert!(Path::new(&yaml_config.power.shutdown_state_file).is_absolute());

    std::env::set_var("YOYOPOD_LOW_BATTERY_WARNING_PERCENT", "16.5");
    std::env::set_var("YOYOPOD_AUTO_SHUTDOWN_ENABLED", "false");
    std::env::set_var("YOYOPOD_POWER_SHUTDOWN_DELAY_SECONDS", "9.5");
    std::env::set_var("YOYOPOD_POWER_SHUTDOWN_COMMAND", "test-poweroff --env");

    let env_config = RuntimeConfig::load(&dir).expect("load env power policy");

    assert_eq!(env_config.power.low_battery_warning_percent, 16.5);
    assert!(!env_config.power.auto_shutdown_enabled);
    assert_eq!(env_config.power.shutdown_delay_seconds, 9.5);
    assert_eq!(
        serde_json::to_value(&env_config.power).expect("power json")["shutdown_command"],
        "test-poweroff --env"
    );
}
