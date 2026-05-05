use std::fmt;
use std::fs;
use std::path::{Path, PathBuf};

use serde::ser::SerializeStruct;
use serde::{Deserialize, Serialize, Serializer};
use serde_json::{json, Value};
use thiserror::Error;

use crate::voice::{
    load_voice_command_dictionary, VoiceCaptureSettings, VoiceCommandSettings, VoiceSpeechSettings,
};

const LINPHONE_HOSTED_SIP_SERVER: &str = "sip.linphone.org";
const LINPHONE_HOSTED_CONFERENCE_FACTORY_URI: &str = "sip:conference-factory@sip.linphone.org";
const LINPHONE_HOSTED_FILE_TRANSFER_SERVER_URL: &str = "https://files.linphone.org/lft.php";
const LINPHONE_HOSTED_LIME_SERVER_URL: &str =
    "https://lime.linphone.org/lime-server/lime-server.php";
const RUST_UI_HOST_DEFAULT_WORKER: &str = "yoyopod_rs/ui-host/build/yoyopod-ui-host";
const RUST_CLOUD_HOST_DEFAULT_WORKER: &str = "yoyopod_rs/cloud-host/build/yoyopod-cloud-host";
const RUST_NETWORK_HOST_DEFAULT_WORKER: &str = "yoyopod_rs/network-host/build/yoyopod-network-host";
const RUST_POWER_HOST_DEFAULT_WORKER: &str = "yoyopod_rs/power-host/build/yoyopod-power-host";
const VOICE_WORKER_DEFAULT: &str = "workers/voice/go/build/yoyopod-voice-worker";

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct RuntimeConfig {
    pub ui: UiConfig,
    pub media: MediaRuntimeConfig,
    pub power: PowerRuntimeConfig,
    pub voice: VoiceRuntimeConfig,
    pub voip: VoipRuntimeConfig,
    pub people: PeopleRuntimeConfig,
    pub worker_paths: WorkerPaths,
    pub pid_file: String,
    pub log_file: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct UiConfig {
    pub hardware: String,
    pub brightness: f64,
    pub renderer: String,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct MediaRuntimeConfig {
    pub music_dir: String,
    pub mpv_socket: String,
    pub mpv_binary: String,
    pub alsa_device: String,
    pub default_volume: i32,
    pub recent_tracks_file: String,
    pub remote_cache_dir: String,
    pub remote_cache_max_bytes: u64,
    pub auto_resume_after_call: bool,
}

#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PowerRuntimeConfig {
    pub enabled: bool,
    pub low_battery_warning_percent: f64,
    pub low_battery_warning_cooldown_seconds: f64,
    pub auto_shutdown_enabled: bool,
    pub critical_shutdown_percent: f64,
    pub shutdown_delay_seconds: f64,
    pub shutdown_command: String,
    pub shutdown_state_file: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct VoiceRuntimeConfig {
    pub worker_enabled: bool,
    pub commands_enabled: bool,
    pub ai_requests_enabled: bool,
    pub activation_prefixes: Vec<String>,
    pub command_dictionary_path: String,
    pub ask_fallback_enabled: bool,
    pub sample_rate_hz: u64,
    pub request_timeout_ms: u64,
    pub max_audio_ms: u64,
    pub stt_model: String,
    pub stt_language: String,
    pub stt_prompt: String,
    pub tts_model: String,
    pub tts_voice: String,
    pub tts_instructions: String,
    pub ask_model: String,
    pub ask_instructions: String,
    pub ask_max_history_turns: usize,
    pub ask_max_response_chars: usize,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct PeopleRuntimeConfig {
    pub contacts: Vec<ContactRuntimeConfig>,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ContactRuntimeConfig {
    pub name: String,
    pub display_name: String,
    pub sip_address: String,
    pub favorite: bool,
    pub aliases: Vec<String>,
}

#[derive(Clone, PartialEq, Deserialize)]
pub struct VoipRuntimeConfig {
    pub sip_server: String,
    pub sip_username: String,
    pub sip_password: String,
    pub sip_password_ha1: String,
    pub sip_identity: String,
    pub factory_config_path: String,
    pub transport: String,
    pub stun_server: String,
    pub conference_factory_uri: String,
    pub file_transfer_server_url: String,
    pub lime_server_url: String,
    pub iterate_interval_ms: u64,
    pub message_store_dir: String,
    pub voice_note_store_dir: String,
    pub auto_download_incoming_voice_recordings: bool,
    pub playback_dev_id: String,
    pub ringer_dev_id: String,
    pub capture_dev_id: String,
    pub media_dev_id: String,
    pub mic_gain: i32,
    pub output_volume: i32,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct WorkerPaths {
    pub ui: String,
    pub cloud: String,
    pub media: String,
    pub voip: String,
    pub network: String,
    pub power: String,
    pub voice: String,
}

#[derive(Debug, Error)]
pub enum ConfigError {
    #[error("failed to read config file {path}: {source}")]
    Read {
        path: String,
        #[source]
        source: std::io::Error,
    },
    #[error("failed to parse YAML config file {path}: {source}")]
    Parse {
        path: String,
        #[source]
        source: serde_yaml::Error,
    },
}

impl RuntimeConfig {
    pub fn load(config_dir: impl AsRef<Path>) -> Result<Self, ConfigError> {
        let config_dir = config_dir.as_ref();
        let runtime_root = runtime_root_for_config_dir(config_dir);
        let app = read_yaml(config_dir.join("app/core.yaml"))?;
        let hardware = read_yaml(config_dir.join("device/hardware.yaml"))?;
        let music = read_yaml(config_dir.join("audio/music.yaml"))?;
        let calling = read_yaml(config_dir.join("communication/calling.yaml"))?;
        let messaging = read_yaml(config_dir.join("communication/messaging.yaml"))?;
        let secrets = read_yaml(config_dir.join("communication/calling.secrets.yaml"))?;
        let people = read_yaml(config_dir.join("people/directory.yaml"))?;
        let power = read_yaml(config_dir.join("power/backend.yaml"))?;
        let voice = read_yaml(config_dir.join("voice/assistant.yaml"))?;

        let default_volume = int_at_env(
            &music,
            &["audio", "default_volume"],
            100,
            "YOYOPOD_DEFAULT_VOLUME",
        );

        Ok(Self {
            ui: UiConfig {
                hardware: string_at_env(
                    &hardware,
                    &["display", "hardware"],
                    "auto",
                    "YOYOPOD_DISPLAY",
                ),
                brightness: (int_at(&hardware, &["display", "brightness"], 80) as f64 / 100.0)
                    .clamp(0.0, 1.0),
                renderer: string_at_env(
                    &hardware,
                    &["display", "whisplay_renderer"],
                    "lvgl",
                    "YOYOPOD_WHISPLAY_RENDERER",
                ),
            },
            media: MediaRuntimeConfig {
                music_dir: string_at_env(
                    &music,
                    &["audio", "music_dir"],
                    "/home/pi/Music",
                    "YOYOPOD_MUSIC_DIR",
                ),
                mpv_socket: string_at_env(
                    &music,
                    &["audio", "mpv_socket"],
                    "/tmp/yoyopod-mpv.sock",
                    "YOYOPOD_MPV_SOCKET",
                ),
                mpv_binary: string_at_env(
                    &music,
                    &["audio", "mpv_binary"],
                    "mpv",
                    "YOYOPOD_MPV_BINARY",
                ),
                alsa_device: string_at_env(
                    &hardware,
                    &["media_audio", "alsa_device"],
                    "default",
                    "YOYOPOD_ALSA_DEVICE",
                ),
                default_volume,
                recent_tracks_file: string_at_env(
                    &music,
                    &["audio", "recent_tracks_file"],
                    "data/media/recent_tracks.json",
                    "YOYOPOD_RECENT_TRACKS_FILE",
                ),
                remote_cache_dir: string_at_env(
                    &music,
                    &["audio", "remote_cache_dir"],
                    "data/media/remote_cache",
                    "YOYOPOD_REMOTE_CACHE_DIR",
                ),
                remote_cache_max_bytes: uint_at_env(
                    &music,
                    &["audio", "remote_cache_max_bytes"],
                    536_870_912,
                    "YOYOPOD_REMOTE_CACHE_MAX_BYTES",
                ),
                auto_resume_after_call: bool_at_env(
                    &music,
                    &["audio", "auto_resume_after_call"],
                    true,
                    "YOYOPOD_AUTO_RESUME_AFTER_CALL",
                ),
            },
            power: PowerRuntimeConfig {
                enabled: bool_at_env(&power, &["power", "enabled"], true, "YOYOPOD_POWER_ENABLED"),
                low_battery_warning_percent: f64_at_env(
                    &power,
                    &["power", "low_battery_warning_percent"],
                    20.0,
                    "YOYOPOD_LOW_BATTERY_WARNING_PERCENT",
                ),
                low_battery_warning_cooldown_seconds: f64_at_env(
                    &power,
                    &["power", "low_battery_warning_cooldown_seconds"],
                    300.0,
                    "YOYOPOD_LOW_BATTERY_WARNING_COOLDOWN_SECONDS",
                ),
                auto_shutdown_enabled: bool_at_env(
                    &power,
                    &["power", "auto_shutdown_enabled"],
                    true,
                    "YOYOPOD_AUTO_SHUTDOWN_ENABLED",
                ),
                critical_shutdown_percent: f64_at_env(
                    &power,
                    &["power", "critical_shutdown_percent"],
                    10.0,
                    "YOYOPOD_CRITICAL_BATTERY_SHUTDOWN_PERCENT",
                ),
                shutdown_delay_seconds: f64_at_env(
                    &power,
                    &["power", "shutdown_delay_seconds"],
                    15.0,
                    "YOYOPOD_POWER_SHUTDOWN_DELAY_SECONDS",
                ),
                shutdown_command: string_at_env(
                    &power,
                    &["power", "shutdown_command"],
                    "sudo -n shutdown -h now",
                    "YOYOPOD_POWER_SHUTDOWN_COMMAND",
                ),
                shutdown_state_file: resolve_runtime_path(
                    &runtime_root,
                    string_at_env(
                        &power,
                        &["power", "shutdown_state_file"],
                        "data/last_shutdown_state.json",
                        "YOYOPOD_POWER_SHUTDOWN_STATE_FILE",
                    ),
                ),
            },
            voice: VoiceRuntimeConfig {
                worker_enabled: bool_at_env(
                    &voice,
                    &["worker", "enabled"],
                    true,
                    "YOYOPOD_VOICE_WORKER_ENABLED",
                ),
                commands_enabled: bool_at(&voice, &["assistant", "commands_enabled"], true),
                ai_requests_enabled: bool_at(&voice, &["assistant", "ai_requests_enabled"], true),
                activation_prefixes: string_array_at(
                    &voice,
                    &["assistant", "activation_prefixes"],
                    &["yoyo", "hey yoyo"],
                ),
                command_dictionary_path: resolve_runtime_path(
                    &runtime_root,
                    string_at_env(
                        &voice,
                        &["assistant", "command_dictionary_path"],
                        "data/voice/commands.yaml",
                        "YOYOPOD_VOICE_COMMAND_DICTIONARY",
                    ),
                ),
                ask_fallback_enabled: bool_at(
                    &voice,
                    &["assistant", "command_routing", "ask_fallback_enabled"],
                    true,
                ),
                sample_rate_hz: uint_at(&voice, &["assistant", "sample_rate_hz"], 16_000),
                request_timeout_ms: seconds_at_ms(
                    &voice,
                    &["worker", "request_timeout_seconds"],
                    12.0,
                ),
                max_audio_ms: seconds_at_ms(&voice, &["worker", "max_audio_seconds"], 30.0),
                stt_model: string_at(
                    &voice,
                    &["worker", "stt_model"],
                    VoiceCaptureSettings::default().stt_model.as_str(),
                ),
                stt_language: string_at(
                    &voice,
                    &["worker", "stt_language"],
                    VoiceCaptureSettings::default().stt_language.as_str(),
                ),
                stt_prompt: string_at(
                    &voice,
                    &["worker", "stt_prompt"],
                    VoiceCaptureSettings::default().stt_prompt.as_str(),
                ),
                tts_model: string_at(
                    &voice,
                    &["worker", "tts_model"],
                    VoiceSpeechSettings::default().tts_model.as_str(),
                ),
                tts_voice: string_at(
                    &voice,
                    &["worker", "tts_voice"],
                    VoiceSpeechSettings::default().tts_voice.as_str(),
                ),
                tts_instructions: string_at(
                    &voice,
                    &["worker", "tts_instructions"],
                    VoiceSpeechSettings::default().tts_instructions.as_str(),
                ),
                ask_model: string_at(&voice, &["worker", "ask_model"], "gpt-4.1-mini"),
                ask_instructions: string_at(
                    &voice,
                    &["worker", "ask_instructions"],
                    VoiceCommandSettings::default().ask_instructions.as_str(),
                ),
                ask_max_history_turns: usize_at(&voice, &["worker", "ask_max_history_turns"], 4),
                ask_max_response_chars: usize_at(
                    &voice,
                    &["worker", "ask_max_response_chars"],
                    480,
                ),
            },
            voip: VoipRuntimeConfig {
                sip_server: string_at_env(
                    &calling,
                    &["calling", "account", "sip_server"],
                    "sip.linphone.org",
                    "YOYOPOD_SIP_SERVER",
                ),
                sip_username: string_at_env(
                    &calling,
                    &["calling", "account", "sip_username"],
                    "",
                    "YOYOPOD_SIP_USERNAME",
                ),
                sip_password: string_at_env(
                    &secrets,
                    &["secrets", "sip_password"],
                    "",
                    "YOYOPOD_SIP_PASSWORD",
                ),
                sip_password_ha1: string_at_env(
                    &secrets,
                    &["secrets", "sip_password_ha1"],
                    "",
                    "YOYOPOD_SIP_PASSWORD_HA1",
                ),
                sip_identity: string_at_env(
                    &calling,
                    &["calling", "account", "sip_identity"],
                    "",
                    "YOYOPOD_SIP_IDENTITY",
                ),
                factory_config_path: string_at_env(
                    &calling,
                    &["integrations", "liblinphone_factory_config_path"],
                    "config/communication/integrations/liblinphone_factory.conf",
                    "YOYOPOD_LIBLINPHONE_FACTORY_CONFIG",
                ),
                transport: string_at_env(
                    &calling,
                    &["calling", "account", "transport"],
                    "tcp",
                    "YOYOPOD_SIP_TRANSPORT",
                ),
                stun_server: string_at_env(
                    &calling,
                    &["calling", "network", "stun_server"],
                    "stun.linphone.org",
                    "YOYOPOD_STUN_SERVER",
                ),
                conference_factory_uri: string_at_env(
                    &messaging,
                    &["messaging", "conference_factory_uri"],
                    "",
                    "YOYOPOD_CONFERENCE_FACTORY_URI",
                ),
                file_transfer_server_url: string_at_env(
                    &messaging,
                    &["messaging", "file_transfer_server_url"],
                    "",
                    "YOYOPOD_FILE_TRANSFER_SERVER_URL",
                ),
                lime_server_url: string_at_env(
                    &messaging,
                    &["messaging", "lime_server_url"],
                    "",
                    "YOYOPOD_LIME_SERVER_URL",
                ),
                iterate_interval_ms: uint_at_env(
                    &messaging,
                    &["messaging", "iterate_interval_ms"],
                    20,
                    "YOYOPOD_VOIP_ITERATE_INTERVAL_MS",
                ),
                message_store_dir: string_at_env(
                    &messaging,
                    &["messaging", "message_store_dir"],
                    "data/communication/messages",
                    "YOYOPOD_MESSAGE_STORE_DIR",
                ),
                voice_note_store_dir: string_at_env(
                    &messaging,
                    &["messaging", "voice_note_store_dir"],
                    "data/communication/voice_notes",
                    "YOYOPOD_VOICE_NOTE_STORE_DIR",
                ),
                auto_download_incoming_voice_recordings: bool_at_env(
                    &messaging,
                    &["messaging", "auto_download_incoming_voice_recordings"],
                    true,
                    "YOYOPOD_AUTO_DOWNLOAD_INCOMING_VOICE_RECORDINGS",
                ),
                playback_dev_id: string_at_env(
                    &hardware,
                    &["communication_audio", "playback_device_id"],
                    "ALSA: wm8960-soundcard",
                    "YOYOPOD_PLAYBACK_DEVICE",
                ),
                ringer_dev_id: string_at_env(
                    &hardware,
                    &["communication_audio", "ringer_device_id"],
                    "ALSA: wm8960-soundcard",
                    "YOYOPOD_RINGER_DEVICE",
                ),
                capture_dev_id: string_at_env(
                    &hardware,
                    &["communication_audio", "capture_device_id"],
                    "ALSA: wm8960-soundcard",
                    "YOYOPOD_CAPTURE_DEVICE",
                ),
                media_dev_id: string_at_env(
                    &hardware,
                    &["communication_audio", "media_device_id"],
                    "ALSA: wm8960-soundcard",
                    "YOYOPOD_MEDIA_DEVICE",
                ),
                mic_gain: int_at(&hardware, &["communication_audio", "mic_gain"], 80),
                output_volume: default_volume,
            },
            people: PeopleRuntimeConfig {
                contacts: load_people_contacts(&runtime_root, &people)?,
            },
            worker_paths: WorkerPaths {
                ui: ui_worker_path(),
                cloud: env_or_default(
                    "YOYOPOD_RUST_CLOUD_HOST_WORKER",
                    RUST_CLOUD_HOST_DEFAULT_WORKER,
                ),
                media: env_or_default(
                    "YOYOPOD_RUST_MEDIA_HOST_WORKER",
                    "yoyopod_rs/media-host/build/yoyopod-media-host",
                ),
                voip: env_or_default(
                    "YOYOPOD_RUST_VOIP_HOST_WORKER",
                    "yoyopod_rs/voip-host/build/yoyopod-voip-host",
                ),
                network: env_or_default(
                    "YOYOPOD_RUST_NETWORK_HOST_WORKER",
                    RUST_NETWORK_HOST_DEFAULT_WORKER,
                ),
                power: env_or_default(
                    "YOYOPOD_RUST_POWER_HOST_WORKER",
                    RUST_POWER_HOST_DEFAULT_WORKER,
                ),
                voice: voice_worker_path(&voice),
            },
            pid_file: resolve_runtime_path(
                &runtime_root,
                string_at_env(
                    &app,
                    &["logging", "pid_file"],
                    "/tmp/yoyopod.pid",
                    "YOYOPOD_PID_FILE",
                ),
            ),
            log_file: resolve_runtime_path(
                &runtime_root,
                string_at_env(
                    &app,
                    &["logging", "file"],
                    "logs/yoyopod.log",
                    "YOYOPOD_LOG_FILE",
                ),
            ),
        })
    }
}

impl MediaRuntimeConfig {
    pub fn to_worker_payload(&self) -> Value {
        json!({
            "music_dir": self.music_dir,
            "mpv_socket": self.mpv_socket,
            "mpv_binary": self.mpv_binary,
            "alsa_device": self.alsa_device,
            "default_volume": self.default_volume,
            "recent_tracks_file": self.recent_tracks_file,
            "remote_cache_dir": self.remote_cache_dir,
            "remote_cache_max_bytes": self.remote_cache_max_bytes,
        })
    }
}

impl PowerRuntimeConfig {
    pub fn to_safety_config(&self) -> crate::state::PowerSafetyConfig {
        crate::state::PowerSafetyConfig {
            enabled: self.enabled,
            low_battery_warning_percent: self.low_battery_warning_percent,
            low_battery_warning_cooldown_seconds: self.low_battery_warning_cooldown_seconds,
            auto_shutdown_enabled: self.auto_shutdown_enabled,
            critical_shutdown_percent: self.critical_shutdown_percent,
            shutdown_delay_seconds: self.shutdown_delay_seconds,
            shutdown_command: self.shutdown_command.clone(),
            shutdown_state_file: self.shutdown_state_file.clone(),
        }
    }
}

impl VoiceRuntimeConfig {
    pub fn to_command_settings(&self) -> VoiceCommandSettings {
        let dictionary = load_voice_command_dictionary(&self.command_dictionary_path);
        VoiceCommandSettings {
            commands_enabled: self.commands_enabled,
            ai_requests_enabled: self.ai_requests_enabled,
            activation_prefixes: self.activation_prefixes.clone(),
            ask_fallback_enabled: self.ask_fallback_enabled,
            disabled_intents: dictionary.disabled_intents,
            command_aliases: dictionary.command_aliases,
            route_actions: dictionary.route_actions,
            ask_model: self.ask_model.clone(),
            ask_instructions: self.ask_instructions.clone(),
            ask_max_history_turns: self.ask_max_history_turns,
            ask_max_response_chars: self.ask_max_response_chars,
        }
    }

    pub fn to_capture_settings(&self) -> VoiceCaptureSettings {
        VoiceCaptureSettings {
            sample_rate_hz: self.sample_rate_hz,
            request_timeout_ms: self.request_timeout_ms,
            max_audio_ms: self.max_audio_ms,
            stt_model: self.stt_model.clone(),
            stt_language: self.stt_language.clone(),
            stt_prompt: self.stt_prompt.clone(),
        }
    }

    pub fn to_speech_settings(&self) -> VoiceSpeechSettings {
        VoiceSpeechSettings {
            sample_rate_hz: self.sample_rate_hz,
            request_timeout_ms: self.request_timeout_ms,
            tts_model: self.tts_model.clone(),
            tts_voice: self.tts_voice.clone(),
            tts_instructions: self.tts_instructions.clone(),
        }
    }
}

impl PeopleRuntimeConfig {
    pub fn to_contact_items(&self) -> Vec<crate::state::ListItem> {
        self.contacts
            .iter()
            .map(|contact| crate::state::ListItem {
                id: contact.sip_address.clone(),
                title: contact.display_name.clone(),
                subtitle: String::new(),
                icon_key: format!("mono:{}", talk_monogram(&contact.display_name)),
                aliases: contact.aliases.clone(),
            })
            .collect()
    }
}

impl VoipRuntimeConfig {
    pub fn to_worker_payload(&self) -> Value {
        json!({
            "sip_server": &self.sip_server,
            "sip_username": &self.sip_username,
            "sip_password": &self.sip_password,
            "sip_password_ha1": &self.sip_password_ha1,
            "sip_identity": &self.sip_identity,
            "factory_config_path": &self.factory_config_path,
            "transport": &self.transport,
            "stun_server": &self.stun_server,
            "conference_factory_uri": self.effective_conference_factory_uri(),
            "file_transfer_server_url": self.effective_file_transfer_server_url(),
            "lime_server_url": self.effective_lime_server_url(),
            "iterate_interval_ms": self.iterate_interval_ms,
            "message_store_dir": &self.message_store_dir,
            "voice_note_store_dir": &self.voice_note_store_dir,
            "auto_download_incoming_voice_recordings": self.auto_download_incoming_voice_recordings,
            "playback_dev_id": &self.playback_dev_id,
            "ringer_dev_id": &self.ringer_dev_id,
            "capture_dev_id": &self.capture_dev_id,
            "media_dev_id": &self.media_dev_id,
            "mic_gain": self.mic_gain,
            "output_volume": self.output_volume,
        })
    }

    fn is_linphone_hosted(&self) -> bool {
        self.sip_server
            .trim()
            .eq_ignore_ascii_case(LINPHONE_HOSTED_SIP_SERVER)
    }

    fn effective_conference_factory_uri(&self) -> String {
        self.effective_linphone_endpoint(
            &self.conference_factory_uri,
            LINPHONE_HOSTED_CONFERENCE_FACTORY_URI,
        )
    }

    fn effective_file_transfer_server_url(&self) -> String {
        self.effective_linphone_endpoint(
            &self.file_transfer_server_url,
            LINPHONE_HOSTED_FILE_TRANSFER_SERVER_URL,
        )
    }

    fn effective_lime_server_url(&self) -> String {
        self.effective_linphone_endpoint(&self.lime_server_url, LINPHONE_HOSTED_LIME_SERVER_URL)
    }

    fn effective_linphone_endpoint(&self, configured: &str, hosted_default: &str) -> String {
        let configured = configured.trim();
        if !configured.is_empty() {
            return configured.to_string();
        }
        if self.is_linphone_hosted() {
            return hosted_default.to_string();
        }
        String::new()
    }
}

impl fmt::Debug for VoipRuntimeConfig {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("VoipRuntimeConfig")
            .field("sip_server", &self.sip_server)
            .field("sip_username", &self.sip_username)
            .field("sip_password", &redacted_secret(&self.sip_password))
            .field("sip_password_ha1", &redacted_secret(&self.sip_password_ha1))
            .field("sip_identity", &self.sip_identity)
            .field("factory_config_path", &self.factory_config_path)
            .field("transport", &self.transport)
            .field("stun_server", &self.stun_server)
            .field("conference_factory_uri", &self.conference_factory_uri)
            .field("file_transfer_server_url", &self.file_transfer_server_url)
            .field("lime_server_url", &self.lime_server_url)
            .field("iterate_interval_ms", &self.iterate_interval_ms)
            .field("message_store_dir", &self.message_store_dir)
            .field("voice_note_store_dir", &self.voice_note_store_dir)
            .field(
                "auto_download_incoming_voice_recordings",
                &self.auto_download_incoming_voice_recordings,
            )
            .field("playback_dev_id", &self.playback_dev_id)
            .field("ringer_dev_id", &self.ringer_dev_id)
            .field("capture_dev_id", &self.capture_dev_id)
            .field("media_dev_id", &self.media_dev_id)
            .field("mic_gain", &self.mic_gain)
            .field("output_volume", &self.output_volume)
            .finish()
    }
}

impl Serialize for VoipRuntimeConfig {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        let mut state = serializer.serialize_struct("VoipRuntimeConfig", 21)?;
        state.serialize_field("sip_server", &self.sip_server)?;
        state.serialize_field("sip_username", &self.sip_username)?;
        state.serialize_field("sip_password", redacted_secret(&self.sip_password))?;
        state.serialize_field("sip_password_ha1", redacted_secret(&self.sip_password_ha1))?;
        state.serialize_field("sip_identity", &self.sip_identity)?;
        state.serialize_field("factory_config_path", &self.factory_config_path)?;
        state.serialize_field("transport", &self.transport)?;
        state.serialize_field("stun_server", &self.stun_server)?;
        state.serialize_field("conference_factory_uri", &self.conference_factory_uri)?;
        state.serialize_field("file_transfer_server_url", &self.file_transfer_server_url)?;
        state.serialize_field("lime_server_url", &self.lime_server_url)?;
        state.serialize_field("iterate_interval_ms", &self.iterate_interval_ms)?;
        state.serialize_field("message_store_dir", &self.message_store_dir)?;
        state.serialize_field("voice_note_store_dir", &self.voice_note_store_dir)?;
        state.serialize_field(
            "auto_download_incoming_voice_recordings",
            &self.auto_download_incoming_voice_recordings,
        )?;
        state.serialize_field("playback_dev_id", &self.playback_dev_id)?;
        state.serialize_field("ringer_dev_id", &self.ringer_dev_id)?;
        state.serialize_field("capture_dev_id", &self.capture_dev_id)?;
        state.serialize_field("media_dev_id", &self.media_dev_id)?;
        state.serialize_field("mic_gain", &self.mic_gain)?;
        state.serialize_field("output_volume", &self.output_volume)?;
        state.end()
    }
}

fn read_yaml(path: PathBuf) -> Result<Value, ConfigError> {
    if !path.exists() {
        return Ok(json!({}));
    }

    let text = fs::read_to_string(&path).map_err(|source| ConfigError::Read {
        path: path.display().to_string(),
        source,
    })?;
    let value: serde_yaml::Value =
        serde_yaml::from_str(&text).map_err(|source| ConfigError::Parse {
            path: path.display().to_string(),
            source,
        })?;

    Ok(serde_json::to_value(value).unwrap_or_else(|_| json!({})))
}

fn load_people_contacts(
    runtime_root: &Path,
    directory: &Value,
) -> Result<Vec<ContactRuntimeConfig>, ConfigError> {
    let contacts_file = PathBuf::from(resolve_runtime_path(
        runtime_root,
        string_at(directory, &["contacts_file"], "data/people/contacts.yaml"),
    ));
    let contacts_seed_file = PathBuf::from(resolve_runtime_path(
        runtime_root,
        string_at(
            directory,
            &["contacts_seed_file"],
            "config/people/contacts.seed.yaml",
        ),
    ));
    let source = if contacts_file.exists() {
        contacts_file
    } else {
        contacts_seed_file
    };
    let payload = read_yaml(source)?;
    Ok(contact_configs_from_value(&payload))
}

fn contact_configs_from_value(value: &Value) -> Vec<ContactRuntimeConfig> {
    let Some(contacts) = value.get("contacts").and_then(Value::as_array) else {
        return Vec::new();
    };
    let contacts = contacts
        .iter()
        .filter_map(contact_config_from_value)
        .collect::<Vec<_>>();
    let (mut favorites, others): (Vec<_>, Vec<_>) =
        contacts.into_iter().partition(|contact| contact.favorite);
    favorites.extend(others);
    favorites
}

fn contact_config_from_value(value: &Value) -> Option<ContactRuntimeConfig> {
    if !value.is_object() {
        return None;
    }
    let can_call = value
        .get("can_call")
        .and_then(Value::as_bool)
        .unwrap_or(true);
    if !can_call {
        return None;
    }
    let sip_address = string_field(value, "sip_address")?;
    if sip_address.trim().is_empty() {
        return None;
    }
    let name = string_field(value, "name").unwrap_or_else(|| sip_address.clone());
    let notes = string_field(value, "notes").unwrap_or_default();
    let display_name = if notes.trim().is_empty() {
        name.clone()
    } else {
        notes.trim().to_string()
    };
    Some(ContactRuntimeConfig {
        name,
        display_name,
        sip_address,
        favorite: value
            .get("favorite")
            .and_then(Value::as_bool)
            .unwrap_or(false),
        aliases: string_array_field(value, "aliases"),
    })
}

fn at_path<'a>(value: &'a Value, path: &[&str]) -> Option<&'a Value> {
    let mut current = value;
    for segment in path {
        current = current.get(*segment)?;
    }
    Some(current)
}

fn string_field(value: &Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(Value::as_str)
        .map(str::trim)
        .filter(|text| !text.is_empty())
        .map(str::to_string)
}

fn string_at_env(value: &Value, path: &[&str], default: &str, env: &str) -> String {
    env_string(env).unwrap_or_else(|| string_at(value, path, default))
}

fn int_at_env(value: &Value, path: &[&str], default: i32, env: &str) -> i32 {
    env_string(env)
        .and_then(|text| text.parse::<i32>().ok())
        .unwrap_or_else(|| int_at(value, path, default))
}

fn uint_at_env(value: &Value, path: &[&str], default: u64, env: &str) -> u64 {
    env_string(env)
        .and_then(|text| text.parse::<u64>().ok())
        .unwrap_or_else(|| uint_at(value, path, default))
}

fn string_array_field(value: &Value, key: &str) -> Vec<String> {
    value
        .get(key)
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::trim)
                .filter(|item| !item.is_empty())
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default()
}

