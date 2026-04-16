"""Deploy-config models and loading helpers for remote Pi operations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import yaml

from yoyopod.audio.test_music import DEFAULT_TEST_MUSIC_TARGET_DIR
from yoyopod.cli.common import REPO_ROOT

DEPLOY_CONFIG_PATH = REPO_ROOT / "deploy" / "pi-deploy.yaml"
LOCAL_DEPLOY_CONFIG_PATH = REPO_ROOT / "deploy" / "pi-deploy.local.yaml"
DEFAULT_PI_PROJECT_DIR = "~/YoyoPod_Core"


@dataclass
class RemoteConfig:
    """Connection details for the Raspberry Pi host."""

    host: str
    user: str
    project_dir: str
    branch: str

    @property
    def ssh_target(self) -> str:
        """Return the SSH target in user@host form when a user is configured."""

        if self.user:
            return f"{self.user}@{self.host}"
        return self.host


@dataclass(frozen=True)
class PiDeployConfig:
    """Stable runtime paths used by the Pi deploy/debugging workflow."""

    host: str = ""
    user: str = ""
    project_dir: str = DEFAULT_PI_PROJECT_DIR
    branch: str = "main"
    venv: str = ".venv"
    start_cmd: str = "python yoyopod.py"
    kill_processes: tuple[str, ...] = ("python", "linphonec")
    log_file: str = "logs/yoyopod.log"
    error_log_file: str = "logs/yoyopod_errors.log"
    pid_file: str = "/tmp/yoyopod.pid"
    startup_marker: str = "YoyoPod starting"
    screenshot_path: str = "/tmp/yoyopod_screenshot.png"
    test_music_target_dir: str = DEFAULT_TEST_MUSIC_TARGET_DIR
    rsync_exclude: tuple[str, ...] = (
        ".git/",
        ".cache/",
        "__pycache__/",
        "*.pyc",
        ".venv/",
        "build/",
        "logs/",
        "models/",
        "node_modules/",
        "*.egg-info/",
    )


def load_yaml_mapping(path: Path) -> dict[str, object]:
    """Load one YAML mapping from disk."""

    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Expected a YAML mapping in {path}")
    return data


def merge_pi_deploy_layers(*layers: dict[str, object]) -> dict[str, object]:
    """Merge deploy config layers from lowest to highest precedence."""

    merged: dict[str, object] = {}
    for layer in layers:
        for key, value in layer.items():
            if value is not None:
                merged[key] = value
    return merged


def _as_string_tuple(value: object, *, default: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize one YAML sequence-like value into a tuple of non-empty strings."""

    if isinstance(value, str):
        candidates: Sequence[object] = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        candidates = value
    else:
        return default

    normalized = tuple(str(item).strip() for item in candidates if str(item).strip())
    return normalized or default


def parse_pi_deploy_config(data: dict[str, object]) -> PiDeployConfig:
    """Normalize raw YAML data into a deploy config object."""

    return PiDeployConfig(
        host=str(data.get("host", "")).strip(),
        user=str(data.get("user", "")).strip(),
        project_dir=str(
            data.get("project_dir", data.get("remote_dir", DEFAULT_PI_PROJECT_DIR))
        ).strip()
        or DEFAULT_PI_PROJECT_DIR,
        branch=str(data.get("branch", "main")).strip() or "main",
        venv=str(data.get("venv", ".venv")).strip() or ".venv",
        start_cmd=str(data.get("start_cmd", "python yoyopod.py")).strip() or "python yoyopod.py",
        kill_processes=_as_string_tuple(
            data.get("kill_processes", ("python", "linphonec")),
            default=("python", "linphonec"),
        ),
        log_file=str(data["log_file"]).strip(),
        error_log_file=str(data["error_log_file"]).strip(),
        pid_file=str(data["pid_file"]).strip(),
        startup_marker=str(data["startup_marker"]).strip(),
        screenshot_path=str(data.get("screenshot_path", "/tmp/yoyopod_screenshot.png")).strip()
        or "/tmp/yoyopod_screenshot.png",
        test_music_target_dir=str(
            data.get("test_music_target_dir", DEFAULT_TEST_MUSIC_TARGET_DIR)
        ).strip()
        or DEFAULT_TEST_MUSIC_TARGET_DIR,
        rsync_exclude=_as_string_tuple(
            data.get(
                "rsync_exclude",
                (
                    ".git/",
                    ".cache/",
                    "__pycache__/",
                    "*.pyc",
                    ".venv/",
                    "build/",
                    "logs/",
                    "models/",
                    "node_modules/",
                    "*.egg-info/",
                ),
            ),
            default=(
                ".git/",
                ".cache/",
                "__pycache__/",
                "*.pyc",
                ".venv/",
                "build/",
                "logs/",
                "models/",
                "node_modules/",
                "*.egg-info/",
            ),
        ),
    )


def load_pi_deploy_config(
    *,
    config_path: Path | None = None,
    local_override_path: Path | None = None,
) -> PiDeployConfig:
    """Load the shared deploy config with an optional local override layer."""

    base_path = config_path or DEPLOY_CONFIG_PATH
    local_path = local_override_path or LOCAL_DEPLOY_CONFIG_PATH

    merged_data = load_yaml_mapping(base_path)
    if local_path.exists():
        merged_data = merge_pi_deploy_layers(
            merged_data,
            load_yaml_mapping(local_path),
        )

    return parse_pi_deploy_config(merged_data)


def pi_deploy_config_to_dict(config: PiDeployConfig) -> dict[str, object]:
    """Convert one deploy config object back into a YAML-friendly mapping."""

    return {
        "host": config.host,
        "user": config.user,
        "project_dir": config.project_dir,
        "branch": config.branch,
        "venv": config.venv,
        "start_cmd": config.start_cmd,
        "kill_processes": list(config.kill_processes),
        "log_file": config.log_file,
        "error_log_file": config.error_log_file,
        "pid_file": config.pid_file,
        "startup_marker": config.startup_marker,
        "screenshot_path": config.screenshot_path,
        "test_music_target_dir": config.test_music_target_dir,
        "rsync_exclude": list(config.rsync_exclude),
    }


def resolve_remote_config(
    host: str,
    user: str,
    project_dir: str,
    branch: str,
) -> RemoteConfig:
    """Build a RemoteConfig from CLI option values."""

    deploy_config = load_pi_deploy_config()
    return RemoteConfig(
        host=host or os.getenv("YOYOPOD_PI_HOST", deploy_config.host),
        user=user or os.getenv("YOYOPOD_PI_USER", deploy_config.user),
        project_dir=project_dir or os.getenv("YOYOPOD_PI_PROJECT_DIR", deploy_config.project_dir),
        branch=branch or os.getenv("YOYOPOD_PI_BRANCH", deploy_config.branch),
    )
