"""Tests for yoyopod_cli.paths — the single source of truth for path constants."""

from __future__ import annotations

from yoyopod_cli.paths import (
    CONFIGS,
    HOST,
    LANES,
    PI_DEFAULTS,
    PROCS,
    LanePaths,
    PiPaths,
    load_lane_paths,
    load_pi_paths,
)


def test_host_paths_resolve() -> None:
    assert HOST.repo_root.exists()
    assert HOST.deploy_config == HOST.repo_root / "deploy" / "pi-deploy.yaml"
    assert HOST.deploy_config_local == HOST.repo_root / "deploy" / "pi-deploy.local.yaml"


def test_pi_defaults_populated() -> None:
    assert PI_DEFAULTS.project_dir == "/opt/yoyopod-dev/checkout"
    assert PI_DEFAULTS.venv == "/opt/yoyopod-dev/venv"
    assert PI_DEFAULTS.start_cmd == "device/runtime/build/yoyopod-runtime --config-dir config"
    assert PI_DEFAULTS.log_file == "logs/yoyopod.log"
    assert PI_DEFAULTS.pid_file == "/tmp/yoyopod.pid"
    assert "yoyopod-runtime" in PI_DEFAULTS.kill_processes
    assert "python" not in PI_DEFAULTS.kill_processes
    assert "linphonec" not in PI_DEFAULTS.kill_processes


def test_lane_defaults_populated() -> None:
    assert LANES == LanePaths()
    assert LANES.dev_root == "/opt/yoyopod-dev"
    assert LANES.dev_checkout == "/opt/yoyopod-dev/checkout"
    assert LANES.dev_venv == "/opt/yoyopod-dev/venv"
    assert LANES.prod_root == "/opt/yoyopod-prod"
    assert LANES.dev_service == "yoyopod-dev.service"
    assert LANES.prod_service == "yoyopod-prod.service"
    assert LANES.prod_ota_timer == "yoyopod-prod-ota.timer"


def test_configs_paths_exist() -> None:
    assert CONFIGS.core.exists()
    assert CONFIGS.music.exists()
    assert CONFIGS.calling.exists()


def test_procs_known() -> None:
    assert PROCS.app == "device/runtime/build/yoyopod-runtime --config-dir config"
    assert PROCS.mpv == "mpv"
    assert not hasattr(PROCS, "linphonec")


def test_load_pi_paths_returns_defaults_when_no_override(tmp_path) -> None:
    base_yaml = tmp_path / "base.yaml"
    base_yaml.write_text(
        "log_file: logs/yoyopod.log\n"
        "error_log_file: logs/yoyopod_errors.log\n"
        "pid_file: /tmp/yoyopod.pid\n"
        "startup_marker: YoYoPod starting\n"
    )
    local_yaml = tmp_path / "local.yaml"  # does not exist

    result = load_pi_paths(base_path=base_yaml, local_path=local_yaml)
    assert isinstance(result, PiPaths)
    assert result.log_file == "logs/yoyopod.log"
    assert result.project_dir == "/opt/yoyopod-dev/checkout"  # default, no override
    assert result.venv == "/opt/yoyopod-dev/venv"


def test_load_pi_paths_null_yaml_value_falls_back_to_default(tmp_path) -> None:
    base = tmp_path / "base.yaml"
    base.write_text("project_dir:\n")  # bare key, value is None
    local = tmp_path / "local.yaml"  # doesn't exist

    result = load_pi_paths(base_path=base, local_path=local)
    assert result.project_dir == "/opt/yoyopod-dev/checkout"  # not 'None'


