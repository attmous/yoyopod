"""Typed configuration models and YAML/env loading helpers."""

from __future__ import annotations

import os
from dataclasses import MISSING, asdict, dataclass, field, fields, is_dataclass
from pathlib import Path
from types import UnionType
from typing import Any, TypeVar, Union, get_args, get_origin, get_type_hints

import yaml

T = TypeVar("T")


def config_value(*, default: Any = MISSING, default_factory: Any = MISSING, env: str | None = None):
    """Create a dataclass field with optional environment override metadata."""

    metadata: dict[str, Any] = {}
    if env is not None:
        metadata["env"] = env

    if default is not MISSING:
        return field(default=default, metadata=metadata)
    if default_factory is not MISSING:
        return field(default_factory=default_factory, metadata=metadata)
    return field(metadata=metadata)


def load_config_model_from_yaml(model_cls: type[T], path: Path) -> T:
    """Load a typed config model from YAML with env-var overlays."""

    data: dict[str, Any] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
            if isinstance(loaded, dict):
                data = loaded
    return build_config_model(model_cls, data)


def build_config_model(model_cls: type[T], data: dict[str, Any] | None = None) -> T:
    """Build a config dataclass from raw YAML data plus environment overrides."""

    payload = data if isinstance(data, dict) else {}
    kwargs: dict[str, Any] = {}
    type_hints = get_type_hints(model_cls)

    for model_field in fields(model_cls):
        field_type = type_hints.get(model_field.name, model_field.type)
        env_name = model_field.metadata.get("env")
        env_value = os.getenv(env_name) if env_name else None

        if env_name and env_value not in (None, ""):
            kwargs[model_field.name] = _coerce_value(env_value, field_type)
            continue

        raw_value = payload.get(model_field.name, MISSING)
        nested_type = _unwrap_optional(field_type)
        if raw_value is not MISSING:
            if _is_dataclass_type(nested_type):
                nested_payload = raw_value if isinstance(raw_value, dict) else {}
                kwargs[model_field.name] = build_config_model(nested_type, nested_payload)
            else:
                kwargs[model_field.name] = _coerce_value(raw_value, field_type)
            continue

        if _is_dataclass_type(nested_type) and model_field.default is not None:
            kwargs[model_field.name] = build_config_model(nested_type, {})
        elif model_field.default is not MISSING:
            kwargs[model_field.name] = model_field.default
        elif model_field.default_factory is not MISSING:
            kwargs[model_field.name] = model_field.default_factory()
        else:
            raise TypeError(f"Missing required config field: {model_field.name}")

    return model_cls(**kwargs)


def config_to_dict(model: Any) -> dict[str, Any]:
    """Convert a config dataclass to a plain dictionary."""

    return asdict(model)


def _unwrap_optional(field_type: Any) -> Any:
    """Return the concrete type inside an Optional/Union type when possible."""

    origin = get_origin(field_type)
    if origin in (UnionType, Union):
        args = [arg for arg in get_args(field_type) if arg is not type(None)]
        if len(args) == 1:
            return args[0]
    return field_type


def _is_dataclass_type(field_type: Any) -> bool:
    """Return True when the provided type is a dataclass class."""

    return isinstance(field_type, type) and is_dataclass(field_type)


def _coerce_value(value: Any, field_type: Any) -> Any:
    """Coerce YAML/env values into the annotated field type."""

    target_type = _unwrap_optional(field_type)
    origin = get_origin(target_type)

    if target_type is Any or value is None:
        return value
    if origin in (list, dict, tuple, set):
        return value
    if target_type is bool:
        if isinstance(value, bool):
            return value
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise ValueError(f"Cannot coerce {value!r} to bool")
    if target_type is int:
        if isinstance(value, str):
            return int(value, 0)
        return int(value)
    if target_type is float:
        return float(value)
    if target_type is str:
        return str(value)
    if target_type is Path:
        return Path(value)
    return value


