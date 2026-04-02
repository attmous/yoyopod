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
    """Input hardware and gesture timing settings."""

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
class AppDisplayConfig:
    """Display hardware configuration."""

    hardware: str = config_value(default="auto", env="YOYOPOD_DISPLAY")
    brightness: int = 80
    rotation: int = 0
    backlight_timeout_seconds: int = 60


@dataclass(slots=True)
class AppLoggingConfig:
    """Logging configuration."""

    level: str = config_value(default="INFO", env="YOYOPOD_LOG_LEVEL")
    file: str = "logs/yoyopod.log"
    max_size_mb: int = 10
    backup_count: int = 3


@dataclass(slots=True)
class YoyoPodConfig:
    """Root application configuration model loaded from yoyopod_config.yaml."""

    app: AppMetadataConfig = config_value(default_factory=AppMetadataConfig)
    audio: AppAudioConfig = config_value(default_factory=AppAudioConfig)
    voip: AppVoIPConfig = config_value(default_factory=AppVoIPConfig)
    ui: AppUiConfig = config_value(default_factory=AppUiConfig)
    input: AppInputConfig = config_value(default_factory=AppInputConfig)
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
    transport: str = config_value(default="tcp", env="YOYOPOD_SIP_TRANSPORT")
    display_name: str = "YoyoPod"


@dataclass(slots=True)
class VoIPNetworkConfig:
    """VoIP network and NAT traversal settings."""

    stun_server: str = config_value(default="stun.linphone.org", env="YOYOPOD_STUN_SERVER")
    enable_ice: bool = True


@dataclass(slots=True)
class VoIPAudioConfig:
    """VoIP audio and device settings."""

    preferred_codec: str = "opus"
    echo_cancellation: bool = True
    mic_gain: int = 80
    speaker_volume: int = 80
    playback_device_id: str = config_value(
        default="ALSA: plughw:1",
        env="YOYOPOD_PLAYBACK_DEVICE",
    )
    ringer_device_id: str = config_value(
        default="ALSA: plughw:1",
        env="YOYOPOD_RINGER_DEVICE",
    )
    capture_device_id: str = config_value(
        default="ALSA: plughw:1",
        env="YOYOPOD_CAPTURE_DEVICE",
    )
    media_device_id: str = config_value(
        default="ALSA: plughw:1",
        env="YOYOPOD_MEDIA_DEVICE",
    )
    ring_output_device: str = config_value(default="", env="YOYOPOD_RING_OUTPUT_DEVICE")


@dataclass(slots=True)
class VoIPFileConfig:
    """Root VoIP configuration model loaded from voip_config.yaml."""

    account: VoIPAccountConfig = config_value(default_factory=VoIPAccountConfig)
    network: VoIPNetworkConfig = config_value(default_factory=VoIPNetworkConfig)
    audio: VoIPAudioConfig = config_value(default_factory=VoIPAudioConfig)
    linphonec_path: str = config_value(default="/usr/bin/linphonec", env="YOYOPOD_LINPHONEC_PATH")
    auto_answer: bool = False
    call_timeout: int = 60
