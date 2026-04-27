"""Tests for yoyopod_cli.pi.validate."""
from __future__ import annotations

import sys
from types import ModuleType

from typer.testing import CliRunner

from yoyopod_cli.pi import validate as pi_validate
from yoyopod_cli.pi.validate import app
from yoyopod_cli.pi.validate import system as _system


def _collect_option_names(click_cmd: object) -> set[str]:
    names: set[str] = set()
    for param in getattr(click_cmd, "params", []):
        names.update(getattr(param, "opts", []))
    return names


def test_deploy_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["deploy", "--help"])
    assert result.exit_code == 0


def test_smoke_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["smoke", "--help"])
    assert result.exit_code == 0


def test_music_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["music", "--help"])
    assert result.exit_code == 0


def test_voip_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["voip", "--help"])
    assert result.exit_code == 0


def test_stability_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["stability", "--help"])
    assert result.exit_code == 0


def test_navigation_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["navigation", "--help"])
    assert result.exit_code == 0


def test_all_six_base_subcommands_present() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("deploy", "smoke", "music", "voip", "stability", "navigation"):
        assert name in result.output


def test_voip_soak_flag_registered() -> None:
    import typer.main

    click_cmd = typer.main.get_command(app)
    voip_cmd = click_cmd.commands["voip"]  # type: ignore[attr-defined]
    names = _collect_option_names(voip_cmd)
    assert "--soak" in names


def test_voip_soak_call_requires_target() -> None:
    import re
    import typer

    runner = CliRunner()
    result = runner.invoke(app, ["voip", "--soak", "call"])
    assert result.exit_code != 0

    # BadParameter gets wrapped in SystemExit by Click's error handler.
    # The original exception is preserved on result.exc_info (a tuple) when
    # catch_exceptions=True (default).
    if result.exc_info is not None:
        _type, exc, _tb = result.exc_info
        if isinstance(exc, typer.BadParameter):
            assert "soak-target" in str(exc).lower()
            return

    # Fallback: strip ANSI codes and check in the combined output.
    ansi_re = re.compile(r"\x1b\[[0-9;]*m")
    stripped = ansi_re.sub("", result.output)
    assert "soak-target" in stripped.lower(), (
        f"BadParameter message missing from output. Got exit={result.exit_code}, "
        f"exc_info={result.exc_info}, output_stripped={stripped!r}"
    )


def test_voip_soak_unknown_value_rejected() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["voip", "--soak", "invalid"])
    assert result.exit_code != 0


def test_lvgl_help() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["lvgl", "--help"])
    assert result.exit_code == 0


def test_all_seven_subcommands_present() -> None:
    runner = CliRunner(env={'COLUMNS': '200'})
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("deploy", "smoke", "music", "voip", "stability", "navigation", "lvgl"):
        assert name in result.output


def test_display_check_prefers_lvgl_probe_when_ui_backend_is_available(
    monkeypatch,
) -> None:
    ui_calls: list[tuple[str, int | None]] = []

    class FakeUiBackend:
        def initialize(self) -> bool:
            ui_calls.append(("initialize", None))
            return True

        def show_probe_scene(self, scene_id: int) -> None:
            ui_calls.append(("show_probe_scene", scene_id))

        def force_refresh(self) -> None:
            ui_calls.append(("force_refresh", None))

        def pump(self, milliseconds: int) -> None:
            ui_calls.append(("pump", milliseconds))

    class FakeAdapter:
        pass

    class FakeDisplay:
        COLOR_BLACK = (0, 0, 0)
        COLOR_WHITE = (255, 255, 255)
        COLOR_GREEN = (0, 255, 0)

        def __init__(self, hardware: str, simulate: bool) -> None:
            assert hardware == "whisplay"
            assert simulate is False
            self.WIDTH = 240
            self.HEIGHT = 280
            self.ORIENTATION = "portrait"
            self.simulate = False
            self.backend_kind = "unavailable"
            self._adapter = FakeAdapter()
            self._ui_backend = FakeUiBackend()

        def get_adapter(self) -> FakeAdapter:
            return self._adapter

        def get_ui_backend(self) -> FakeUiBackend:
            return self._ui_backend

        def refresh_backend_kind(self) -> str:
            self.backend_kind = "lvgl"
            return self.backend_kind

        def clear(self, color) -> None:
            raise AssertionError("LVGL smoke path should not call immediate draw helpers")

        def text(self, *args, **kwargs) -> None:
            raise AssertionError("LVGL smoke path should not call immediate draw helpers")

        def update(self) -> None:
            raise AssertionError("LVGL smoke path should not call immediate draw helpers")

    fake_display_module = ModuleType("yoyopod.ui.display")
    fake_display_module.Display = FakeDisplay
    fake_display_module.detect_hardware = lambda: "whisplay"
    monkeypatch.setitem(sys.modules, "yoyopod.ui.display", fake_display_module)

    result, _display = _system._display_check({"display": {"hardware": "auto"}}, 0.0)

    assert result.status == "pass"
    assert "backend=lvgl" in result.details
    assert ui_calls == [
        ("initialize", None),
        ("show_probe_scene", 1),
        ("force_refresh", None),
        ("pump", 16),
    ]


def test_display_check_keeps_immediate_draw_path_without_ui_backend(monkeypatch) -> None:
    draw_calls: list[str] = []

    class FakeAdapter:
        pass

    class FakeDisplay:
        COLOR_BLACK = (0, 0, 0)
        COLOR_WHITE = (255, 255, 255)
        COLOR_GREEN = (0, 255, 0)

        def __init__(self, hardware: str, simulate: bool) -> None:
            assert hardware == "pimoroni"
            assert simulate is False
            self.WIDTH = 320
            self.HEIGHT = 240
            self.ORIENTATION = "landscape"
            self.simulate = False
            self.backend_kind = "pil"
            self._adapter = FakeAdapter()

        def get_adapter(self) -> FakeAdapter:
            return self._adapter

        def get_ui_backend(self):
            return None

        def clear(self, color) -> None:
            draw_calls.append("clear")

        def text(self, text: str, x: int, y: int, **kwargs) -> None:
            draw_calls.append(text)

        def update(self) -> None:
            draw_calls.append("update")

    fake_display_module = ModuleType("yoyopod.ui.display")
    fake_display_module.Display = FakeDisplay
    fake_display_module.detect_hardware = lambda: "pimoroni"
    monkeypatch.setitem(sys.modules, "yoyopod.ui.display", fake_display_module)

    result, _display = _system._display_check({"display": {"hardware": "auto"}}, 0.0)

    assert result.status == "pass"
    assert "backend=pil" in result.details
    assert draw_calls == ["clear", "YoYoPod Pi smoke", "Display OK", "update"]