@dataclass(slots=True)
class AppMetadataConfig:
    """Top-level application identity settings."""

    name: str = "YoyoPod"
    version: str = "1.0.0"
    simulate: bool = config_value(default=False, env="YOYOPOD_SIMULATE")
    device_id: str = config_value(default="", env="YOYOPOD_DEVICE_ID")


@dataclass(slots=True)
class MediaMusicConfig:
    """Local music playback policy and runtime paths."""

    music_dir: str = config_value(default="/home/pi/Music", env="YOYOPOD_MUSIC_DIR")
    mpv_socket: str = config_value(default="", env="YOYOPOD_MPV_SOCKET")
    mpv_binary: str = config_value(default="mpv", env="YOYOPOD_MPV_BINARY")
    auto_resume_after_call: bool = config_value(
        default=True,
        env="YOYOPOD_AUTO_RESUME_AFTER_CALL",
    )
    fade_out_duration_ms: int = config_value(default=0, env="YOYOPOD_FADE_OUT_DURATION_MS")
    fade_in_duration_ms: int = config_value(default=0, env="YOYOPOD_FADE_IN_DURATION_MS")
    default_volume: int = config_value(default=100, env="YOYOPOD_DEFAULT_VOLUME")
    speaker_test_path: str = config_value(default="speaker-test", env="YOYOPOD_SPEAKER_TEST_PATH")
    recent_tracks_file: str = config_value(
        default="data/media/recent_tracks.json",
        env="YOYOPOD_RECENT_TRACKS_FILE",
    )


@dataclass(slots=True)
class MediaAudioConfig:
    """Device-owned playback routing for the local media domain."""

    alsa_device: str = config_value(default="default", env="YOYOPOD_ALSA_DEVICE")


@dataclass(slots=True)
class MediaConfig:
    """Composed media/audio config built from music policy and device-owned routing."""

    music: MediaMusicConfig = config_value(default_factory=MediaMusicConfig)
    audio: MediaAudioConfig = config_value(default_factory=MediaAudioConfig)


@dataclass(slots=True)
class AppUiConfig:
    """Display/UI behavior settings."""

    theme: str = "dark"
    show_album_art: bool = True
    screen_timeout_seconds: int = 300
    button_debounce_ms: int = 50


@dataclass(slots=True)
class AppInputConfig:
    """Input hardware and gesture timing settings.

    `ptt_navigation=False` keeps the Whisplay button in raw press/release mode
    for future voice/PTT features. That path is experimental today and does not
    provide a complete navigable app flow.
    """

    ptt_navigation: bool = config_value(default=True, env="YOYOPOD_PTT_NAVIGATION")
    whisplay_debounce_ms: int = config_value(default=50, env="YOYOPOD_WHISPLAY_DEBOUNCE_MS")
    whisplay_double_tap_ms: int = config_value(
        default=300,
        env="YOYOPOD_WHISPLAY_DOUBLE_TAP_MS",
    )
    whisplay_long_hold_ms: int = config_value(
        default=800,
        env="YOYOPOD_WHISPLAY_LONG_HOLD_MS",
    )
    pimoroni_gpio: PimoroniGpioInputConfig | None = None


@dataclass(slots=True)
class VoiceAssistantConfig:
    """Local voice-command and spoken-response policy."""

    commands_enabled: bool = config_value(default=True, env="YOYOPOD_VOICE_COMMANDS_ENABLED")
    ai_requests_enabled: bool = config_value(default=True, env="YOYOPOD_AI_REQUESTS_ENABLED")
    screen_read_enabled: bool = config_value(default=False, env="YOYOPOD_SCREEN_READ_ENABLED")
    stt_enabled: bool = config_value(default=True, env="YOYOPOD_STT_ENABLED")
    tts_enabled: bool = config_value(default=True, env="YOYOPOD_TTS_ENABLED")
    stt_backend: str = config_value(default="vosk", env="YOYOPOD_STT_BACKEND")
    tts_backend: str = config_value(default="espeak-ng", env="YOYOPOD_TTS_BACKEND")
    vosk_model_path: str = config_value(
        default="models/vosk-model-small-en-us",
        env="YOYOPOD_VOSK_MODEL_PATH",
    )
    vosk_model_keep_loaded: bool = config_value(
        default=True,
        env="YOYOPOD_VOSK_MODEL_KEEP_LOADED",
    )
    record_seconds: int = config_value(default=4, env="YOYOPOD_VOICE_RECORD_SECONDS")
    sample_rate_hz: int = config_value(default=16000, env="YOYOPOD_VOICE_SAMPLE_RATE_HZ")
    tts_rate_wpm: int = config_value(default=155, env="YOYOPOD_TTS_RATE_WPM")
    tts_voice: str = config_value(default="en", env="YOYOPOD_TTS_VOICE")