fn f64_at_env(value: &Value, path: &[&str], default: f64, env: &str) -> f64 {
    env_string(env)
        .and_then(|text| text.parse::<f64>().ok())
        .unwrap_or_else(|| f64_at(value, path, default))
}

fn bool_at_env(value: &Value, path: &[&str], default: bool, env: &str) -> bool {
    env_string(env)
        .and_then(|text| parse_bool(&text))
        .unwrap_or_else(|| bool_at(value, path, default))
}

fn string_at(value: &Value, path: &[&str], default: &str) -> String {
    at_path(value, path)
        .and_then(Value::as_str)
        .filter(|text| !text.trim().is_empty())
        .unwrap_or(default)
        .to_string()
}

fn int_at(value: &Value, path: &[&str], default: i32) -> i32 {
    at_path(value, path)
        .and_then(|value| {
            value
                .as_i64()
                .and_then(|number| i32::try_from(number).ok())
                .or_else(|| value.as_str()?.trim().parse::<i32>().ok())
        })
        .unwrap_or(default)
}

fn uint_at(value: &Value, path: &[&str], default: u64) -> u64 {
    at_path(value, path)
        .and_then(|value| {
            value
                .as_u64()
                .or_else(|| value.as_str()?.trim().parse::<u64>().ok())
        })
        .unwrap_or(default)
}

