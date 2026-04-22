"""Power and GPIO configuration models."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.config.models.core import config_value


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