@dataclass(slots=True)
class VoiceAudioConfig:
    """Device-owned ALSA selectors consumed by the local voice domain."""

    speaker_device_id: str = config_value(default="", env="YOYOPOD_VOICE_SPEAKER_DEVICE")
    capture_device_id: str = config_value(default="", env="YOYOPOD_VOICE_CAPTURE_DEVICE")


@dataclass(slots=True)
class PowerConfig:
    """Power-domain backend, watchdog, and shutdown settings."""

    enabled: bool = config_value(default=True, env="YOYOPOD_POWER_ENABLED")
    backend: str = config_value(default="pisugar", env="YOYOPOD_POWER_BACKEND")
    transport: str = config_value(default="auto", env="YOYOPOD_POWER_TRANSPORT")
    socket_path: str = config_value(
        default="/tmp/pisugar-server.sock",
        env="YOYOPOD_PISUGAR_SOCKET_PATH",
    )
    tcp_host: str = config_value(default="127.0.0.1", env="YOYOPOD_PISUGAR_HOST")
    tcp_port: int = config_value(default=8423, env="YOYOPOD_PISUGAR_PORT")
    timeout_seconds: float = config_value(default=2.0, env="YOYOPOD_POWER_TIMEOUT_SECONDS")
    poll_interval_seconds: float = config_value(
        default=30.0,
        env="YOYOPOD_POWER_POLL_INTERVAL_SECONDS",
    )
    low_battery_warning_percent: float = config_value(
        default=20.0,
        env="YOYOPOD_LOW_BATTERY_WARNING_PERCENT",
    )
    low_battery_warning_cooldown_seconds: float = config_value(
        default=300.0,
        env="YOYOPOD_LOW_BATTERY_WARNING_COOLDOWN_SECONDS",
    )
    auto_shutdown_enabled: bool = config_value(
        default=True,
        env="YOYOPOD_AUTO_SHUTDOWN_ENABLED",
    )
    critical_shutdown_percent: float = config_value(
        default=10.0,
        env="YOYOPOD_CRITICAL_BATTERY_SHUTDOWN_PERCENT",
    )
    shutdown_delay_seconds: float = config_value(
        default=15.0,
        env="YOYOPOD_POWER_SHUTDOWN_DELAY_SECONDS",
    )
    shutdown_command: str = config_value(
        default="sudo -n shutdown -h now",
        env="YOYOPOD_POWER_SHUTDOWN_COMMAND",
    )
    shutdown_state_file: str = config_value(
        default="data/last_shutdown_state.json",
        env="YOYOPOD_POWER_SHUTDOWN_STATE_FILE",
    )
    watchdog_enabled: bool = config_value(
        default=False,
        env="YOYOPOD_POWER_WATCHDOG_ENABLED",
    )
    watchdog_timeout_seconds: int = config_value(
        default=60,
        env="YOYOPOD_POWER_WATCHDOG_TIMEOUT_SECONDS",
    )
    watchdog_feed_interval_seconds: float = config_value(
        default=15.0,
        env="YOYOPOD_POWER_WATCHDOG_FEED_INTERVAL_SECONDS",
    )
    watchdog_i2c_bus: int = config_value(
        default=1,
        env="YOYOPOD_POWER_WATCHDOG_I2C_BUS",
    )
    watchdog_i2c_address: int = config_value(
        default=0x57,
        env="YOYOPOD_POWER_WATCHDOG_I2C_ADDRESS",
    )
    watchdog_command_timeout_seconds: float = config_value(
        default=5.0,
        env="YOYOPOD_POWER_WATCHDOG_COMMAND_TIMEOUT_SECONDS",
    )


