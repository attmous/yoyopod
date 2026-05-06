"""PiSugar software watchdog helpers."""

from __future__ import annotations

import subprocess
from math import ceil
from typing import Callable, Protocol

from yoyopod_cli.config.models import PowerConfig


class WatchdogRunnerResult(Protocol):
    """Minimal subprocess-like result contract used by the watchdog controller."""

    returncode: int
    stdout: str
    stderr: str


WatchdogRunner = Callable[[list[str]], WatchdogRunnerResult]


class WatchdogCommandError(RuntimeError):
    """Raised when one PiSugar watchdog command cannot be completed."""


class PiSugarWatchdog:
    """Control the PiSugar 3 software watchdog over I2C tools."""

    CONTROL_REGISTER = 0x06
    TIMEOUT_REGISTER = 0x07
    ENABLE_MASK = 0x80
    FEED_MASK = 0x20

    def __init__(
        self,
        config: PowerConfig,
        runner: WatchdogRunner | None = None,
    ) -> None:
        self.config = config
        self._runner = runner or self._default_runner

    def enable(self, timeout_seconds: int | None = None) -> None:
        """Enable the PiSugar watchdog and start a fresh timeout window."""
        timeout_value = self._coerce_timeout_value(timeout_seconds)
        control_value = self._read_register(self.CONTROL_REGISTER)
        self._write_register(self.TIMEOUT_REGISTER, timeout_value)
        self._write_register(
            self.CONTROL_REGISTER,
            control_value | self.ENABLE_MASK | self.FEED_MASK,
        )

    def feed(self) -> None:
        """Reset the PiSugar watchdog timer while keeping it enabled."""
        control_value = self._read_register(self.CONTROL_REGISTER)
        self._write_register(
            self.CONTROL_REGISTER,
            control_value | self.ENABLE_MASK | self.FEED_MASK,
        )

    def disable(self) -> None:
        """Turn off the PiSugar watchdog."""
        control_value = self._read_register(self.CONTROL_REGISTER)
        disabled_value = control_value & ~self.ENABLE_MASK & ~self.FEED_MASK
        self._write_register(self.CONTROL_REGISTER, disabled_value)

    def _coerce_timeout_value(self, timeout_seconds: int | None) -> int:
        effective_timeout = (
            self.config.watchdog_timeout_seconds if timeout_seconds is None else timeout_seconds
        )
        if effective_timeout <= 0:
            raise WatchdogCommandError("Watchdog timeout must be positive")

        # PiSugar stores the watchdog timeout in 2-second units.
        return max(1, min(255, ceil(effective_timeout / 2.0)))

    def _read_register(self, register: int) -> int:
        result = self._run_command(
            [
                "i2cget",
                "-y",
                str(self.config.watchdog_i2c_bus),
                hex(self.config.watchdog_i2c_address),
                hex(register),
            ]
        )
        try:
            return int(result.stdout.strip(), 0)
        except ValueError as exc:
            raise WatchdogCommandError(
                f"Unexpected i2cget output for register {hex(register)}: {result.stdout!r}"
            ) from exc

    def _write_register(self, register: int, value: int) -> None:
        self._run_command(
            [
                "i2cset",
                "-y",
                str(self.config.watchdog_i2c_bus),
                hex(self.config.watchdog_i2c_address),
                hex(register),
                hex(value),
            ]
        )

    def _run_command(self, command: list[str]) -> WatchdogRunnerResult:
        result = self._runner(command)
        if result.returncode != 0:
            raise WatchdogCommandError(
                f"Watchdog command failed ({result.returncode}): {' '.join(command)}; "
                f"stderr={result.stderr.strip()!r}"
            )
        return result

    def _default_runner(self, command: list[str]) -> WatchdogRunnerResult:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=self.config.watchdog_command_timeout_seconds,
        )
