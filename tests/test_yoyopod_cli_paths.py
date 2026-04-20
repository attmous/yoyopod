"""Tests for yoyopod_cli.paths — the single source of truth for path constants."""
from __future__ import annotations

from pathlib import Path

import pytest

from yoyopod_cli.paths import (
    CONFIGS,
    HOST,
    PI_DEFAULTS,
    PROCS,
    PiPaths,
    load_pi_paths,
)


def test_host_paths_resolve() -> None:
    assert HOST.repo_root.exists()
    assert HOST.deploy_config == HOST.repo_root / "deploy" / "pi-deploy.yaml"
    assert HOST.deploy_config_local == HOST.repo_root / "deploy" / "pi-deploy.local.yaml"


def test_pi_defaults_populated() -> None:
    assert PI_DEFAULTS.project_dir == "~/YoyoPod_Core"
    assert PI_DEFAULTS.log_file == "logs/yoyopod.log"
    assert PI_DEFAULTS.pid_file == "/tmp/yoyopod.pid"
    assert "python" in PI_DEFAULTS.kill_processes


def test_configs_paths_exist() -> None:
    assert CONFIGS.core.exists()
    assert CONFIGS.music.exists()
    assert CONFIGS.calling.exists()


def test_procs_known() -> None:
    assert PROCS.app == "python yoyopod.py"
    assert PROCS.mpv == "mpv"


def test_load_pi_paths_returns_defaults_when_no_override(tmp_path) -> None:
    base_yaml = tmp_path / "base.yaml"
    base_yaml.write_text(
        "log_file: logs/yoyopod.log\n"
        "error_log_file: logs/yoyopod_errors.log\n"
        "pid_file: /tmp/yoyopod.pid\n"
        "startup_marker: YoyoPod starting\n"
    )
    local_yaml = tmp_path / "local.yaml"  # does not exist

    result = load_pi_paths(base_path=base_yaml, local_path=local_yaml)
    assert isinstance(result, PiPaths)
    assert result.log_file == "logs/yoyopod.log"
    assert result.project_dir == "~/YoyoPod_Core"  # default, no override


def test_load_pi_paths_null_yaml_value_falls_back_to_default(tmp_path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text("project_dir:\n")  # bare key, value is None
    local = tmp_path / "local.yaml"  # doesn't exist

    result = load_pi_paths(base_path=base, local_path=local)
    assert result.project_dir == "~/YoyoPod_Core"  # not 'None'


def test_load_pi_paths_applies_local_override(tmp_path) -> None:
    base_yaml = tmp_path / "base.yaml"
    base_yaml.write_text(
        "log_file: logs/yoyopod.log\n"
        "error_log_file: logs/yoyopod_errors.log\n"
        "pid_file: /tmp/yoyopod.pid\n"
        "startup_marker: YoyoPod starting\n"
    )
    local_yaml = tmp_path / "local.yaml"
    local_yaml.write_text("host: rpi-zero\nproject_dir: /opt/yoyopod\n")

    result = load_pi_paths(base_path=base_yaml, local_path=local_yaml)
    assert result.project_dir == "/opt/yoyopod"  # overridden