def test_load_lane_paths_applies_lane_overrides(tmp_path) -> None:
    base_yaml = tmp_path / "base.yaml"
    base_yaml.write_text(
        "lane:\n"
        "  dev_root: /opt/yoyopod-dev\n"
        "  prod_root: /opt/yoyopod-prod\n"
    )
    local_yaml = tmp_path / "local.yaml"
    local_yaml.write_text(
        "lane:\n"
        "  dev_root: /srv/yoyopod-dev\n"
        "  dev_checkout: /srv/yoyopod-dev/checkout\n"
        "  dev_venv: /srv/yoyopod-dev/venv\n"
    )

    result = load_lane_paths(base_path=base_yaml, local_path=local_yaml)
    assert result.dev_root == "/srv/yoyopod-dev"
    assert result.dev_checkout == "/srv/yoyopod-dev/checkout"
    assert result.dev_venv == "/srv/yoyopod-dev/venv"
    assert result.prod_root == "/opt/yoyopod-prod"


def test_load_pi_paths_prefers_lane_dev_overrides_over_base_top_level_defaults(
    tmp_path,
) -> None:
    base_yaml = tmp_path / "base.yaml"
    base_yaml.write_text(
        "project_dir: /opt/yoyopod-dev/checkout\n"
        "venv: /opt/yoyopod-dev/venv\n"
        "lane:\n"
        "  dev_root: /opt/yoyopod-dev\n"
        "  dev_checkout: /opt/yoyopod-dev/checkout\n"
        "  dev_venv: /opt/yoyopod-dev/venv\n"
    )
    local_yaml = tmp_path / "local.yaml"
    local_yaml.write_text("lane:\n  dev_root: /srv/yoyopod-dev\n")

    result = load_pi_paths(base_path=base_yaml, local_path=local_yaml)

    assert result.project_dir == "/srv/yoyopod-dev/checkout"
    assert result.venv == "/srv/yoyopod-dev/venv"


def test_load_lane_paths_derives_dev_subpaths_from_dev_root(tmp_path) -> None:
    base_yaml = tmp_path / "base.yaml"
    base_yaml.write_text("lane:\n  dev_root: /srv/yoyopod-dev\n")
    local_yaml = tmp_path / "local.yaml"

    result = load_lane_paths(base_path=base_yaml, local_path=local_yaml)

    assert result.dev_checkout == "/srv/yoyopod-dev/checkout"
    assert result.dev_venv == "/srv/yoyopod-dev/venv"
    assert result.dev_state == "/srv/yoyopod-dev/state"
    assert result.dev_logs == "/srv/yoyopod-dev/logs"


def test_load_lane_paths_derives_subpaths_from_local_dev_root_over_base_defaults(
    tmp_path,
) -> None:
    base_yaml = tmp_path / "base.yaml"
    base_yaml.write_text(
        "lane:\n"
        "  dev_root: /opt/yoyopod-dev\n"
        "  dev_checkout: /opt/yoyopod-dev/checkout\n"
        "  dev_venv: /opt/yoyopod-dev/venv\n"
    )
    local_yaml = tmp_path / "local.yaml"
    local_yaml.write_text("lane:\n  dev_root: /srv/yoyopod-dev\n")

    result = load_lane_paths(base_path=base_yaml, local_path=local_yaml)

    assert result.dev_root == "/srv/yoyopod-dev"
    assert result.dev_checkout == "/srv/yoyopod-dev/checkout"
    assert result.dev_venv == "/srv/yoyopod-dev/venv"


def test_load_pi_paths_applies_local_override(tmp_path) -> None:
    base_yaml = tmp_path / "base.yaml"
    base_yaml.write_text(
        "log_file: logs/yoyopod.log\n"
        "error_log_file: logs/yoyopod_errors.log\n"
        "pid_file: /tmp/yoyopod.pid\n"
        "startup_marker: YoYoPod starting\n"
    )
    local_yaml = tmp_path / "local.yaml"
    local_yaml.write_text("host: rpi-zero\nproject_dir: /opt/yoyopod\n")

    result = load_pi_paths(base_path=base_yaml, local_path=local_yaml)
    assert result.project_dir == "/opt/yoyopod"  # overridden
