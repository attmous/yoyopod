"""PiSugar power and RTC CLI commands."""

from __future__ import annotations

import socket
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Callable

import typer

from yoyopod_cli.common import configure_logging, resolve_config_dir
from yoyopod_cli.config.models import PowerConfig

app = typer.Typer(name="power", help="PiSugar power and RTC commands.", no_args_is_help=True)
rtc_app = typer.Typer(name="rtc", help="PiSugar RTC operations.", no_args_is_help=True)
app.add_typer(rtc_app)


@dataclass(frozen=True, slots=True)
class PowerDeviceInfo:
    model: str | None = None
    firmware_version: str | None = None


@dataclass(frozen=True, slots=True)
class BatteryState:
    level_percent: float | None = None
    voltage_volts: float | None = None
    charging: bool | None = None
    power_plugged: bool | None = None
    allow_charging: bool | None = None
    output_enabled: bool | None = None
    temperature_celsius: float | None = None


@dataclass(frozen=True, slots=True)
class RTCState:
    time: datetime | None = None
    alarm_enabled: bool | None = None
    alarm_time: datetime | None = None
    alarm_repeat_mask: int | None = None
    adjust_ppm: float | None = None


@dataclass(frozen=True, slots=True)
class ShutdownState:
    safe_shutdown_level_percent: float | None = None
    safe_shutdown_delay_seconds: int | None = None


@dataclass(frozen=True, slots=True)
class PowerSnapshot:
    available: bool
    checked_at: datetime
    source: str = "pisugar"
    device: PowerDeviceInfo = field(default_factory=PowerDeviceInfo)
    battery: BatteryState = field(default_factory=BatteryState)
    rtc: RTCState = field(default_factory=RTCState)
    shutdown: ShutdownState = field(default_factory=ShutdownState)
    error: str = ""


class PowerTransportError(RuntimeError):
    """Raised when the PiSugar server cannot complete a command."""


