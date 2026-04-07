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

        if _is_dataclass_type(nested_type):
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


@dataclass(slots=True)
class AppAudioConfig:
    """Audio and Mopidy integration settings."""

    music_dir: str = config_value(default="/home/pi/Music", env="YOYOPOD_MUSIC_DIR")
    mpv_socket: str = config_value(default="", env="YOYOPOD_MPV_SOCKET")
    mpv_binary: str = config_value(default="mpv", env="YOYOPOD_MPV_BINARY")
    alsa_device: str = config_value(default="default", env="YOYOPOD_ALSA_DEVICE")
    mopidy_host: str = config_value(default="localhost", env="YOYOPOD_MOPIDY_HOST")
    mopidy_port: int = config_value(default=6680, env="YOYOPOD_MOPIDY_PORT")
    auto_resume_after_call: bool = config_value(
        default=True,
        env="YOYOPOD_AUTO_RESUME_AFTER_CALL",
    )
    fade_out_duration_ms: int = config_value(default=0, env="YOYOPOD_FADE_OUT_DURATION_MS")
    fade_in_duration_ms: int = config_value(default=0, env="YOYOPOD_FADE_IN_DURATION_MS")
    default_volume: int = config_value(default=70, env="YOYOPOD_DEFAULT_VOLUME")
    ring_output_device: str = config_value(default="", env="YOYOPOD_RING_OUTPUT_DEVICE")
    speaker_test_path: str = config_value(default="speaker-test", env="YOYOPOD_SPEAKER_TEST_PATH")


@dataclass(slots=True)
class AppVoIPConfig:
    """App-level VoIP coordination settings."""

    config_file: str = config_value(default="config/voip_config.yaml", env="YOYOPOD_VOIP_CONFIG_FILE")
    priority_over_music: bool = config_value(default=True, env="YOYOPOD_PRIORITY_OVER_MUSIC")
    auto_answer: bool = config_value(default=False)
    ring_duration_seconds: int = config_value(default=30, env="YOYOPOD_RING_DURATION_SECONDS")


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


@dataclass(slots=True)
class AppPowerConfig:
    """Power-management backend settings."""

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
class YoyoPodConfig:
    """Root application configuration model loaded from yoyopod_config.yaml."""

    app: AppMetadataConfig = config_value(default_factory=AppMetadataConfig)
    audio: AppAudioConfig = config_value(default_factory=AppAudioConfig)
    voip: AppVoIPConfig = config_value(default_factory=AppVoIPConfig)
    ui: AppUiConfig = config_value(default_factory=AppUiConfig)
    input: AppInputConfig = config_value(default_factory=AppInputConfig)
    power: AppPowerConfig = config_value(default_factory=AppPowerConfig)
    display: AppDisplayConfig = config_value(default_factory=AppDisplayConfig)
    logging: AppLoggingConfig = config_value(default_factory=AppLoggingConfig)


@dataclass(slots=True)
class VoIPAccountConfig:
    """VoIP account and SIP identity settings."""

    sip_server: str = config_value(default="sip.linphone.org", env="YOYOPOD_SIP_SERVER")
    sip_username: str = config_value(default="", env="YOYOPOD_SIP_USERNAME")
    sip_password: str = config_value(default="", env="YOYOPOD_SIP_PASSWORD")
    sip_password_ha1: str = config_value(default="", env="YOYOPOD_SIP_PASSWORD_HA1")
    sip_identity: str = config_value(default="", env="YOYOPOD_SIP_IDENTITY")
    factory_config_path: str = config_value(
        default="config/liblinphone_factory.conf",
        env="YOYOPOD_LIBLINPHONE_FACTORY_CONFIG",
    )
    transport: str = config_value(default="tcp", env="YOYOPOD_SIP_TRANSPORT")
    display_name: str = "YoyoPod"


@dataclass(slots=True)
class VoIPNetworkConfig:
    """VoIP network and NAT traversal settings."""

    stun_server: str = config_value(default="stun.linphone.org", env="YOYOPOD_STUN_SERVER")
    enable_ice: bool = True


@dataclass(slots=True)
class VoIPMessagingConfig:
    """VoIP chat and voice-note settings."""

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
        default="data/messages",
        env="YOYOPOD_MESSAGE_STORE_DIR",
    )
    voice_note_store_dir: str = config_value(
        default="data/voice_notes",
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
class VoIPAudioConfig:
    """VoIP audio and device settings."""

    preferred_codec: str = "opus"
    echo_cancellation: bool = True
    mic_gain: int = 80
    speaker_volume: int = 80
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
class VoIPFileConfig:
    """Root VoIP configuration model loaded from voip_config.yaml."""

    account: VoIPAccountConfig = config_value(default_factory=VoIPAccountConfig)
    network: VoIPNetworkConfig = config_value(default_factory=VoIPNetworkConfig)
    audio: VoIPAudioConfig = config_value(default_factory=VoIPAudioConfig)
    messaging: VoIPMessagingConfig = config_value(default_factory=VoIPMessagingConfig)
    auto_answer: bool = False
    call_timeout: int = 60
