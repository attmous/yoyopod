"""Tests for yoyopod_cli.remote_infra — power, rtc, service."""

from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.remote_infra import (
    app,
    _build_power,
    _build_rtc,
)


def test_build_power_invokes_pi_power_battery() -> None:
    shell = _build_power(venv_relpath=".venv")
    assert ".venv/bin/python -m yoyopod_cli.main pi power battery" in shell


def test_build_rtc_status() -> None:
    shell = _build_rtc("status", venv_relpath=".venv", time_iso="", repeat_mask=127)
    assert ".venv/bin/python -m yoyopod_cli.main pi power rtc" in shell
    assert "status" in shell


def test_build_rtc_set_alarm_with_time() -> None:
    shell = _build_rtc(
        "set-alarm",
        venv_relpath=".venv",
        time_iso="2026-04-20T07:00:00",
        repeat_mask=127,
    )
    assert "set-alarm" in shell
    assert "2026-04-20T07:00:00" in shell
    assert "127" in shell


def test_build_rtc_set_alarm_without_time_fails() -> None:
    import pytest
    import typer

    with pytest.raises(typer.BadParameter):
        _build_rtc("set-alarm", venv_relpath=".venv", time_iso="", repeat_mask=127)


def test_power_cli_invokes_run_remote(monkeypatch) -> None:
    calls: list[tuple[object, str]] = []

    def fake_run_remote(conn, cmd, tty=False):
        calls.append((conn, cmd))
        return 0

    monkeypatch.setattr("yoyopod_cli.remote_infra.run_remote", fake_run_remote)
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["power"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1


# --- Fix 2: checkout-local module invocation for power / rtc ---


def test_build_power_uses_checkout_python_module_invocation() -> None:
    shell = _build_power(venv_relpath=".venv")
    assert ".venv/bin/python -m yoyopod_cli.main pi power battery" in shell
    assert "source " not in shell
    assert "uv run" not in shell


def test_build_rtc_uses_checkout_python_module_invocation() -> None:
    shell = _build_rtc("status", venv_relpath=".venv", time_iso="", repeat_mask=127)
    assert ".venv/bin/python -m yoyopod_cli.main pi power rtc" in shell
    assert "source " not in shell
    assert "uv run" not in shell


def test_legacy_service_command_fails_locally(monkeypatch) -> None:
    def fail_run_remote(*args, **kwargs):
        raise AssertionError("legacy service command must not SSH to the Pi")

    monkeypatch.setattr("yoyopod_cli.remote_infra.run_remote", fail_run_remote)
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["service", "status"])

    assert result.exit_code == 2
    assert "Legacy yoyopod@ service management is no longer supported" in (
        result.stderr or result.output
    )