@dataclass(slots=True)
class GpioPin:
    """A single GPIO pin reference: chip name and line number."""

    chip: str = ""
    line: int = 0


@dataclass(slots=True)
class PimoroniGpioConfig:
    """GPIO pin mapping for driving the Pimoroni Display HAT Mini via spidev + gpiod."""

    spi_bus: int = 1
    spi_device: int = 0
    spi_speed_hz: int = 60_000_000
    dc: GpioPin | None = None
    cs: GpioPin | None = None
    backlight: GpioPin | None = None
    led_r: GpioPin | None = None
    led_g: GpioPin | None = None
    led_b: GpioPin | None = None


@dataclass(slots=True)
class PimoroniGpioInputConfig:
    """GPIO pin mapping for the Pimoroni Display HAT Mini 4-button input via gpiod."""

    button_a: GpioPin | None = None
    button_b: GpioPin | None = None
    button_x: GpioPin | None = None
    button_y: GpioPin | None = None


@dataclass(slots=True)
class NetworkConfig:
    """4G cellular modem settings owned by the network domain."""

    enabled: bool = config_value(default=False, env="YOYOPOD_NETWORK_ENABLED")
    serial_port: str = config_value(default="/dev/ttyUSB2", env="YOYOPOD_MODEM_PORT")
    ppp_port: str = config_value(default="/dev/ttyUSB3", env="YOYOPOD_MODEM_PPP_PORT")
    baud_rate: int = config_value(default=115200, env="YOYOPOD_MODEM_BAUD")
    apn: str = config_value(default="", env="YOYOPOD_MODEM_APN")
    pin: str | None = config_value(default=None)
    gps_enabled: bool = config_value(default=True, env="YOYOPOD_MODEM_GPS_ENABLED")
    ppp_timeout: int = config_value(default=30, env="YOYOPOD_MODEM_PPP_TIMEOUT")


@dataclass(slots=True)
class AppDisplayConfig:
    """Display hardware configuration."""

    hardware: str = config_value(default="auto", env="YOYOPOD_DISPLAY")
    whisplay_renderer: str = config_value(
        default="lvgl",
        env="YOYOPOD_WHISPLAY_RENDERER",
    )
    lvgl_buffer_lines: int = config_value(
        default=40,
        env="YOYOPOD_LVGL_BUFFER_LINES",
    )
    brightness: int = 80
    rotation: int = 0
    backlight_timeout_seconds: int = 60
    pimoroni_gpio: PimoroniGpioConfig | None = None


@dataclass(slots=True)
class AppLoggingConfig:
    """Logging configuration."""

    level: str = config_value(default="INFO", env="YOYOPOD_LOG_LEVEL")
    file: str = config_value(default="logs/yoyopod.log", env="YOYOPOD_LOG_FILE")
    error_file: str = config_value(
        default="logs/yoyopod_errors.log",
        env="YOYOPOD_ERROR_LOG_FILE",
    )
    pid_file: str = config_value(default="/tmp/yoyopod.pid", env="YOYOPOD_PID_FILE")
    rotation: str = config_value(default="5 MB", env="YOYOPOD_LOG_ROTATION")
    retention: str = config_value(default="3 days", env="YOYOPOD_LOG_RETENTION")
    compression: str = config_value(default="gz", env="YOYOPOD_LOG_COMPRESSION")
    error_rotation: str = config_value(default="2 MB", env="YOYOPOD_ERROR_LOG_ROTATION")
    error_retention: str = config_value(default="7 days", env="YOYOPOD_ERROR_LOG_RETENTION")
    encoding: str = config_value(default="utf-8", env="YOYOPOD_LOG_ENCODING")
    enqueue: bool = config_value(default=False, env="YOYOPOD_LOG_ENQUEUE")
    backtrace: bool = config_value(default=True, env="YOYOPOD_LOG_BACKTRACE")
    diagnose: bool = config_value(default=True, env="YOYOPOD_LOG_DIAGNOSE")


