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


def test_ensure_native_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["ensure-native", "--help"])
    assert result.exit_code == 0
    assert "native" in result.output.lower()


def test_clean_native_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["clean-native", "--help"])
    assert result.exit_code == 0
    assert "native" in result.output.lower()


def test_simulation_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["simulation", "--help"])
    assert result.exit_code == 0
    assert "simulate" in result.output.lower()


def test_voice_worker_build_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["voice-worker", "--help"])

    assert result.exit_code == 0
    assert "rust speech host" in result.output.lower()


def test_rust_ui_poc_build_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["rust-ui-poc", "--help"])

    assert result.exit_code == 0
    assert "rust-ui-host" in result.output.lower()


def test_rust_ui_host_build_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["rust-ui-host", "--help"])

    assert result.exit_code == 0
    assert "rust ui host" in result.output.lower()


def test_voice_worker_build_command_invokes_builder(monkeypatch: pytest.MonkeyPatch) -> None:
    output = Path("/tmp/yoyopod-speech-host")
    monkeypatch.setattr(build_cli, "build_voice_worker", lambda: output)

    runner = CliRunner()
    result = runner.invoke(app, ["voice-worker"])

    assert result.exit_code == 0
    assert "Built Rust speech host:" in result.output
    assert str(output) in result.output
    assert output.name in result.output


def test_resolve_lvgl_native_dir_points_at_package_root() -> None:
    native_dir = build_cli._resolve_lvgl_native_dir()

    assert native_dir == build_cli._REPO_ROOT / "yoyopod" / "ui" / "lvgl_binding" / "native"
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


