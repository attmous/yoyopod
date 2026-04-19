"""tests/test_cli.py — yoyoctl CLI smoke tests."""

import re
import sys
import types

import pytest

pytest.importorskip("typer")

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


def test_pi_music_help():
    result = runner.invoke(app, ["pi", "music", "--help"])
    assert result.exit_code == 0


def test_pi_music_provision_test_library_help():
    result = runner.invoke(app, ["pi", "music", "provision-test-library", "--help"])
    assert result.exit_code == 0
    assert "--target-dir" in _plain(result.output)


def test_remote_help():
    result = runner.invoke(app, ["remote", "--help"])
    assert result.exit_code == 0
    assert "navigation-soak" in _plain(result.output)


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
    assert "--config-dir" in _plain(result.output)


def test_pi_voip_debug_help():
    result = runner.invoke(app, ["pi", "voip", "debug", "--help"])
    assert result.exit_code == 0
    assert "--config-dir" in _plain(result.output)


def test_pi_voip_registration_stability_help():
    result = runner.invoke(app, ["pi", "voip", "registration-stability", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--registration-timeout" in output
    assert "--hold-seconds" in output
    assert "--artifacts-dir" in output


def test_pi_voip_reconnect_drill_help():
    result = runner.invoke(app, ["pi", "voip", "reconnect-drill", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--disconnect-seconds" in output
    assert "--drop-command" in output
    assert "--restore-command" in output
    assert "--artifacts-dir" in output


def test_pi_voip_call_soak_help():
    result = runner.invoke(app, ["pi", "voip", "call-soak", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--target" in output
    assert "--connect-timeout" in output
    assert "--soak-seconds" in output
    assert "--artifacts-dir" in output


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
    assert "--idle-seconds" in _plain(result.output)
    assert "--with-music" in _plain(result.output)
    assert "--test-music-dir" in _plain(result.output)


def test_pi_lvgl_probe_help():
    result = runner.invoke(app, ["pi", "lvgl", "probe", "--help"])
    assert result.exit_code == 0
    assert "--scene" in _plain(result.output)
    assert "--duration-seconds" in _plain(result.output)
    assert "--simulate" in _plain(result.output)


def test_pi_lvgl_probe_uses_explicit_debug_escape_hatch(monkeypatch) -> None:
    """The standalone probe should bypass the production render contract explicitly."""

    import yoyopod.cli.pi.lvgl as lvgl_cli

    adapter_kwargs = {}
    backend_calls = []

    class FakeWhisplayDisplayAdapter:
        def __init__(self, **kwargs) -> None:
            adapter_kwargs.update(kwargs)

        def cleanup(self) -> None:
            backend_calls.append("adapter_cleanup")

    class FakeLvglBinding:
        SCENE_CARD = 1
        SCENE_LIST = 2
        SCENE_FOOTER = 3
        SCENE_CAROUSEL = 4

    class FakeLvglBindingError(RuntimeError):
        pass

    class FakeLvglDisplayBackend:
        def __init__(self, adapter) -> None:
            self.adapter = adapter
            self.available = True

        def initialize(self) -> bool:
            backend_calls.append("initialize")
            return True

        def show_probe_scene(self, scene_id: int) -> None:
            backend_calls.append(("scene", scene_id))

        def pump(self, milliseconds: int) -> int:
            backend_calls.append(("pump", milliseconds))
            return 0

        def cleanup(self) -> None:
            backend_calls.append("backend_cleanup")

    fake_whisplay_module = types.ModuleType("yoyopod.ui.display.adapters.whisplay")
    fake_whisplay_module.WhisplayDisplayAdapter = FakeWhisplayDisplayAdapter
    fake_lvgl_module = types.ModuleType("yoyopod.ui.lvgl_binding")
    fake_lvgl_module.LvglBinding = FakeLvglBinding
    fake_lvgl_module.LvglBindingError = FakeLvglBindingError
    fake_lvgl_module.LvglDisplayBackend = FakeLvglDisplayBackend

    monkeypatch.setattr(lvgl_cli, "configure_logging", lambda _verbose: None)
    monkeypatch.setitem(
        sys.modules,
        "yoyopod.ui.display.adapters.whisplay",
        fake_whisplay_module,
    )
    monkeypatch.setitem(
        sys.modules,
        "yoyopod.ui.lvgl_binding",
        fake_lvgl_module,
    )

    lvgl_cli.probe(scene="carousel", duration_seconds=0.0, simulate=False, verbose=False)

    assert adapter_kwargs == {
        "simulate": False,
        "renderer": "pil",
        "enforce_production_contract": False,
    }
    assert backend_calls == [
        "initialize",
        ("scene", FakeLvglBinding.SCENE_CAROUSEL),
        "backend_cleanup",
        "adapter_cleanup",
    ]


def test_pi_smoke_help():
    result = runner.invoke(app, ["pi", "smoke", "--help"])
    assert result.exit_code == 0
    assert "--with-music" in _plain(result.output)
    assert "--with-voip" in _plain(result.output)
    assert "--with-power" in _plain(result.output)
    assert "--with-lvgl-soak" in _plain(result.output)
    assert "--test-music-dir" in _plain(result.output)


def test_pi_validate_help():
    result = runner.invoke(app, ["pi", "validate", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "deploy" in output
    assert "smoke" in output
    assert "music" in output
    assert "voip" in output
    assert "navigation" in output
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
    assert "--idle-seconds" in output
    assert "--with-music" in output
    assert "--test-music-dir" in output


def test_pi_validate_navigation_help():
    result = runner.invoke(
        app,
        ["pi", "validate", "navigation", "--help"],
        terminal_width=200,
    )
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--cycles" in output
    assert "--idle-seconds" in output
    assert "--tail-idle-seconds" in output
    assert "--with-playback" in output
    assert "--provision-test-mu" in output
    assert "--test-music-dir" in output


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
    result = runner.invoke(app, ["remote", "validate", "--help"], terminal_width=200)
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--branch" in output
    assert "--sha" in output
    assert "--with-music" in output
    assert "--with-navigation-s" in output
    assert "--test-music-dir" in output
    assert "--lines" in output


def test_remote_smoke_help():
    result = runner.invoke(app, ["remote", "smoke", "--help"], terminal_width=200)
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--test-music-dir" in output
    assert "--with-navigation-s" in output


def test_remote_provision_test_music_help():
    result = runner.invoke(app, ["remote", "provision-test-music", "--help"])
    assert result.exit_code == 0
    assert "--target-dir" in _plain(result.output)


def test_remote_preflight_help():
    result = runner.invoke(app, ["remote", "preflight", "--help"], terminal_width=200)
    assert result.exit_code == 0
    assert "--with-navigation-s" in _plain(result.output)


def test_remote_lvgl_soak_help():
    result = runner.invoke(app, ["remote", "lvgl-soak", "--help"])
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--cycles" in output
    assert "--hold-seconds" in output
    assert "--idle-seconds" in output
    assert "--with-music" in output
    assert "--test-music-dir" in output
    assert "--skip-sleep" in output


def test_remote_navigation_soak_help():
    result = runner.invoke(app, ["remote", "navigation-soak", "--help"], terminal_width=200)
    assert result.exit_code == 0
    output = _plain(result.output)
    assert "--cycles" in output
    assert "--idle-seconds" in output
    assert "--tail-idle-seconds" in output
    assert "--with-playback" in output
    assert "--provision-test-mu" in output
    assert "--test-music-dir" in output


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
