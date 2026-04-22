"""PiSugar power backend protocol and transport implementation."""

from __future__ import annotations

import socket
from datetime import datetime
from pathlib import Path
from typing import Callable, Protocol

from loguru import logger

from yoyopod.config.models import PowerConfig
from yoyopod.integrations.power.models import (
    BatteryState,
    PowerDeviceInfo,
    PowerSnapshot,
    RTCState,
    ShutdownState,
)


class PowerBackend(Protocol):
    """Read-only backend contract for power-management integrations."""

    def probe(self) -> bool:
        """Return True when the backend is reachable."""

    def get_snapshot(self) -> PowerSnapshot:
        """Return a best-effort point-in-time power snapshot."""

    def sync_time_to_rtc(self) -> None:
        """Sync Raspberry Pi system time to the PiSugar RTC."""

    def sync_time_from_rtc(self) -> None:
        """Sync PiSugar RTC time back to the Raspberry Pi system clock."""

    def set_rtc_alarm(self, when: datetime, repeat_mask: int = 127) -> None:
        """Configure the PiSugar RTC wake alarm."""

    def disable_rtc_alarm(self) -> None:
        """Disable the configured PiSugar RTC wake alarm."""


class PowerTransportError(RuntimeError):
    """Raised when the PiSugar transport cannot complete a command."""


class PiSugarTransport(Protocol):
    """Simple command transport for the PiSugar server."""

    def send_command(self, command: str) -> str:
        """Send one command and return the raw response."""


class PiSugarTCPTransport:
    """Talk to PiSugar over the documented local TCP API."""

    def __init__(self, host: str, port: int, timeout_seconds: float) -> None:
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds

    def send_command(self, command: str) -> str:
        try:
            with socket.create_connection(
                (self.host, self.port),
                timeout=self.timeout_seconds,
            ) as conn:
                conn.settimeout(self.timeout_seconds)
                conn.sendall((command.strip() + "\n").encode("utf-8"))
                conn.shutdown(socket.SHUT_WR)
                return _read_socket_response(conn)
        except OSError as exc:
            raise PowerTransportError(
                f"TCP transport failed for {self.host}:{self.port}: {exc}"
            ) from exc


class PiSugarUnixTransport:
    """Talk to PiSugar over the documented Unix-domain socket API."""

    def __init__(self, socket_path: str, timeout_seconds: float) -> None:
        self.socket_path = socket_path
        self.timeout_seconds = timeout_seconds

    def send_command(self, command: str) -> str:
        path = Path(self.socket_path)
        if not path.exists():
            raise PowerTransportError(f"Unix socket not found: {path}")

        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(self.timeout_seconds)
                conn.connect(self.socket_path)
                conn.sendall((command.strip() + "\n").encode("utf-8"))
                conn.shutdown(socket.SHUT_WR)
                return _read_socket_response(conn)
        except OSError as exc:
            raise PowerTransportError(
                f"Unix transport failed for {self.socket_path}: {exc}"
            ) from exc


class PiSugarAutoTransport:
    """Try Unix socket first, then local TCP, until one responds."""

    def __init__(self, transports: list[PiSugarTransport]) -> None:
        self.transports = transports

    def send_command(self, command: str) -> str:
        errors: list[str] = []
        for transport in self.transports:
            try:
                return transport.send_command(command)
            except PowerTransportError as exc:
                errors.append(str(exc))

        raise PowerTransportError("; ".join(errors) or "No PiSugar transports configured")