@dataclass(slots=True)
class AppDiagnosticsConfig:
    """Investigation-only runtime diagnostics for target-hardware runs."""

    responsiveness_watchdog_enabled: bool = config_value(
        default=False,
        env="YOYOPOD_RESPONSIVENESS_WATCHDOG_ENABLED",
    )
    responsiveness_watchdog_poll_interval_seconds: float = config_value(
        default=1.0,
        env="YOYOPOD_RESPONSIVENESS_WATCHDOG_POLL_INTERVAL_SECONDS",
    )
    responsiveness_stall_threshold_seconds: float = config_value(
        default=5.0,
        env="YOYOPOD_RESPONSIVENESS_STALL_THRESHOLD_SECONDS",
    )
    responsiveness_capture_cooldown_seconds: float = config_value(
        default=30.0,
        env="YOYOPOD_RESPONSIVENESS_CAPTURE_COOLDOWN_SECONDS",
    )
    responsiveness_recent_input_window_seconds: float = config_value(
        default=3.0,
        env="YOYOPOD_RESPONSIVENESS_RECENT_INPUT_WINDOW_SECONDS",
    )
    responsiveness_capture_dir: str = config_value(
        default="logs/responsiveness",
        env="YOYOPOD_RESPONSIVENESS_CAPTURE_DIR",
    )


@dataclass(slots=True)
class YoyoPodConfig:
    """Composed application-shell config built from the canonical app/device files."""

    app: AppMetadataConfig = config_value(default_factory=AppMetadataConfig)
    ui: AppUiConfig = config_value(default_factory=AppUiConfig)
    input: AppInputConfig = config_value(default_factory=AppInputConfig)
    display: AppDisplayConfig = config_value(default_factory=AppDisplayConfig)
    logging: AppLoggingConfig = config_value(default_factory=AppLoggingConfig)
    diagnostics: AppDiagnosticsConfig = config_value(default_factory=AppDiagnosticsConfig)


@dataclass(slots=True)
class CommunicationAccountConfig:
    """Non-secret SIP identity and transport settings."""

    sip_server: str = config_value(default="sip.linphone.org", env="YOYOPOD_SIP_SERVER")
    sip_username: str = config_value(default="", env="YOYOPOD_SIP_USERNAME")
    sip_identity: str = config_value(default="", env="YOYOPOD_SIP_IDENTITY")
    transport: str = config_value(default="tcp", env="YOYOPOD_SIP_TRANSPORT")
    display_name: str = "YoyoPod"


@dataclass(slots=True)
class CommunicationSecretConfig:
    """Credentials that must stay out of tracked authored config."""

    sip_password: str = config_value(default="", env="YOYOPOD_SIP_PASSWORD")
    sip_password_ha1: str = config_value(default="", env="YOYOPOD_SIP_PASSWORD_HA1")


@dataclass(slots=True)
class CommunicationNetworkConfig:
    """Communication NAT traversal and SIP network settings."""

    stun_server: str = config_value(default="stun.linphone.org", env="YOYOPOD_STUN_SERVER")
    enable_ice: bool = True


@dataclass(slots=True)
class CommunicationAudioConfig:
    """Shared device-truth used by the communication domain."""

    preferred_codec: str = "opus"
    echo_cancellation: bool = True
    mic_gain: int = 80
    playback_device_id: str = config_value(
        default="ALSA: wm8960-soundcard",
        env="YOYOPOD_PLAYBACK_DEVICE",
    )
    ringer_device_id: str = config_value(
        default="ALSA: wm8960-soundcard",
        env="YOYOPOD_RINGER_DEVICE",
    )
    capture_device_id: str = config_value(
        default="ALSA: wm8960-soundcard",
        env="YOYOPOD_CAPTURE_DEVICE",
    )
    media_device_id: str = config_value(
        default="ALSA: wm8960-soundcard",
        env="YOYOPOD_MEDIA_DEVICE",
    )
    ring_output_device: str = config_value(default="", env="YOYOPOD_RING_OUTPUT_DEVICE")


