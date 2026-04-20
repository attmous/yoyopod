"""Tests for yoyopod_cli.remote_config — show/edit pi-deploy.local.yaml."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from yoyopod_cli.remote_config import _resolve_editor_argv, app


def test_show_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["show", "--help"])
    assert result.exit_code == 0


def test_edit_help() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["edit", "--help"])
    assert result.exit_code == 0


def test_show_outputs_yaml(monkeypatch) -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["show"])
    assert result.exit_code == 0
    assert "project_dir" in result.output


def test_resolve_editor_argv_splits_configured_editor(monkeypatch) -> None:
    monkeypatch.setenv("EDITOR", "code -w --reuse-window")
    monkeypatch.delenv("VISUAL", raising=False)

    assert _resolve_editor_argv() == ["code", "-w", "--reuse-window"]


def test_edit_uses_split_editor_argv(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    target = tmp_path / "pi-deploy.local.yaml"

    monkeypatch.setattr(
        "yoyopod_cli.remote_config.HOST",
        SimpleNamespace(deploy_config_local=target),
    )
    monkeypatch.setenv("EDITOR", "code -w")
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr(
        "yoyopod_cli.remote_config.subprocess.run",
        lambda argv, check=False: calls.append(list(argv)) or SimpleNamespace(returncode=0),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["edit"])

    assert result.exit_code == 0, result.output
    assert calls == [["code", "-w", str(target)]]
    assert target.exists()


def test_edit_falls_back_to_installed_editor(monkeypatch, tmp_path: Path) -> None:
    calls: list[list[str]] = []
    target = tmp_path / "pi-deploy.local.yaml"

    monkeypatch.setattr(
        "yoyopod_cli.remote_config.HOST",
        SimpleNamespace(deploy_config_local=target),
    )
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr(
        "yoyopod_cli.remote_config.shutil.which",
        lambda name: "/usr/bin/vim" if name == "vim" else None,
    )
    monkeypatch.setattr(
        "yoyopod_cli.remote_config.subprocess.run",
        lambda argv, check=False: calls.append(list(argv)) or SimpleNamespace(returncode=0),
    )

    runner = CliRunner()
    result = runner.invoke(app, ["edit"])

    assert result.exit_code == 0, result.output
    assert calls == [["/usr/bin/vim", str(target)]]


def test_edit_errors_when_no_editor_is_available(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "pi-deploy.local.yaml"

    monkeypatch.setattr(
        "yoyopod_cli.remote_config.HOST",
        SimpleNamespace(deploy_config_local=target),
    )
    monkeypatch.delenv("EDITOR", raising=False)
    monkeypatch.delenv("VISUAL", raising=False)
    monkeypatch.setattr("yoyopod_cli.remote_config.shutil.which", lambda _name: None)

    runner = CliRunner()
    result = runner.invoke(app, ["edit"])

    assert result.exit_code == 1
    assert "No editor found" in result.output