class PiSugarBackend:
    """Read-only PiSugar backend backed by the local socket/TCP server."""

    def __init__(
        self,
        config: PowerConfig,
        transport: PiSugarTransport | None = None,
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.config = config
        self.transport = transport or build_pisugar_transport(config)
        self.now_provider = now_provider or datetime.now

    def probe(self) -> bool:
        """Return True if the backend responds to a lightweight command."""
        if not self.config.enabled:
            return False

        try:
            self._query("get model")
            return True
        except (PowerTransportError, ValueError) as exc:
            logger.debug(f"PiSugar probe failed: {exc}")
            return False

    def get_snapshot(self) -> PowerSnapshot:
        """Collect a best-effort snapshot of the current PiSugar state."""
        checked_at = self.now_provider()

        if not self.config.enabled:
            return PowerSnapshot(
                available=False,
                checked_at=checked_at,
                error="power backend disabled",
            )

        success_count = 0
        errors: list[str] = []

        def read_optional(reader: Callable[[str], object], command: str):
            nonlocal success_count
            try:
                value = reader(command)
            except (PowerTransportError, ValueError) as exc:
                errors.append(f"{command}: {exc}")
                return None
            success_count += 1
            return value

        device = PowerDeviceInfo(
            model=read_optional(self._read_str, "get model"),
            firmware_version=read_optional(self._read_str, "get firmware_version"),
        )
        battery = BatteryState(
            level_percent=read_optional(self._read_float, "get battery"),
            voltage_volts=read_optional(self._read_float, "get battery_v"),
            charging=read_optional(self._read_bool, "get battery_charging"),
            power_plugged=read_optional(self._read_bool, "get battery_power_plugged"),
            allow_charging=read_optional(self._read_bool, "get battery_allow_charging"),
            output_enabled=read_optional(self._read_bool, "get battery_output_enabled"),
            temperature_celsius=read_optional(self._read_float, "get temperature"),
        )
        rtc = RTCState(
            time=read_optional(self._read_datetime, "get rtc_time"),
            alarm_enabled=read_optional(self._read_bool, "get rtc_alarm_enabled"),
            alarm_time=read_optional(self._read_datetime, "get rtc_alarm_time"),
            alarm_repeat_mask=read_optional(self._read_int, "get alarm_repeat"),
            adjust_ppm=read_optional(self._read_float, "get rtc_adjust_ppm"),
        )
        shutdown = ShutdownState(
            safe_shutdown_level_percent=read_optional(
                self._read_float,
                "get safe_shutdown_level",
            ),
            safe_shutdown_delay_seconds=read_optional(
                self._read_int,
                "get safe_shutdown_delay",
            ),
        )

        return PowerSnapshot(
            available=success_count > 0,
            checked_at=checked_at,
            device=device,
            battery=battery,
            rtc=rtc,
            shutdown=shutdown,
            error="; ".join(errors),
        )

    def sync_time_to_rtc(self) -> None:
        """Sync Raspberry Pi system time to the PiSugar RTC."""
        self._execute_control("rtc_pi2rtc")

    def sync_time_from_rtc(self) -> None:
        """Sync PiSugar RTC time back to the Raspberry Pi system clock."""
        self._execute_control("rtc_rtc2pi")

    def set_rtc_alarm(self, when: datetime, repeat_mask: int = 127) -> None:
        """Configure the PiSugar RTC wake alarm."""
        iso_time = when.isoformat()
        self._execute_control(f"rtc_alarm_set {iso_time} {int(repeat_mask)}")

    def disable_rtc_alarm(self) -> None:
        """Disable the PiSugar RTC wake alarm."""
        self._execute_control("rtc_alarm_disable")

    def _query(self, command: str) -> str:
        """Execute one PiSugar command and normalize its payload."""
        response = self.transport.send_command(command)
        return _extract_response_value(command, response)

    def _execute_control(self, command: str) -> str:
        """Execute one PiSugar control command and validate that it responded."""
        response = self.transport.send_command(command).strip()
        if not response:
            raise PowerTransportError(f"Empty response for {command!r}")
        if response.lower().startswith("error"):
            raise PowerTransportError(f"PiSugar command failed for {command!r}: {response}")
        return response

    def _read_str(self, command: str) -> str:
        return self._query(command)

    def _read_bool(self, command: str) -> bool:
        value = self._query(command).strip().lower()
        if value in {"true", "1", "yes", "on"}:
            return True
        if value in {"false", "0", "no", "off"}:
            return False
        raise ValueError(f"Cannot coerce {value!r} to bool")

    def _read_int(self, command: str) -> int:
        return int(float(self._query(command)))

    def _read_float(self, command: str) -> float:
        return float(self._query(command))

    def _read_datetime(self, command: str) -> datetime:
        value = self._query(command)
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)


def build_pisugar_transport(config: PowerConfig) -> PiSugarTransport:
    """Build a transport based on the configured PiSugar access mode."""
    unix_transport = PiSugarUnixTransport(config.socket_path, config.timeout_seconds)
    tcp_transport = PiSugarTCPTransport(
        config.tcp_host,
        config.tcp_port,
        config.timeout_seconds,
    )

    if config.transport == "socket":
        return unix_transport
    if config.transport == "tcp":
        return tcp_transport
    return PiSugarAutoTransport([unix_transport, tcp_transport])


def _read_socket_response(conn: socket.socket) -> str:
    """Read all response bytes from a socket connection."""
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
    """Normalize raw PiSugar command responses into their payload value."""
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