class PiSugarClient:
    """Direct PiSugar server client used by CLI diagnostics."""

    def __init__(self, config: PowerConfig) -> None:
        self.config = config

    def get_snapshot(self) -> PowerSnapshot:
        checked_at = datetime.now()
        if not self.config.enabled:
            return PowerSnapshot(
                available=False,
                checked_at=checked_at,
                error="power backend disabled",
            )

        telemetry_success_count = 0
        errors: list[str] = []

        def read_optional(
            reader: Callable[[str], object],
            command: str,
            *,
            counts_as_telemetry: bool = True,
        ) -> object | None:
            nonlocal telemetry_success_count
            try:
                value = reader(command)
            except (PowerTransportError, ValueError) as exc:
                errors.append(f"{command}: {exc}")
                return None
            if counts_as_telemetry:
                telemetry_success_count += 1
            return value

        device = PowerDeviceInfo(
            model=_as_optional_str(
                read_optional(self._read_str, "get model", counts_as_telemetry=False)
            ),
            firmware_version=_as_optional_str(
                read_optional(
                    self._read_str,
                    "get firmware_version",
                    counts_as_telemetry=False,
                )
            ),
        )
        battery = BatteryState(
            level_percent=_as_optional_float(read_optional(self._read_float, "get battery")),
            voltage_volts=_as_optional_float(read_optional(self._read_float, "get battery_v")),
            charging=_as_optional_bool(read_optional(self._read_bool, "get battery_charging")),
            power_plugged=_as_optional_bool(
                read_optional(self._read_bool, "get battery_power_plugged")
            ),
            allow_charging=_as_optional_bool(
                read_optional(self._read_bool, "get battery_allow_charging")
            ),
            output_enabled=_as_optional_bool(
                read_optional(self._read_bool, "get battery_output_enabled")
            ),
            temperature_celsius=_as_optional_float(
                read_optional(self._read_float, "get temperature")
            ),
        )
        rtc = RTCState(
            time=_as_optional_datetime(read_optional(self._read_datetime, "get rtc_time")),
            alarm_enabled=_as_optional_bool(
                read_optional(self._read_bool, "get rtc_alarm_enabled")
            ),
            alarm_time=_as_optional_datetime(
                read_optional(self._read_datetime, "get rtc_alarm_time")
            ),
            alarm_repeat_mask=_as_optional_int(
                read_optional(self._read_int, "get alarm_repeat", counts_as_telemetry=False)
            ),
            adjust_ppm=_as_optional_float(
                read_optional(self._read_float, "get rtc_adjust_ppm", counts_as_telemetry=False)
            ),
        )
        shutdown = ShutdownState(
            safe_shutdown_level_percent=_as_optional_float(
                read_optional(self._read_float, "get safe_shutdown_level")
            ),
            safe_shutdown_delay_seconds=_as_optional_int(
                read_optional(self._read_int, "get safe_shutdown_delay")
            ),
        )

        return PowerSnapshot(
            available=telemetry_success_count > 0,
            checked_at=checked_at,
            device=device,
            battery=battery,
            rtc=rtc,
            shutdown=shutdown,
            error="; ".join(errors),
        )

    def sync_time_to_rtc(self) -> RTCState:
        self._execute_control("rtc_pi2rtc")
        return self.get_snapshot().rtc

    def sync_time_from_rtc(self) -> RTCState:
        self._execute_control("rtc_rtc2pi")
        return self.get_snapshot().rtc

    def set_rtc_alarm(self, when: datetime, repeat_mask: int = 127) -> RTCState:
        self._execute_control(f"rtc_alarm_set {when.isoformat()} {int(repeat_mask)}")
        return self.get_snapshot().rtc

    def disable_rtc_alarm(self) -> RTCState:
        self._execute_control("rtc_alarm_disable")
        return self.get_snapshot().rtc

    def _read_str(self, command: str) -> str:
        return _extract_response_value(command, self._send_command(command))

    def _read_bool(self, command: str) -> bool:
        value = self._read_str(command).strip().lower()
        if value in {"true", "1", "yes", "on"}:
            return True
        if value in {"false", "0", "no", "off"}:
            return False
        raise ValueError(f"Cannot coerce {value!r} to bool")

    def _read_int(self, command: str) -> int:
        return int(float(self._read_str(command)))

    def _read_float(self, command: str) -> float:
        return float(self._read_str(command))

    def _read_datetime(self, command: str) -> datetime:
        value = self._read_str(command)
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)

    def _execute_control(self, command: str) -> str:
        response = self._send_command(command).strip()
        if not response:
            raise PowerTransportError(f"Empty response for {command!r}")
        if response.lower().startswith("error"):
            raise PowerTransportError(f"PiSugar command failed for {command!r}: {response}")
        return response

    def _send_command(self, command: str) -> str:
        errors: list[str] = []
        for transport in _transport_order(self.config):
            try:
                return transport(command)
            except PowerTransportError as exc:
                errors.append(str(exc))
        raise PowerTransportError("; ".join(errors) or "No PiSugar transports configured")


