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


def test_ensure_native_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["ensure-native", "--help"])
    assert result.exit_code == 0
    assert "native" in result.output.lower()


def test_resolve_lvgl_native_dir_points_at_package_root() -> None:
    native_dir = build_cli._resolve_lvgl_native_dir()

    assert native_dir == build_cli._REPO_ROOT / "yoyopod" / "ui" / "lvgl_binding" / "native"
    assert (native_dir / "CMakeLists.txt").exists()


def test_resolve_liblinphone_native_dir_points_at_package_root() -> None:
    native_dir = build_cli._resolve_liblinphone_native_dir()

    assert native_dir == build_cli._REPO_ROOT / "yoyopod" / "backends" / "voip" / "shim_native"
    assert (native_dir / "CMakeLists.txt").exists()


def test_native_build_jobs_uses_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("YOYOPOD_NATIVE_BUILD_JOBS", "3")

    assert build_cli._native_build_jobs() == "3"


def test_native_build_jobs_drops_to_one_on_low_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YOYOPOD_NATIVE_BUILD_JOBS", raising=False)

    def fake_sysconf(name: str) -> int:
        if name == "SC_PAGE_SIZE":
            return 4096
        if name == "SC_PHYS_PAGES":
            return 200_000
        raise AssertionError(f"Unexpected sysconf key: {name}")

    monkeypatch.setattr(build_cli.os, "sysconf", fake_sysconf, raising=False)

    assert build_cli._native_build_jobs() == "1"


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


def test_ensure_native_shims_rebuilds_missing_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lvgl_native = tmp_path / "lvgl-native"
    lib_native = tmp_path / "liblinphone-native"
    lvgl_native.mkdir()
    lib_native.mkdir()

    calls: list[tuple[str, Path, Path | None]] = []

    monkeypatch.setattr(build_cli, "_resolve_lvgl_native_dir", lambda: lvgl_native)
    monkeypatch.setattr(build_cli, "_resolve_liblinphone_native_dir", lambda: lib_native)
    monkeypatch.setattr(build_cli, "_default_lvgl_source_dir", lambda: tmp_path / "lvgl-source")
    monkeypatch.setattr(build_cli, "_ensure_lvgl_source", lambda source_dir: calls.append(("fetch", source_dir, None)))
    monkeypatch.setattr(
        build_cli,
        "_build_lvgl",
        lambda native_dir, source_dir, build_dir: calls.append(("lvgl", native_dir, build_dir)),
    )
    monkeypatch.setattr(
        build_cli,
        "_build_liblinphone",
        lambda native_dir, build_dir: calls.append(("liblinphone", native_dir, build_dir)),
    )

    rebuilt = build_cli._ensure_native_shims()

    assert rebuilt == ("LVGL", "Liblinphone")
    assert ("fetch", tmp_path / "lvgl-source", None) in calls
    assert ("lvgl", lvgl_native, lvgl_native / "build") in calls
    assert ("liblinphone", lib_native, lib_native / "build") in calls


def test_ensure_native_shims_skips_current_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lvgl_native = tmp_path / "lvgl-native"
    lib_native = tmp_path / "liblinphone-native"
    (lvgl_native / "build").mkdir(parents=True)
    (lib_native / "build").mkdir(parents=True)
    (lvgl_native / "build" / "libyoyopod_lvgl_shim.so").write_text("ok", encoding="utf-8")
    (lib_native / "build" / "libyoyopod_liblinphone_shim.so").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(build_cli, "_resolve_lvgl_native_dir", lambda: lvgl_native)
    monkeypatch.setattr(build_cli, "_resolve_liblinphone_native_dir", lambda: lib_native)
    monkeypatch.setattr(build_cli, "_ensure_lvgl_source", lambda _source_dir: pytest.fail("fetch not expected"))
    monkeypatch.setattr(
        build_cli,
        "_build_lvgl",
        lambda *_args, **_kwargs: pytest.fail("LVGL rebuild not expected"),
    )
    monkeypatch.setattr(
        build_cli,
        "_build_liblinphone",
        lambda *_args, **_kwargs: pytest.fail("Liblinphone rebuild not expected"),
    )

    rebuilt = build_cli._ensure_native_shims()

    assert rebuilt == ()