fn usize_at(value: &Value, path: &[&str], default: usize) -> usize {
    uint_at(value, path, default as u64)
        .try_into()
        .unwrap_or(default)
}

fn f64_at(value: &Value, path: &[&str], default: f64) -> f64 {
    at_path(value, path)
        .and_then(|value| {
            value
                .as_f64()
                .or_else(|| value.as_str()?.trim().parse::<f64>().ok())
        })
        .unwrap_or(default)
}

fn seconds_at_ms(value: &Value, path: &[&str], default_seconds: f64) -> u64 {
    let seconds = f64_at(value, path, default_seconds);
    if !seconds.is_finite() || seconds <= 0.0 {
        return (default_seconds * 1000.0).round() as u64;
    }
    (seconds * 1000.0).round() as u64
}

fn string_array_at(value: &Value, path: &[&str], default: &[&str]) -> Vec<String> {
    at_path(value, path)
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::trim)
                .filter(|text| !text.is_empty())
                .map(str::to_string)
                .collect::<Vec<_>>()
        })
        .filter(|items| !items.is_empty())
        .unwrap_or_else(|| default.iter().map(|value| (*value).to_string()).collect())
}

fn bool_at(value: &Value, path: &[&str], default: bool) -> bool {
    at_path(value, path)
        .and_then(|value| value.as_bool().or_else(|| parse_bool(value.as_str()?)))
        .unwrap_or(default)
}

