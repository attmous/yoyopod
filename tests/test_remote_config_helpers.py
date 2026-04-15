"""Focused tests for extracted remote-config and transport helpers."""

from pathlib import Path

from yoyopy.cli.remote.config import load_pi_deploy_config, resolve_remote_config
from yoyopy.cli.remote.transport import build_ssh_command


def test_resolve_remote_config_prefers_cli_values_over_defaults(monkeypatch) -> None:
    """Explicit CLI args should win over env and tracked deploy defaults."""

    monkeypatch.setenv("YOYOPOD_PI_HOST", "env-host")
    monkeypatch.setenv("YOYOPOD_PI_USER", "env-user")
    monkeypatch.setenv("YOYOPOD_PI_PROJECT_DIR", "~/env-yoyo")
    monkeypatch.setenv("YOYOPOD_PI_BRANCH", "env-branch")

    config = resolve_remote_config("cli-host", "cli-user", "~/cli-yoyo", "cli-branch")

    assert config.host == "cli-host"
    assert config.user == "cli-user"
    assert config.project_dir == "~/cli-yoyo"
    assert config.branch == "cli-branch"


def test_build_ssh_command_cd_wraps_remote_project_dir() -> None:
    """SSH commands should always enter the configured project directory first."""

    from yoyopy.cli.remote.config import RemoteConfig

    config = RemoteConfig(host="rpi-zero", user="pi", project_dir="~/Yoyo Pod", branch="main")

    command = build_ssh_command(config, "git status", tty=True)

    assert command[0:2] == ["ssh", "-t"]
    assert command[2] == "pi@rpi-zero"
    assert 'cd "$HOME/Yoyo Pod" && git status' in command[3]


def test_load_pi_deploy_config_uses_tracked_defaults_without_local_override(tmp_path) -> None:
    """Tracked deploy config should still parse cleanly when no local layer exists."""

    base_path = tmp_path / "pi-deploy.yaml"
    base_path.write_text(
        "\n".join(
            [
                "host: rpi-zero",
                "user: pi",
                "project_dir: ~/YoyoPod_Core",
                "branch: main",
                "venv: .venv",
                "start_cmd: python yoyopod.py",
                "kill_processes: [python, linphonec]",
                "log_file: logs/yoyopod.log",
                "error_log_file: logs/yoyopod_errors.log",
                "pid_file: /tmp/yoyopod.pid",
                'startup_marker: "YoyoPod starting"',
                "screenshot_path: /tmp/yoyopod_screenshot.png",
                "rsync_exclude: [.git/, .cache/, build/, logs/]",
            ]
        ),
        encoding="utf-8",
    )

    config = load_pi_deploy_config(
        config_path=base_path,
        local_override_path=Path(tmp_path / "missing.local.yaml"),
    )

    assert config.host == "rpi-zero"
    assert config.user == "pi"
    assert config.project_dir == "~/YoyoPod_Core"
