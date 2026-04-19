"""Application-level configuration models."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.config.models.core import config_value
from yoyopod.config.models.power import PimoroniGpioConfig, PimoroniGpioInputConfig


@dataclass(slots=True)
class AppMetadataConfig:
    """Top-level application identity settings."""

    name: str = "YoyoPod"
    version: str = "1.0.0"
    simulate: bool = config_value(default=False, env="YOYOPOD_SIMULATE")
    device_id: str = config_value(default="", env="YOYOPOD_DEVICE_ID")


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
    """Composed application-shell config built from canonical app/device files."""

    app: AppMetadataConfig = config_value(default_factory=AppMetadataConfig)
    ui: AppUiConfig = config_value(default_factory=AppUiConfig)
    input: AppInputConfig = config_value(default_factory=AppInputConfig)
    display: AppDisplayConfig = config_value(default_factory=AppDisplayConfig)
    logging: AppLoggingConfig = config_value(default_factory=AppLoggingConfig)
    diagnostics: AppDiagnosticsConfig = config_value(default_factory=AppDiagnosticsConfig)