fn parse_bool(value: &str) -> Option<bool> {
    match value.trim().to_ascii_lowercase().as_str() {
        "1" | "true" | "yes" | "on" => Some(true),
        "0" | "false" | "no" | "off" => Some(false),
        _ => None,
    }
}

fn env_string(name: &str) -> Option<String> {
    std::env::var(name)
        .ok()
        .map(|value| value.trim().to_string())
        .filter(|value| !value.is_empty())
}

fn ui_worker_path() -> String {
    match env_string("YOYOPOD_RUST_UI_HOST_WORKER") {
        Some(value) if value != RUST_UI_HOST_DEFAULT_WORKER => value,
        _ => env_or_default("YOYOPOD_RUST_UI_WORKER", RUST_UI_HOST_DEFAULT_WORKER),
    }
}

fn voice_worker_path(voice: &Value) -> String {
    if let Some(value) = env_string("YOYOPOD_RUST_VOICE_WORKER") {
        return value;
    }
    string_array_at(voice, &["worker", "argv"], &[VOICE_WORKER_DEFAULT])
        .into_iter()
        .next()
        .unwrap_or_else(|| VOICE_WORKER_DEFAULT.to_string())
}

fn env_or_default(name: &str, default: &str) -> String {
    env_string(name).unwrap_or_else(|| default.to_string())
}