@app.command()
def battery(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Inspect PiSugar power telemetry directly from the PiSugar server."""
    from loguru import logger

    configure_logging(verbose)
    config = _load_power_config(config_dir)
    client = PiSugarClient(config)
    snapshot = client.get_snapshot()
    if not snapshot.available:
        logger.error(snapshot.error or "power backend unavailable")
        raise typer.Exit(code=1)

    print("")
    print("PiSugar power status")
    print("====================")
    lines = [
        f"available={snapshot.available}",
        f"source={snapshot.source}",
        f"error={snapshot.error or 'none'}",
        f"model={snapshot.device.model or 'unknown'}",
        f"battery_percent={_format_optional(snapshot.battery.level_percent)}",
        f"battery_voltage={_format_optional(snapshot.battery.voltage_volts)}",
        f"temperature_celsius={_format_optional(snapshot.battery.temperature_celsius)}",
        f"charging={_format_optional(snapshot.battery.charging)}",
        f"external_power={_format_optional(snapshot.battery.power_plugged)}",
        f"allow_charging={_format_optional(snapshot.battery.allow_charging)}",
        f"output_enabled={_format_optional(snapshot.battery.output_enabled)}",
        f"rtc_time={snapshot.rtc.time.isoformat() if snapshot.rtc.time is not None else 'unknown'}",
        f"rtc_alarm_enabled={_format_optional(snapshot.rtc.alarm_enabled)}",
        f"rtc_alarm_time={snapshot.rtc.alarm_time.isoformat() if snapshot.rtc.alarm_time is not None else 'none'}",
        f"safe_shutdown_level={_format_optional(snapshot.shutdown.safe_shutdown_level_percent)}",
        f"safe_shutdown_delay={_format_optional(snapshot.shutdown.safe_shutdown_delay_seconds)}",
        f"warning_threshold={config.low_battery_warning_percent}",
        f"critical_threshold={config.critical_shutdown_percent}",
        f"shutdown_delay_seconds={config.shutdown_delay_seconds}",
        f"watchdog_enabled={config.watchdog_enabled}",
        f"watchdog_timeout_seconds={config.watchdog_timeout_seconds}",
        f"watchdog_feed_interval_seconds={config.watchdog_feed_interval_seconds}",
    ]
    for line in lines:
        print(line)


@rtc_app.command()
def status(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Show current RTC and alarm state."""
    from loguru import logger

    configure_logging(verbose)
    snapshot = PiSugarClient(_load_power_config(config_dir)).get_snapshot()
    if not snapshot.available:
        logger.error(snapshot.error or "power backend unavailable")
        raise typer.Exit(code=1)

    heading = "PiSugar RTC status"
    print("")
    print(heading)
    print("=" * len(heading))
    print(f"model={snapshot.device.model or 'unknown'}")
    for line in _format_rtc_state(snapshot.rtc):
        print(line)


@rtc_app.command(name="sync-to")
def sync_to(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Sync Raspberry Pi system time to the PiSugar RTC."""
    configure_logging(verbose)
    state = PiSugarClient(_load_power_config(config_dir)).sync_time_to_rtc()
    print("")
    print("PiSugar RTC synced from Raspberry Pi system time")
    print("==============================================")
    for line in _format_rtc_state(state):
        print(line)


@rtc_app.command(name="sync-from")
def sync_from(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Sync PiSugar RTC time to the Raspberry Pi system clock."""
    configure_logging(verbose)
    state = PiSugarClient(_load_power_config(config_dir)).sync_time_from_rtc()
    print("")
    print("Raspberry Pi system time synced from PiSugar RTC")
    print("===============================================")
    for line in _format_rtc_state(state):
        print(line)


@rtc_app.command(name="set-alarm")
def set_alarm(
    time: Annotated[str, typer.Option("--time", help="Alarm time as ISO 8601 timestamp.")],
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
    repeat_mask: Annotated[
        int,
        typer.Option("--repeat-mask", help="Weekday repeat bitmask (default: 127 for every day)."),
    ] = 127,
) -> None:
    """Set the PiSugar RTC wake alarm."""
    configure_logging(verbose)
    normalized = time.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    state = PiSugarClient(_load_power_config(config_dir)).set_rtc_alarm(
        datetime.fromisoformat(normalized),
        repeat_mask=repeat_mask,
    )
    print("")
    print("PiSugar RTC alarm updated")
    print("=========================")
    for line in _format_rtc_state(state):
        print(line)


@rtc_app.command(name="disable-alarm")
def disable_alarm(
    config_dir: Annotated[
        str, typer.Option("--config-dir", help="Configuration directory to use.")
    ] = "config",
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Disable the PiSugar RTC wake alarm."""
    configure_logging(verbose)
    state = PiSugarClient(_load_power_config(config_dir)).disable_rtc_alarm()
    print("")
    print("PiSugar RTC alarm disabled")
    print("==========================")
    for line in _format_rtc_state(state):
        print(line)


def _load_power_config(config_dir: str) -> PowerConfig:
    from loguru import logger

    from yoyopod_cli.config import ConfigManager

    config_path = resolve_config_dir(config_dir)
    config = ConfigManager(config_dir=str(config_path)).get_power_settings()
    if not config.enabled:
        logger.error("power backend disabled in config/power/backend.yaml")
        raise typer.Exit(code=1)
    return config


def _format_rtc_state(state: RTCState) -> list[str]:
    return [
        f"rtc_time={state.time.isoformat() if state.time is not None else 'unknown'}",
        f"alarm_enabled={_format_optional(state.alarm_enabled)}",
        f"alarm_time={state.alarm_time.isoformat() if state.alarm_time is not None else 'none'}",
        f"alarm_repeat_mask={_format_optional(state.alarm_repeat_mask)}",
        f"adjust_ppm={_format_optional(state.adjust_ppm)}",
    ]


def _format_optional(value: object) -> object:
    return "unknown" if value is None else value


def _transport_order(config: PowerConfig) -> list[Callable[[str], str]]:
    def unix_transport(command: str) -> str:
        return _send_unix_command(
            config.socket_path,
            command,
            config.timeout_seconds,
        )

    def tcp_transport(command: str) -> str:
        return _send_tcp_command(
            config.tcp_host,
            config.tcp_port,
            command,
            config.timeout_seconds,
        )

    if config.transport == "socket":
        return [unix_transport]
    if config.transport == "tcp":
        return [tcp_transport]
    return [unix_transport, tcp_transport]


def _send_unix_command(socket_path: str, command: str, timeout_seconds: float) -> str:
    path = Path(socket_path)
    if not path.exists():
        raise PowerTransportError(f"Unix socket not found: {path}")
    af_unix = getattr(socket, "AF_UNIX", None)
    if af_unix is None:
        raise PowerTransportError("Unix sockets are not supported on this platform")
    try:
        with socket.socket(af_unix, socket.SOCK_STREAM) as conn:
            conn.settimeout(timeout_seconds)
            conn.connect(socket_path)
            conn.sendall((command.strip() + "\n").encode("utf-8"))
            conn.shutdown(socket.SHUT_WR)
            return _read_socket_response(conn)
    except OSError as exc:
        raise PowerTransportError(f"Unix transport failed for {socket_path}: {exc}") from exc


def _send_tcp_command(host: str, port: int, command: str, timeout_seconds: float) -> str:
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds) as conn:
            conn.settimeout(timeout_seconds)
            conn.sendall((command.strip() + "\n").encode("utf-8"))
            conn.shutdown(socket.SHUT_WR)
            return _read_socket_response(conn)
    except OSError as exc:
        raise PowerTransportError(f"TCP transport failed for {host}:{port}: {exc}") from exc


def _read_socket_response(conn: socket.socket) -> str:
    chunks: list[bytes] = []
    while True:
        data = conn.recv(4096)
        if not data:
            break
        chunks.append(data)
    response = b"".join(chunks).decode("utf-8", errors="replace").strip()
    if not response:
        raise PowerTransportError("No response from PiSugar server")
    return response


def _extract_response_value(command: str, response: str) -> str:
    lines = [line.strip() for line in response.splitlines() if line.strip()]
    if not lines:
        raise PowerTransportError(f"Empty response for {command!r}")

    line = lines[-1]
    if ":" in line:
        _, line = line.split(":", 1)
    value = line.strip()
    if not value:
        raise PowerTransportError(f"Malformed response for {command!r}: {response!r}")
    return value


def _as_optional_str(value: object | None) -> str | None:
    return value if isinstance(value, str) else None


def _as_optional_bool(value: object | None) -> bool | None:
    return value if isinstance(value, bool) else None


def _as_optional_int(value: object | None) -> int | None:
    return value if isinstance(value, int) else None


def _as_optional_float(value: object | None) -> float | None:
    return float(value) if isinstance(value, int | float) else None


def _as_optional_datetime(value: object | None) -> datetime | None:
    return value if isinstance(value, datetime) else None