@dataclass(slots=True)
class CommunicationMessagingConfig:
    """Messaging and voice-note policy plus mutable storage paths."""

    conference_factory_uri: str = config_value(
        default="",
        env="YOYOPOD_CONFERENCE_FACTORY_URI",
    )
    file_transfer_server_url: str = config_value(
        default="",
        env="YOYOPOD_FILE_TRANSFER_SERVER_URL",
    )
    lime_server_url: str = config_value(
        default="",
        env="YOYOPOD_LIME_SERVER_URL",
    )
    iterate_interval_ms: int = config_value(
        default=20,
        env="YOYOPOD_VOIP_ITERATE_INTERVAL_MS",
    )
    message_store_dir: str = config_value(
        default="data/communication/messages",
        env="YOYOPOD_MESSAGE_STORE_DIR",
    )
    voice_note_store_dir: str = config_value(
        default="data/communication/voice_notes",
        env="YOYOPOD_VOICE_NOTE_STORE_DIR",
    )
    voice_note_max_duration_seconds: int = config_value(
        default=30,
        env="YOYOPOD_VOICE_NOTE_MAX_DURATION_SECONDS",
    )
    auto_download_incoming_voice_recordings: bool = config_value(
        default=True,
        env="YOYOPOD_AUTO_DOWNLOAD_INCOMING_VOICE_RECORDINGS",
    )


@dataclass(slots=True)
class CommunicationIntegrationsConfig:
    """Config for repo-owned communication integrations."""

    liblinphone_factory_config_path: str = config_value(
        default="config/communication/integrations/liblinphone_factory.conf",
        env="YOYOPOD_LIBLINPHONE_FACTORY_CONFIG",
    )


@dataclass(slots=True)
class CommunicationCallingConfig:
    """Calling-specific policy and runtime state paths."""

    priority_over_music: bool = config_value(default=True, env="YOYOPOD_PRIORITY_OVER_MUSIC")
    auto_answer: bool = False
    ring_duration_seconds: int = config_value(default=30, env="YOYOPOD_RING_DURATION_SECONDS")
    call_timeout: int = 60
    call_history_file: str = config_value(
        default="data/communication/call_history.json",
        env="YOYOPOD_CALL_HISTORY_FILE",
    )
    account: CommunicationAccountConfig = config_value(default_factory=CommunicationAccountConfig)
    network: CommunicationNetworkConfig = config_value(default_factory=CommunicationNetworkConfig)


@dataclass(slots=True)
class CommunicationConfig:
    """Composed communication domain config built from calling/messaging/device/secret layers."""

    calling: CommunicationCallingConfig = config_value(default_factory=CommunicationCallingConfig)
    messaging: CommunicationMessagingConfig = config_value(
        default_factory=CommunicationMessagingConfig
    )
    audio: CommunicationAudioConfig = config_value(default_factory=CommunicationAudioConfig)
    integrations: CommunicationIntegrationsConfig = config_value(
        default_factory=CommunicationIntegrationsConfig
    )
    secrets: CommunicationSecretConfig = config_value(default_factory=CommunicationSecretConfig)


@dataclass(slots=True)
class PeopleDirectoryConfig:
    """Authored paths that define where mutable people data lives."""

    contacts_file: str = config_value(
        default="data/people/contacts.yaml",
        env="YOYOPOD_PEOPLE_CONTACTS_FILE",
    )
    contacts_seed_file: str = config_value(
        default="config/people/contacts.seed.yaml",
        env="YOYOPOD_PEOPLE_CONTACTS_SEED_FILE",
    )


