from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.remote_setup import app, _build_setup, _build_verify_setup


def test_build_setup_calls_pi_setup() -> None:
    assert "yoyopod setup pi" in _build_setup()


def test_build_verify_setup_calls_pi_verify() -> None:
    assert "yoyopod setup verify-pi" in _build_verify_setup()


def test_setup_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0


def test_verify_setup_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["verify-setup", "--help"])
    assert result.exit_code == 0


# --- Fix 2: venv activation for setup / verify-setup ---

def test_build_setup_activates_venv_before_yoyopod() -> None:
    shell = _build_setup()
    activate_idx = shell.find("source")
    yoyopod_idx = shell.find("yoyopod setup pi")
    assert activate_idx >= 0, f"expected venv activation in: {shell}"
    assert activate_idx < yoyopod_idx, "venv must activate BEFORE yoyopod invocation"


def test_build_verify_setup_activates_venv_before_yoyopod() -> None:
    shell = _build_verify_setup()
    activate_idx = shell.find("source")
    yoyopod_idx = shell.find("yoyopod setup verify-pi")
    assert activate_idx >= 0, f"expected venv activation in: {shell}"
    assert activate_idx < yoyopod_idx, "venv must activate BEFORE yoyopod invocation"
