"""tests/test_cli.py — yoyoctl CLI smoke tests."""

import re

from typer.testing import CliRunner

from yoyopod.cli import app

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    """Strip ANSI escape codes so assertions work in CI."""
    return _ANSI_RE.sub("", text)


def test_root_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "pi" in _plain(result.output)
    assert "remote" in _plain(result.output)
    assert "build" in _plain(result.output)
    assert "setup" in _plain(result.output)


def test_pi_help():
    result = runner.invoke(app, ["pi", "--help"])
    assert result.exit_code == 0
    assert "validate" in _plain(result.output)


def test_remote_help():
    result = runner.invoke(app, ["remote", "--help"])
    assert result.exit_code == 0


def test_build_help():
    result = runner.invoke(app, ["build", "--help"])
    assert result.exit_code == 0


def test_setup_help():
    result = runner.invoke(app, ["setup", "--help"])
    assert result.exit_code == 0


def test_setup_host_help():
    result = runner.invoke(app, ["setup", "host", "--help"])
    assert result.exit_code == 0
    assert "--skip-sync" in _plain(result.output)


def test_setup_pi_help():
    result = runner.invoke(app, ["setup", "pi", "--help"])
    assert result.exit_code == 0
    assert "--with-pisugar" in _plain(result.output)


def test_setup_verify_host_help():
    result = runner.invoke(app, ["setup", "verify-host", "--help"])
    assert result.exit_code == 0
    assert "--with-remote-tools" in _plain(result.output)


def test_setup_verify_pi_help():
    result = runner.invoke(app, ["setup", "verify-pi", "--help"])
    assert result.exit_code == 0
    assert "--with-network" in _plain(result.output)


def test_build_lvgl_help():
    result = runner.invoke(app, ["build", "lvgl", "--help"])
    assert result.exit_code == 0
    assert "--source-dir" in _plain(result.output)
    assert "--build-dir" in _plain(result.output)
    assert "--skip-fetch" in _plain(result.output)


def test_build_liblinphone_help():
    result = runner.invoke(app, ["build", "liblinphone", "--help"])
    assert result.exit_code == 0
    assert "--build-dir" in _plain(result.output)


def test_pi_voip_check_help():
    result = runner.invoke(app, ["pi", "voip", "check", "--help"])
    assert result.exit_code == 0


def test_pi_voip_debug_help():
    result = runner.invoke(app, ["pi", "voip", "debug", "--help"])
    assert result.exit_code == 0


def test_pi_power_battery_help():
    result = runner.invoke(app, ["pi", "power", "battery", "--help"])
    assert result.exit_code == 0
    assert "--config-dir" in _plain(result.output)
    assert "--verbose" in _plain(result.output)


def test_pi_power_rtc_help():
    result = runner.invoke(app, ["pi", "power", "rtc", "--help"])
    assert result.exit_code == 0


def test_pi_power_rtc_status_help():
    result = runner.invoke(app, ["pi", "power", "rtc", "status", "--help"])
    assert result.exit_code == 0


def test_pi_lvgl_soak_help():
    result = runner.invoke(app, ["pi", "lvgl", "soak", "--help"])
    assert result.exit_code == 0
    assert "--cycles" in _plain(result.output)
    assert "--simulate" in _plain(result.output)
    assert "--hold-seconds" in _plain(result.output)


def test_pi_lvgl_probe_help():
    result = runner.invoke(app, ["pi", "lvgl", "probe", "--help"])
    assert result.exit_code == 0
    assert "--scene" in _plain(result.output)
    assert "--duration-seconds" in _plain(result.output)
    assert "--simulate" in _plain(result.output)


def test_pi_smoke_help():
    result = runner.invoke(app, ["pi", "smoke", "--help"])
    assert result.exit_code == 0
    assert "--with-music" in _plain(result.output)
    assert "--with-voip" in _plain(result.output)
    assert "--with-power" in _plain(result.output)
    assert "--with-lvgl-soak" in _plain(result.output)


