"""Tests for the shared Pi-connection options callback."""

from __future__ import annotations

import typer
from typer.testing import CliRunner

from yoyopod_cli.remote_shared import (
    RemoteConnection,
    _resolve_remote_connection,
    build_remote_app,
    pi_conn,
)


def test_remote_connection_ssh_target_with_user() -> None:
    conn = RemoteConnection(host="rpi-zero", user="pi", project_dir="~", branch="main")
    assert conn.ssh_target == "pi@rpi-zero"


def test_remote_connection_ssh_target_without_user() -> None:
    conn = RemoteConnection(host="rpi-zero", user="", project_dir="~", branch="main")
    assert conn.ssh_target == "rpi-zero"


def test_build_remote_app_captures_cli_flags() -> None:
    app = build_remote_app("ops", "Test ops group.")

    captured: dict[str, object] = {}

    @app.command()
    def echo(ctx: typer.Context) -> None:
        conn = pi_conn(ctx)
        captured["host"] = conn.host
        captured["user"] = conn.user
        captured["project_dir"] = conn.project_dir
        captured["branch"] = conn.branch

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--host",
            "rpi-zero",
            "--user",
            "pi",
            "--project-dir",
            "/opt/yoyopod",
            "--branch",
            "feature-x",
            "echo",
        ],
    )
    assert result.exit_code == 0, result.output
    assert captured["host"] == "rpi-zero"
    assert captured["user"] == "pi"
    assert captured["project_dir"] == "/opt/yoyopod"
    assert captured["branch"] == "feature-x"


def test_build_remote_app_defaults_from_env(monkeypatch) -> None:
    monkeypatch.setenv("YOYOPOD_PI_HOST", "env-host")
    monkeypatch.setenv("YOYOPOD_PI_USER", "env-user")

    app = build_remote_app("ops", "Test ops group.")

    captured: dict[str, object] = {}

    @app.command()
    def echo(ctx: typer.Context) -> None:
        conn = pi_conn(ctx)
        captured["host"] = conn.host
        captured["user"] = conn.user

    runner = CliRunner()
    result = runner.invoke(app, ["echo"])
    assert result.exit_code == 0, result.output
    assert captured["host"] == "env-host"
    assert captured["user"] == "env-user"


def test_build_remote_app_defaults_from_yaml(tmp_path, monkeypatch) -> None:
    """When no CLI flag and no env var, YAML defaults should win."""
    from yoyopod_cli import remote_shared as _remote_shared

    base_yaml = tmp_path / "pi-deploy.yaml"
    base_yaml.write_text(
        "host: yaml-host\n" "user: yaml-user\n" "branch: yaml-branch\n" "project_dir: /yaml/proj\n"
    )
    local_yaml = tmp_path / "pi-deploy.local.yaml"  # does not exist

    # Point the module-level HOST singleton at our tmp files
    class FakeHost:
        repo_root = tmp_path
        deploy_config = base_yaml
        deploy_config_local = local_yaml
        systemd_unit_template = tmp_path / "yoyopod@.service"

    monkeypatch.setattr(_remote_shared, "HOST", FakeHost)

    # Ensure no env vars leak in
    monkeypatch.delenv("YOYOPOD_PI_HOST", raising=False)
    monkeypatch.delenv("YOYOPOD_PI_USER", raising=False)
    monkeypatch.delenv("YOYOPOD_PI_PROJECT_DIR", raising=False)
    monkeypatch.delenv("YOYOPOD_PI_BRANCH", raising=False)

    app = _remote_shared.build_remote_app("ops", "YAML-defaults test.")

    captured: dict[str, object] = {}

    @app.command()
    def echo(ctx: typer.Context) -> None:
        conn = _remote_shared.pi_conn(ctx)
        captured["host"] = conn.host
        captured["user"] = conn.user
        captured["project_dir"] = conn.project_dir
        captured["branch"] = conn.branch

    runner = CliRunner()
    result = runner.invoke(app, ["echo"])
    assert result.exit_code == 0, result.output
    assert captured["host"] == "yaml-host"
    assert captured["user"] == "yaml-user"
    assert captured["branch"] == "yaml-branch"
    assert captured["project_dir"] == "/yaml/proj"


def test_build_remote_app_project_dir_follows_lane_dev_root_override(
    tmp_path, monkeypatch
) -> None:
    """Remote commands should use the resolved dev lane checkout by default."""
    from yoyopod_cli import remote_shared as _remote_shared

    base_yaml = tmp_path / "pi-deploy.yaml"
    base_yaml.write_text(
        "host: yaml-host\n"
        "project_dir: /opt/yoyopod-dev/checkout\n"
        "lane:\n"
        "  dev_root: /opt/yoyopod-dev\n"
        "  dev_checkout: /opt/yoyopod-dev/checkout\n"
    )
    local_yaml = tmp_path / "pi-deploy.local.yaml"
    local_yaml.write_text("lane:\n  dev_root: /srv/yoyopod-dev\n")

    class FakeHost:
        repo_root = tmp_path
        deploy_config = base_yaml
        deploy_config_local = local_yaml
        systemd_unit_template = tmp_path / "yoyopod@.service"

    monkeypatch.setattr(_remote_shared, "HOST", FakeHost)
    monkeypatch.delenv("YOYOPOD_PI_PROJECT_DIR", raising=False)

    config = _remote_shared._resolve_remote_connection("", "", "", "")

    assert config.project_dir == "/srv/yoyopod-dev/checkout"


def test_resolve_remote_connection_treats_null_local_overrides_as_unset(
    tmp_path, monkeypatch
) -> None:
    """Null values in the local override should fall back to base/default values."""
    from yoyopod_cli import remote_shared as _remote_shared

    base_yaml = tmp_path / "pi-deploy.yaml"
    base_yaml.write_text(
        "host: yaml-host\n" "user: yaml-user\n" "branch: yaml-branch\n" "project_dir: /yaml/proj\n"
    )
    local_yaml = tmp_path / "pi-deploy.local.yaml"
    local_yaml.write_text("host:\n" "user:\n" "branch:\n" "project_dir:\n")

    class FakeHost:
        repo_root = tmp_path
        deploy_config = base_yaml
        deploy_config_local = local_yaml
        systemd_unit_template = tmp_path / "yoyopod@.service"

    monkeypatch.setattr(_remote_shared, "HOST", FakeHost)
    monkeypatch.delenv("YOYOPOD_PI_HOST", raising=False)
    monkeypatch.delenv("YOYOPOD_PI_USER", raising=False)
    monkeypatch.delenv("YOYOPOD_PI_PROJECT_DIR", raising=False)
    monkeypatch.delenv("YOYOPOD_PI_BRANCH", raising=False)

    config = _resolve_remote_connection("", "", "", "")

    assert config.host == "yaml-host"
    assert config.user == "yaml-user"
    assert config.project_dir == "/yaml/proj"
    assert config.branch == "yaml-branch"