def test_build_simulation_builds_lvgl_shim(
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
    monkeypatch.setattr(build_cli, "_default_lvgl_source_dir", lambda: tmp_path / "lvgl-source")

    build_cli.build_simulation(skip_fetch=True)

    assert captured == {
        "native_dir": build_cli._REPO_ROOT / "yoyopod" / "ui" / "lvgl_binding" / "native",
        "source_dir": tmp_path / "lvgl-source",
        "build_dir": build_cli._REPO_ROOT / "yoyopod" / "ui" / "lvgl_binding" / "native" / "build",
    }


def test_build_voice_worker_invokes_rust_speech_host_build(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_dir = tmp_path / "src"
    crate_dir = workspace_dir / "speech-host"
    crate_dir.mkdir(parents=True)
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []
    copies: list[tuple[Path, Path]] = []
    monkeypatch.setattr(build_cli, "_rust_speech_host_workspace_dir", lambda: workspace_dir)
    monkeypatch.setattr(
        build_cli,
        "_run",
        lambda command, cwd=None, env=None: calls.append((command, cwd, env)),
    )
    monkeypatch.setattr(
        build_cli.shutil,
        "copy2",
        lambda source, target: copies.append((Path(source), Path(target))),
    )

    output = build_cli.build_voice_worker()

    assert output.name.startswith("yoyopod-speech-host")
    assert calls == [
        (
            [
                "cargo",
                "build",
                "--release",
                "-p",
                "yoyopod-speech-host",
                "--locked",
            ],
            workspace_dir,
            None,
        )
    ]
    assert copies == [
        (
            workspace_dir / "target" / "release" / output.name,
            crate_dir / "build" / output.name,
        )
    ]


def test_rust_ui_host_paths_point_at_yoyopod_rs_workspace() -> None:
    suffix = ".exe" if build_cli.os.name == "nt" else ""

    assert build_cli._rust_ui_host_workspace_dir() == build_cli._REPO_ROOT / "yoyopod_rs"
    assert build_cli._rust_ui_host_crate_dir() == build_cli._REPO_ROOT / "yoyopod_rs" / "ui-host"
    assert build_cli._rust_ui_host_binary_path() == (
        build_cli._REPO_ROOT / "yoyopod_rs" / "ui-host" / "build" / f"yoyopod-ui-host{suffix}"
    )


def test_build_rust_ui_poc_invokes_cargo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_dir = tmp_path / "src"
    crate_dir = workspace_dir / "ui-host"
    crate_dir.mkdir(parents=True)
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []
    copies: list[tuple[Path, Path]] = []
    monkeypatch.setattr(build_cli, "_rust_ui_host_workspace_dir", lambda: workspace_dir)
    monkeypatch.setattr(
        build_cli,
        "_run",
        lambda command, cwd=None, env=None: calls.append((command, cwd, env)),
    )
    monkeypatch.setattr(
        build_cli.shutil,
        "copy2",
        lambda source, target: copies.append((Path(source), Path(target))),
    )

    output = build_cli.build_rust_ui_poc()

    assert output.name.startswith("yoyopod-ui-host")
    assert calls[0][0] == [
        "cargo",
        "build",
        "--release",
        "-p",
        "yoyopod-ui-host",
        "--locked",
        "--features",
        "whisplay-hardware",
    ]
    assert calls[0][1] == workspace_dir
    assert copies == [(workspace_dir / "target" / "release" / output.name, output)]


def test_build_rust_ui_host_invokes_cargo_workspace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_dir = tmp_path / "src"
    crate_dir = workspace_dir / "ui-host"
    crate_dir.mkdir(parents=True)
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []
    copies: list[tuple[Path, Path]] = []
    monkeypatch.setattr(build_cli, "_rust_ui_host_workspace_dir", lambda: workspace_dir)
    monkeypatch.setattr(
        build_cli,
        "_run",
        lambda command, cwd=None, env=None: calls.append((command, cwd, env)),
    )
    monkeypatch.setattr(
        build_cli.shutil,
        "copy2",
        lambda source, target: copies.append((Path(source), Path(target))),
    )

    output = build_cli.build_rust_ui_host()

    assert output.name.startswith("yoyopod-ui-host")
    assert calls == [
        (
            [
                "cargo",
                "build",
                "--release",
                "-p",
                "yoyopod-ui-host",
                "--locked",
                "--features",
                "whisplay-hardware",
            ],
            workspace_dir,
            None,
        )
    ]
    assert copies == [
        (
            workspace_dir / "target" / "release" / output.name,
            crate_dir / "build" / output.name,
        )
    ]


def test_ensure_native_shims_rebuilds_lvgl_without_liblinphone_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lvgl_native = tmp_path / "lvgl-native"
    lvgl_native.mkdir()

    calls: list[tuple[str, Path, Path | None]] = []

    monkeypatch.setattr(build_cli, "_resolve_lvgl_native_dir", lambda: lvgl_native)
    monkeypatch.setattr(build_cli, "_default_lvgl_source_dir", lambda: tmp_path / "lvgl-source")
    monkeypatch.setattr(
        build_cli,
        "_ensure_lvgl_source",
        lambda source_dir: calls.append(("fetch", source_dir, None)),
    )
    monkeypatch.setattr(
        build_cli,
        "_build_lvgl",
        lambda native_dir, source_dir, build_dir: calls.append(("lvgl", native_dir, build_dir)),
    )
    monkeypatch.setattr(build_cli.shutil, "which", lambda _command: None)
    rebuilt = build_cli._ensure_native_shims()

    assert rebuilt == ("LVGL",)
    assert ("fetch", tmp_path / "lvgl-source", None) in calls
    assert ("lvgl", lvgl_native, lvgl_native / "build") in calls


def test_ensure_native_shims_skips_current_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lvgl_native = tmp_path / "lvgl-native"
    (lvgl_native / "build").mkdir(parents=True)
    (lvgl_native / "build" / "libyoyopod_lvgl_shim.so").write_text("ok", encoding="utf-8")

    monkeypatch.setattr(build_cli, "_resolve_lvgl_native_dir", lambda: lvgl_native)
    monkeypatch.setattr(
        build_cli, "_ensure_lvgl_source", lambda _source_dir: pytest.fail("fetch not expected")
    )
    monkeypatch.setattr(
        build_cli,
        "_build_lvgl",
        lambda *_args, **_kwargs: pytest.fail("LVGL rebuild not expected"),
    )
    monkeypatch.setattr(build_cli.shutil, "which", lambda _command: None)

    rebuilt = build_cli._ensure_native_shims()

    assert rebuilt == ()


def test_clean_native_build_dirs_removes_mutable_cmake_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    lvgl_native = tmp_path / "lvgl-native"
    build_dir = lvgl_native / "build"
    build_dir.mkdir(parents=True)
    (build_dir / "CMakeCache.txt").write_text("stale\n", encoding="utf-8")

    monkeypatch.setattr(build_cli, "_resolve_lvgl_native_dir", lambda: lvgl_native)

    removed = build_cli._clean_native_build_dirs()

    assert removed == (lvgl_native / "build",)
    assert not (lvgl_native / "build").exists()
