from __future__ import annotations

from typer.testing import CliRunner

from yoyopod_cli.remote_setup import app, _build_setup, _build_verify_setup


def test_build_setup_calls_pi_setup() -> None:
    shell = _build_setup(
        venv_relpath=".venv",
        with_voice=False,
        with_network=False,
        with_pisugar=False,
        skip_uv_sync=False,
        skip_builds=False,
        dry_run=False,
    )
    assert "uv run yoyopod setup pi" in shell


def test_build_verify_setup_calls_pi_verify() -> None:
    shell = _build_verify_setup(
        venv_relpath=".venv",
        with_voice=False,
        with_network=False,
        with_pisugar=False,
    )
    assert "uv run yoyopod setup verify-pi" in shell


def test_setup_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0


def test_verify_setup_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["verify-setup", "--help"])
    assert result.exit_code == 0


# --- checkout-local uv run for setup / verify-setup ---

def test_build_setup_uses_uv_run_yoyopod() -> None:
    shell = _build_setup(
        venv_relpath=".venv",
        with_voice=False,
        with_network=False,
        with_pisugar=False,
        skip_uv_sync=False,
        skip_builds=False,
        dry_run=False,
    )
    assert "uv run yoyopod setup pi" in shell
    assert "source " not in shell


def test_build_verify_setup_uses_uv_run_yoyopod() -> None:
    shell = _build_verify_setup(
        venv_relpath=".venv",
        with_voice=False,
        with_network=False,
        with_pisugar=False,
    )
    assert "uv run yoyopod setup verify-pi" in shell
    assert "source " not in shell


# --- Fix 1: feature-flag passthrough regression tests ---

def test_build_setup_passes_all_feature_flags() -> None:
    shell = _build_setup(
        venv_relpath=".venv",
        with_voice=True,
        with_network=True,
        with_pisugar=True,
        skip_uv_sync=True,
        skip_builds=True,
        dry_run=True,
    )
    assert "uv run yoyopod setup pi" in shell
    assert "--with-voice" in shell
    assert "--with-network" in shell
    assert "--with-pisugar" in shell
    assert "--skip-uv-sync" in shell
    assert "--skip-builds" in shell
    assert "--dry-run" in shell


def test_build_setup_default_has_no_feature_flags() -> None:
    shell = _build_setup(
        venv_relpath=".venv",
        with_voice=False,
        with_network=False,
        with_pisugar=False,
        skip_uv_sync=False,
        skip_builds=False,
        dry_run=False,
    )
    assert "uv run yoyopod setup pi" in shell
    for flag in (
        "--with-voice",
        "--with-network",
        "--with-pisugar",
        "--skip-uv-sync",
        "--skip-builds",
        "--dry-run",
    ):
        assert flag not in shell


def test_build_verify_setup_passes_feature_flags() -> None:
    shell = _build_verify_setup(
        venv_relpath=".venv",
        with_voice=True,
        with_network=True,
        with_pisugar=True,
    )
    assert "uv run yoyopod setup verify-pi" in shell
    assert "--with-voice" in shell
    assert "--with-network" in shell
    assert "--with-pisugar" in shell


def test_build_verify_setup_default_has_no_feature_flags() -> None:
    shell = _build_verify_setup(
        venv_relpath=".venv",
        with_voice=False,
        with_network=False,
        with_pisugar=False,
    )
    for flag in ("--with-voice", "--with-network", "--with-pisugar"):
        assert flag not in shell


def test_setup_cli_forwards_all_flags(monkeypatch) -> None:
    """CLI invocation with --with-pisugar etc. produces remote shell with those flags."""
    calls: list[str] = []
    monkeypatch.setattr(
        "yoyopod_cli.remote_setup.run_remote",
        lambda conn, cmd, tty=False: (calls.append(cmd), 0)[1],
    )
    monkeypatch.setenv("YOYOPOD_PI_HOST", "rpi-zero")

    runner = CliRunner()
    result = runner.invoke(app, ["setup", "--with-pisugar", "--with-voice", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert len(calls) == 1
    assert "--with-pisugar" in calls[0]
    assert "--with-voice" in calls[0]
    assert "--dry-run" in calls[0]
