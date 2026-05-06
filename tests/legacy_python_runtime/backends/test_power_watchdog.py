"""Tests for the PiSugar watchdog controller."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoyopod.backends.power import PiSugarWatchdog, WatchdogCommandError
from yoyopod.config import PowerConfig


def test_enable_sets_timeout_and_starts_with_fresh_feed() -> None:
    """Enabling the watchdog should write the timeout register and feed immediately."""

    commands: list[list[str]] = []

    def runner(command: list[str]):
        commands.append(command)
        if command[0] == "i2cget":
            return SimpleNamespace(returncode=0, stdout="0x10\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    watchdog = PiSugarWatchdog(
        PowerConfig(
            watchdog_enabled=True,
            watchdog_timeout_seconds=19,
        ),
        runner=runner,
    )

    watchdog.enable()

    assert commands == [
        ["i2cget", "-y", "1", "0x57", "0x6"],
        ["i2cset", "-y", "1", "0x57", "0x7", "0xa"],
        ["i2cset", "-y", "1", "0x57", "0x6", "0xb0"],
    ]


def test_feed_preserves_enable_bit_and_sets_reset_bit() -> None:
    """Feeding the watchdog should read the current control register and kick the timer."""

    commands: list[list[str]] = []

    def runner(command: list[str]):
        commands.append(command)
        if command[0] == "i2cget":
            return SimpleNamespace(returncode=0, stdout="0x80\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    watchdog = PiSugarWatchdog(PowerConfig(watchdog_enabled=True), runner=runner)

    watchdog.feed()

    assert commands == [
        ["i2cget", "-y", "1", "0x57", "0x6"],
        ["i2cset", "-y", "1", "0x57", "0x6", "0xa0"],
    ]


def test_disable_clears_watchdog_enable_bit() -> None:
    """Disabling should write the control register without the watchdog bits set."""

    commands: list[list[str]] = []

    def runner(command: list[str]):
        commands.append(command)
        if command[0] == "i2cget":
            return SimpleNamespace(returncode=0, stdout="0xa0\n", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    watchdog = PiSugarWatchdog(PowerConfig(watchdog_enabled=True), runner=runner)

    watchdog.disable()

    assert commands == [
        ["i2cget", "-y", "1", "0x57", "0x6"],
        ["i2cset", "-y", "1", "0x57", "0x6", "0x0"],
    ]


def test_watchdog_raises_on_failed_command() -> None:
    """Non-zero i2c command exits should be surfaced as watchdog failures."""

    def runner(_command: list[str]):
        return SimpleNamespace(returncode=1, stdout="", stderr="i2c failure")

    watchdog = PiSugarWatchdog(PowerConfig(watchdog_enabled=True), runner=runner)

    with pytest.raises(WatchdogCommandError):
        watchdog.feed()