fn runtime_root_for_config_dir(config_dir: &Path) -> PathBuf {
    let config_dir = if config_dir.is_absolute() {
        config_dir.to_path_buf()
    } else {
        std::env::current_dir()
            .map(|cwd| cwd.join(config_dir))
            .unwrap_or_else(|_| config_dir.to_path_buf())
    };
    config_dir
        .parent()
        .map(Path::to_path_buf)
        .unwrap_or(config_dir)
}

fn resolve_runtime_path(runtime_root: &Path, raw_path: String) -> String {
    let path = Path::new(&raw_path);
    if path.is_absolute() || raw_path.starts_with('/') {
        raw_path
    } else {
        runtime_root.join(path).to_string_lossy().to_string()
    }
}

fn redacted_secret(value: &str) -> &'static str {
    if value.trim().is_empty() {
        ""
    } else {
        "<redacted>"
    }
}

fn talk_monogram(text: &str) -> String {
    let words = text.split_whitespace().collect::<Vec<_>>();
    if words.is_empty() {
        return "T".to_string();
    }

    let mut result = String::new();
    if words.len() > 1 {
        for word in words.iter().take(2) {
            if let Some(letter) = word.chars().next() {
                result.push(letter.to_ascii_uppercase());
            }
        }
    } else {
        for letter in words[0].chars().take(2) {
            result.push(letter.to_ascii_uppercase());
        }
    }

    if result.is_empty() {
        "T".to_string()
    } else {
        result
    }
}
