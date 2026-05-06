"""Focused tests for extracted remote-config and transport helpers."""

import subprocess
import sys
from pathlib import Path

from yoyopod_cli.defaults import DEFAULT_TEST_MUSIC_TARGET_DIR
from yoyopod_cli.paths import load_pi_paths
from yoyopod_cli.remote_config import DEFAULT_TEST_MUSIC_TARGET_DIR as REMOTE_CONFIG_TEST_MUSIC_DIR
from yoyopod_cli.remote_shared import RemoteConnection, _resolve_remote_connection
from yoyopod_cli.remote_transport import build_ssh_command


def test_resolve_remote_config_prefers_cli_values_over_defaults(monkeypatch) -> None:
    """Explicit CLI args should win over env and tracked deploy defaults."""

    monkeypatch.setenv("YOYOPOD_PI_HOST", "env-host")
    monkeypatch.setenv("YOYOPOD_PI_USER", "env-user")
    monkeypatch.setenv("YOYOPOD_PI_PROJECT_DIR", "~/env-yoyo")
    monkeypatch.setenv("YOYOPOD_PI_BRANCH", "env-branch")

    config = _resolve_remote_connection(
        host="cli-host",
        user="cli-user",
        project_dir="~/cli-yoyo",
        branch="cli-branch",
    )

    assert config.host == "cli-host"
    assert config.user == "cli-user"
    assert config.project_dir == "~/cli-yoyo"
    assert config.branch == "cli-branch"


def test_build_ssh_command_cd_wraps_remote_project_dir() -> None:
    """SSH commands should always enter the configured project directory first."""

    config = RemoteConnection(host="rpi-zero", user="pi", project_dir="~/Yoyo Pod", branch="main")

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
                "project_dir: /opt/yoyopod-dev/checkout",
                "branch: main",
                "venv: .venv",
                "start_cmd: device/runtime/build/yoyopod-runtime --config-dir config",
                "kill_processes: [yoyopod-runtime]",
                "log_file: logs/yoyopod.log",
                "error_log_file: logs/yoyopod_errors.log",
                "pid_file: /tmp/yoyopod.pid",
                'startup_marker: "YoYoPod Rust runtime starting"',
                "screenshot_path: /tmp/yoyopod_screenshot.png",
                "rsync_exclude: [.git/, .cache/, build/, logs/]",
            ]
        ),
        encoding="utf-8",
    )

    pi = load_pi_paths(
        base_path=base_path,
        local_path=Path(tmp_path / "missing.local.yaml"),
    )

    assert pi.project_dir == "/opt/yoyopod-dev/checkout"
    assert pi.test_music_target_dir == DEFAULT_TEST_MUSIC_TARGET_DIR
    assert REMOTE_CONFIG_TEST_MUSIC_DIR == DEFAULT_TEST_MUSIC_TARGET_DIR


def test_remote_config_imports_cleanly_in_fresh_interpreter() -> None:
    """Remote config should expose shared defaults without importing the old pi package."""

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from yoyopod_cli.remote_config import DEFAULT_TEST_MUSIC_TARGET_DIR; "
            "print(DEFAULT_TEST_MUSIC_TARGET_DIR)",
        ],
        capture_output=True,
        check=False,
        cwd=Path(__file__).resolve().parents[2],
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == DEFAULT_TEST_MUSIC_TARGET_DIR
