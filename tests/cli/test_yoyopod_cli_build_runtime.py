"""Tests for Rust runtime build CLI integration."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

import yoyopod_cli.build as build_cli
from yoyopod_cli.build import app


def test_build_help_includes_rust_runtime() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "rust-runtime" in result.output


def test_rust_runtime_paths_point_at_device_workspace() -> None:
    suffix = ".exe" if build_cli.os.name == "nt" else ""

    assert build_cli._rust_runtime_workspace_dir() == build_cli._REPO_ROOT / "device"
    assert build_cli._rust_runtime_crate_dir() == build_cli._REPO_ROOT / "device" / "runtime"
    assert build_cli._rust_runtime_binary_path() == (
        build_cli._REPO_ROOT
        / "device"
        / "runtime"
        / "build"
        / f"yoyopod-runtime{suffix}"
    )


def test_build_rust_runtime_invokes_cargo_workspace(
    monkeypatch,
    tmp_path: Path,
) -> None:
    workspace_dir = tmp_path / "src"
    crate_dir = workspace_dir / "runtime"
    crate_dir.mkdir(parents=True)
    calls: list[tuple[list[str], Path | None, dict[str, str] | None]] = []
    copies: list[tuple[Path, Path]] = []
    monkeypatch.setattr(build_cli, "_rust_runtime_workspace_dir", lambda: workspace_dir)
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

    output = build_cli.build_rust_runtime()

    assert output.name.startswith("yoyopod-runtime")
    assert calls == [
        (
            [
                "cargo",
                "build",
                "--release",
                "-p",
                "yoyopod-runtime",
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


def test_rust_runtime_command_echoes_built_path(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "yoyopod-runtime"
    monkeypatch.setattr(build_cli, "build_rust_runtime", lambda: output)

    runner = CliRunner()
    result = runner.invoke(app, ["rust-runtime"])

    assert result.exit_code == 0
    assert "Built Rust runtime:" in result.output
    assert str(output) in result.output