@dataclass(slots=True)
class CloudBackendConfig:
    """Tracked cloud/backend endpoints, polling, cache, and MQTT transport."""

    api_base_url: str = config_value(
        default="https://yoyopod.moraouf.net",
        env="YOYOPOD_CLOUD_API_BASE_URL",
    )
    auth_path: str = "/v1/auth/device"
    refresh_path: str = "/v1/auth/device/refresh"
    config_path_template: str = "/v1/devices/{device_id}/config"
    contacts_bootstrap_path_template: str = "/v1/devices/{device_id}/contacts/bootstrap"
    timeout_seconds: float = config_value(default=3.0, env="YOYOPOD_CLOUD_TIMEOUT_SECONDS")
    config_poll_interval_seconds: int = config_value(
        default=300,
        env="YOYOPOD_CLOUD_CONFIG_POLL_INTERVAL_SECONDS",
    )
    claim_retry_seconds: int = config_value(
        default=60,
        env="YOYOPOD_CLOUD_CLAIM_RETRY_SECONDS",
    )
    cache_file: str = config_value(
        default="data/cloud/config_cache.json",
        env="YOYOPOD_CLOUD_CACHE_FILE",
    )
    status_file: str = config_value(
        default="data/cloud/status.json",
        env="YOYOPOD_CLOUD_STATUS_FILE",
    )
    mqtt_broker_host: str = config_value(
        default="yoyopod.moraouf.net",
        env="YOYOPOD_CLOUD_MQTT_BROKER_HOST",
    )
    mqtt_broker_port: int = config_value(
        default=1883,
        env="YOYOPOD_CLOUD_MQTT_BROKER_PORT",
    )
    mqtt_use_tls: bool = config_value(
        default=False,
        env="YOYOPOD_CLOUD_MQTT_USE_TLS",
    )
    mqtt_username: str = config_value(
        default="",
        env="YOYOPOD_CLOUD_MQTT_USERNAME",
    )
    mqtt_password: str = config_value(
        default="",
        env="YOYOPOD_CLOUD_MQTT_PASSWORD",
    )
    mqtt_transport: str = config_value(
        default="tcp",
        env="YOYOPOD_CLOUD_MQTT_TRANSPORT",
    )
    battery_report_interval_seconds: int = config_value(
        default=60,
        env="YOYOPOD_CLOUD_BATTERY_REPORT_INTERVAL_SECONDS",
    )


@dataclass(slots=True)
class CloudSecretsConfig:
    """Runtime-only device claim credentials."""

    device_id: str = config_value(default="", env="YOYOPOD_CLOUD_DEVICE_ID")
    device_secret: str = config_value(default="", env="YOYOPOD_CLOUD_DEVICE_SECRET")


@dataclass(slots=True)
class CloudConfig:
    """Composed cloud config built from tracked backend settings plus runtime secrets."""

    backend: CloudBackendConfig = config_value(default_factory=CloudBackendConfig)
    secrets: CloudSecretsConfig = config_value(default_factory=CloudSecretsConfig)


@dataclass(slots=True)
class VoiceConfig:
    """Composed voice domain config built from voice and device-owned layers."""

    assistant: VoiceAssistantConfig = config_value(default_factory=VoiceAssistantConfig)
    audio: VoiceAudioConfig = config_value(default_factory=VoiceAudioConfig)


BackendTelemetryConfig = CloudBackendConfig

@dataclass(slots=True)
class YoyoPodRuntimeConfig:
    """One typed runtime model composed from the canonical authored config topology."""

    app: YoyoPodConfig = config_value(default_factory=YoyoPodConfig)
    media: MediaConfig = config_value(default_factory=MediaConfig)
    power: PowerConfig = config_value(default_factory=PowerConfig)
    network: NetworkConfig = config_value(default_factory=NetworkConfig)
    voice: VoiceConfig = config_value(default_factory=VoiceConfig)
    communication: CommunicationConfig = config_value(default_factory=CommunicationConfig)
    people: PeopleDirectoryConfig = config_value(default_factory=PeopleDirectoryConfig)
    cloud: CloudConfig = config_value(default_factory=CloudConfig)
