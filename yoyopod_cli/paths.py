"""All CLI paths and process constants — single source of truth.

If a path or process name changes, edit this file and only this file.
Per-host overrides still live in deploy/pi-deploy.local.yaml.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from yoyopod_cli.common import REPO_ROOT
from yoyopod_cli.defaults import DEFAULT_TEST_MUSIC_TARGET_DIR


@dataclass(frozen=True)
class HostPaths:
    """Paths on the dev machine."""

    repo_root: Path = REPO_ROOT
    deploy_config: Path = REPO_ROOT / "deploy" / "pi-deploy.yaml"
    deploy_config_local: Path = REPO_ROOT / "deploy" / "pi-deploy.local.yaml"
    systemd_unit_template: Path = REPO_ROOT / "deploy" / "systemd" / "yoyopod@.service"


@dataclass(frozen=True)
class PiPaths:
    """Default Pi-side paths (overridable via pi-deploy.local.yaml)."""

    project_dir: str = "~/YoyoPod_Core"
    venv: str = ".venv"
    start_cmd: str = "python yoyopod.py"
    log_file: str = "logs/yoyopod.log"
    error_log_file: str = "logs/yoyopod_errors.log"
    pid_file: str = "/tmp/yoyopod.pid"
    screenshot_path: str = "/tmp/yoyopod_screenshot.png"
    test_music_target_dir: str = DEFAULT_TEST_MUSIC_TARGET_DIR
    startup_marker: str = "YoyoPod starting"
    kill_processes: tuple[str, ...] = ("python", "linphonec")
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


@dataclass(frozen=True)
class ConfigFiles:
    """YAML configs the app reads; referenced by CLI commands."""

    core: Path = REPO_ROOT / "config" / "app" / "core.yaml"
    music: Path = REPO_ROOT / "config" / "audio" / "music.yaml"
    hardware: Path = REPO_ROOT / "config" / "device" / "hardware.yaml"
    cellular: Path = REPO_ROOT / "config" / "network" / "cellular.yaml"
    voice: Path = REPO_ROOT / "config" / "voice" / "assistant.yaml"
    calling: Path = REPO_ROOT / "config" / "communication" / "calling.yaml"
    messaging: Path = REPO_ROOT / "config" / "communication" / "messaging.yaml"
    people: Path = REPO_ROOT / "config" / "people" / "directory.yaml"
    cloud_backend: Path = REPO_ROOT / "config" / "cloud" / "backend.yaml"


@dataclass(frozen=True)
class ProcessNames:
    """Process names used in kill/grep operations."""

    app: str = "python yoyopod.py"
    mpv: str = "mpv"
    linphonec: str = "linphonec"


HOST = HostPaths()
PI_DEFAULTS = PiPaths()
CONFIGS = ConfigFiles()
PROCS = ProcessNames()


def _load_yaml(path: Path) -> dict[str, object]:
    """Load one YAML mapping from disk; return {} if missing."""
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"Expected YAML mapping in {path}")
    return data


def _str_field(value: object, default: str) -> str:
    """Normalize a YAML scalar into a non-empty string, falling back to default."""
    if value is None:
        return default
    text = str(value).strip()
    return text or default


def _as_str_tuple(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    """Normalize a YAML list into a tuple of non-empty strings.

    Nested lists are coerced via str(); callers should pass flat lists.
    """
    if isinstance(value, str):
        candidates: Sequence[object] = (value,)
    elif isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        candidates = value
    else:
        return default
    normalized = tuple(str(item).strip() for item in candidates if str(item).strip())
    return normalized or default


def load_pi_paths(
    *,
    base_path: Path | None = None,
    local_path: Path | None = None,
) -> PiPaths:
    """Return PiPaths with base + local YAML overrides applied.

    Reads fresh on every call — CLI commands are short-lived processes.
    """
    base = base_path if base_path is not None else HOST.deploy_config
    local = local_path if local_path is not None else HOST.deploy_config_local

    merged: dict[str, object] = {}
    merged.update(_load_yaml(base))
    merged.update(_load_yaml(local))

    # Note: host, user, and branch keys in the YAML are connection concerns handled
    # by yoyopod_cli.remote_shared._resolve_remote_connection, not path concerns.
    # They're silently ignored here.
    return replace(
        PI_DEFAULTS,
        project_dir=_str_field(merged.get("project_dir"), PI_DEFAULTS.project_dir),
        venv=_str_field(merged.get("venv"), PI_DEFAULTS.venv),
        start_cmd=_str_field(merged.get("start_cmd"), PI_DEFAULTS.start_cmd),
        log_file=_str_field(merged.get("log_file"), PI_DEFAULTS.log_file),
        error_log_file=_str_field(merged.get("error_log_file"), PI_DEFAULTS.error_log_file),
        pid_file=_str_field(merged.get("pid_file"), PI_DEFAULTS.pid_file),
        screenshot_path=_str_field(merged.get("screenshot_path"), PI_DEFAULTS.screenshot_path),
        test_music_target_dir=_str_field(
            merged.get("test_music_target_dir"), PI_DEFAULTS.test_music_target_dir
        ),
        startup_marker=_str_field(merged.get("startup_marker"), PI_DEFAULTS.startup_marker),
        kill_processes=_as_str_tuple(merged.get("kill_processes"), PI_DEFAULTS.kill_processes),
        rsync_exclude=_as_str_tuple(merged.get("rsync_exclude"), PI_DEFAULTS.rsync_exclude),
    )