def test_pi_validate_help():
    result = runner.invoke(app, ["pi", "validate", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "deploy" in output
    assert "smoke" in output
    assert "music" in output
    assert "voip" in output
    assert "stability" in output


def test_pi_validate_deploy_help():
    result = runner.invoke(app, ["pi", "validate", "deploy", "--help"])
    assert result.exit_code == 0
    assert "--config-dir" in _plain(result.output)


def test_pi_validate_smoke_help():
    result = runner.invoke(app, ["pi", "validate", "smoke", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--with-power" in output
    assert "--with-rtc" in output


def test_pi_validate_music_help():
    result = runner.invoke(app, ["pi", "validate", "music", "--help"])
    assert result.exit_code == 0
    assert "--timeout" in _plain(result.output)


def test_pi_validate_voip_help():
    result = runner.invoke(app, ["pi", "validate", "voip", "--help"])
    assert result.exit_code == 0
    assert "--timeout" in _plain(result.output)


def test_pi_validate_stability_help():
    result = runner.invoke(app, ["pi", "validate", "stability", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--cycles" in output
    assert "--hold-seconds" in output


def test_pi_tune_help():
    result = runner.invoke(app, ["pi", "tune", "--help"])
    assert result.exit_code == 0
    assert "--debounce-ms" in _plain(result.output)
    assert "--hardware" in _plain(result.output)


def test_pi_gallery_help():
    result = runner.invoke(app, ["pi", "gallery", "--help"])
    assert result.exit_code == 0
    assert "--output-dir" in _plain(result.output)
    assert "--simulate" in _plain(result.output)


def test_remote_status_help():
    result = runner.invoke(app, ["remote", "status", "--help"])
    assert result.exit_code == 0
    assert "--host" in _plain(result.output)


def test_remote_sync_help():
    result = runner.invoke(app, ["remote", "sync", "--help"])
    assert result.exit_code == 0
    assert "--host" in _plain(result.output)
    assert "--branch" in _plain(result.output)
    assert "--sha" in _plain(result.output)


def test_remote_validate_help():
    result = runner.invoke(app, ["remote", "validate", "--help"])
    assert result.exit_code == 0
    assert "--branch" in _plain(result.output)
    assert "--sha" in _plain(result.output)
    assert "--with-music" in _plain(result.output)
    assert "--lines" in _plain(result.output)


def test_remote_smoke_help():
    result = runner.invoke(app, ["remote", "smoke", "--help"])
    assert result.exit_code == 0


def test_remote_preflight_help():
    result = runner.invoke(app, ["remote", "preflight", "--help"])
    assert result.exit_code == 0


def test_remote_lvgl_soak_help():
    result = runner.invoke(app, ["remote", "lvgl-soak", "--help"])
    assert result.exit_code == 0


def test_remote_power_help():
    result = runner.invoke(app, ["remote", "power", "--help"])
    assert result.exit_code == 0


def test_remote_config_help():
    result = runner.invoke(app, ["remote", "config", "--help"])
    assert result.exit_code == 0


def test_remote_service_help():
    result = runner.invoke(app, ["remote", "service", "--help"])
    assert result.exit_code == 0


def test_remote_restart_help():
    result = runner.invoke(app, ["remote", "restart", "--help"])
    assert result.exit_code == 0


def test_remote_logs_help():
    result = runner.invoke(app, ["remote", "logs", "--help"])
    assert result.exit_code == 0


def test_remote_screenshot_help():
    result = runner.invoke(app, ["remote", "screenshot", "--help"])
    assert result.exit_code == 0


def test_remote_rsync_help():
    result = runner.invoke(app, ["remote", "rsync", "--help"])
    assert result.exit_code == 0
    assert "escape hatch" in _plain(result.output).lower()


def test_remote_whisplay_help():
    result = runner.invoke(app, ["remote", "whisplay", "--help"])
    assert result.exit_code == 0
    assert "--debounce-ms" in _plain(result.output)


def test_remote_rtc_help():
    result = runner.invoke(app, ["remote", "rtc", "--help"])
    assert result.exit_code == 0


def test_remote_setup_help():
    result = runner.invoke(app, ["remote", "setup", "--help"])
    assert result.exit_code == 0
    assert "--with-voice" in _plain(result.output)


def test_remote_verify_setup_help():
    result = runner.invoke(app, ["remote", "verify-setup", "--help"])
    assert result.exit_code == 0
    assert "--with-pisugar" in _plain(result.output)
