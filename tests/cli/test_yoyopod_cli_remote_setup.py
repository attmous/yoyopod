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
    assert "sudo apt update" in shell
    assert "python3 -m venv .venv" in shell
    assert ".venv/bin/python -m pip install -e '.[dev]'" in shell
    assert ".venv/bin/python -m yoyopod_cli.main build liblinphone" in shell
    assert ".venv/bin/python -m yoyopod_cli.main build lvgl" in shell


def test_build_setup_preserves_home_relative_venv_expansion() -> None:
    shell = _build_setup(
        venv_relpath="~/.venv",
        with_voice=False,
        with_network=False,
        with_pisugar=False,
        skip_uv_sync=False,
        skip_builds=False,
        dry_run=False,
    )

    assert '"$HOME/.venv/bin/python"' in shell
    assert "'~/.venv" not in shell


def test_build_verify_setup_calls_pi_verify() -> None:
    shell = _build_verify_setup(
        venv_relpath=".venv",
        with_voice=False,
        with_network=False,
        with_pisugar=False,
    )
    assert ".venv/bin/python -m yoyopod_cli.main setup verify-pi" in shell


def test_build_verify_setup_preserves_home_relative_venv_expansion() -> None:
    shell = _build_verify_setup(
        venv_relpath="~/.venv",
        with_voice=False,
        with_network=False,
        with_pisugar=False,
    )

    assert '"$HOME/.venv/bin/python" -m yoyopod_cli.main setup verify-pi' in shell


def test_setup_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0


def test_verify_setup_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["verify-setup", "--help"])
    assert result.exit_code == 0


# --- bootstrap shell for setup / checkout-local verify for verify-setup ---


def test_build_setup_bootstraps_checkout_venv_without_uv() -> None:
    shell = _build_setup(
        venv_relpath=".venv",
        with_voice=False,
        with_network=False,
        with_pisugar=False,
        skip_uv_sync=False,
        skip_builds=False,
        dry_run=False,
    )
    assert "python3 -m venv .venv" in shell
    assert ".venv/bin/python -m pip install --upgrade pip setuptools wheel" in shell
    assert ".venv/bin/python -m pip install -e '.[dev]'" in shell
    assert "source " not in shell
    assert "uv run" not in shell


def test_build_verify_setup_uses_checkout_python_module_invocation() -> None:
    shell = _build_verify_setup(
        venv_relpath=".venv",
        with_voice=False,
        with_network=False,
        with_pisugar=False,
    )
    assert ".venv/bin/python -m yoyopod_cli.main setup verify-pi" in shell
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
    assert shell.startswith("printf '%s\\n' ")
    assert "espeak-ng" in shell
    assert "ppp" in shell
    assert "pisugar-server" in shell
    assert "python3 -m venv" not in shell
    assert "pip install" not in shell
    assert "build liblinphone" not in shell
    assert "build lvgl" not in shell


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
    assert (
        "sudo apt install -y python3-venv mpv ffmpeg liblinphone-dev pkg-config cmake alsa-utils i2c-tools"
        in shell
    )
    for package in ("espeak-ng", "ppp", "pisugar-server"):
        assert package not in shell


def test_build_verify_setup_passes_feature_flags() -> None:
    shell = _build_verify_setup(
        venv_relpath=".venv",
        with_voice=True,
        with_network=True,
        with_pisugar=True,
    )
    assert ".venv/bin/python -m yoyopod_cli.main setup verify-pi" in shell
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
    """CLI invocation with feature flags produces the corresponding bootstrap shell."""
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
    assert "pisugar-server" in calls[0]
    assert "espeak-ng" in calls[0]
    assert calls[0].startswith("printf '%s\\n' ")
