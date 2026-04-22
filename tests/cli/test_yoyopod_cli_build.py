"""Tests for yoyopod_cli.build — native extension build commands."""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

import yoyopod_cli.build as build_cli
from yoyopod_cli.build import app


def test_lvgl_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["lvgl", "--help"])
    assert result.exit_code == 0
    assert "lvgl" in result.output.lower()


def test_liblinphone_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["liblinphone", "--help"])
    assert result.exit_code == 0
    assert "liblinphone" in result.output.lower()


def test_resolve_lvgl_native_dir_points_at_package_root() -> None:
    native_dir = build_cli._resolve_lvgl_native_dir()

    assert native_dir == build_cli._REPO_ROOT / "yoyopod" / "ui" / "lvgl_binding" / "native"
    assert (native_dir / "CMakeLists.txt").exists()


def test_resolve_liblinphone_native_dir_points_at_package_root() -> None:
    native_dir = build_cli._resolve_liblinphone_native_dir()

    assert native_dir == build_cli._REPO_ROOT / "yoyopod" / "backends" / "voip" / "shim_native"
    assert (native_dir / "CMakeLists.txt").exists()


def test_build_lvgl_uses_resolved_native_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Path] = {}

    monkeypatch.setattr(build_cli, "_ensure_lvgl_source", lambda _source_dir: None)

    def fake_build(native_dir: Path, source_dir: Path, build_dir: Path) -> None:
        captured["native_dir"] = native_dir
        captured["source_dir"] = source_dir
        captured["build_dir"] = build_dir

    monkeypatch.setattr(build_cli, "_build_lvgl", fake_build)

    source_dir = tmp_path / "lvgl-source"
    build_dir = tmp_path / "lvgl-build"
    build_cli.build_lvgl(source_dir=source_dir, build_dir=build_dir, skip_fetch=True)

    assert captured == {
        "native_dir": build_cli._REPO_ROOT / "yoyopod" / "ui" / "lvgl_binding" / "native",
        "source_dir": source_dir,
        "build_dir": build_dir,
    }


def test_build_liblinphone_uses_resolved_native_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, Path] = {}

    def fake_build(native_dir: Path, build_dir: Path) -> None:
        captured["native_dir"] = native_dir
        captured["build_dir"] = build_dir

    monkeypatch.setattr(build_cli, "_build_liblinphone", fake_build)

    build_dir = tmp_path / "liblinphone-build"
    build_cli.build_liblinphone(build_dir=build_dir)

    assert captured == {
        "native_dir": build_cli._REPO_ROOT / "yoyopod" / "backends" / "voip" / "shim_native",
        "build_dir": build_dir,
    }
