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


@dataclass(frozen=True)
class PiPaths:
    """Default Pi-side paths (overridable via pi-deploy.local.yaml)."""

    project_dir: str = "/opt/yoyopod-dev/checkout"
    venv: str = "/opt/yoyopod-dev/venv"
    start_cmd: str = "device/runtime/build/yoyopod-runtime --config-dir config"
    log_file: str = "logs/yoyopod.log"
    error_log_file: str = "logs/yoyopod_errors.log"
    pid_file: str = "/tmp/yoyopod.pid"
    screenshot_path: str = "/tmp/yoyopod_screenshot.png"
    test_music_target_dir: str = DEFAULT_TEST_MUSIC_TARGET_DIR
    startup_marker: str = "YoYoPod Rust runtime starting"
    kill_processes: tuple[str, ...] = ("yoyopod-runtime",)
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
class LanePaths:
    """Dev/prod lane roots and systemd unit names on the Pi."""

    dev_root: str = "/opt/yoyopod-dev"
    dev_checkout: str = "/opt/yoyopod-dev/checkout"
    dev_venv: str = "/opt/yoyopod-dev/venv"
    dev_state: str = "/opt/yoyopod-dev/state"
    dev_logs: str = "/opt/yoyopod-dev/logs"
    prod_root: str = "/opt/yoyopod-prod"
    prod_service: str = "yoyopod-prod.service"
    prod_rollback_service: str = "yoyopod-prod-rollback.service"
    prod_ota_service: str = "yoyopod-prod-ota.service"
    prod_ota_timer: str = "yoyopod-prod-ota.timer"
    dev_service: str = "yoyopod-dev.service"
    legacy_slot_service: str = "yoyopod-slot.service"


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

    app: str = "device/runtime/build/yoyopod-runtime --config-dir config"
    mpv: str = "mpv"


HOST = HostPaths()
LANES = LanePaths()
PI_DEFAULTS = PiPaths()
CONFIGS = ConfigFiles()
PROCS = ProcessNames()


@dataclass(frozen=True)
class SlotPaths:
    """Slot-deploy paths on the Pi (overridable via pi-deploy.local.yaml)."""

    root: str = "/opt/yoyopod-prod"
    releases_subdir: str = "releases"
    state_subdir: str = "state"
    bin_subdir: str = "bin"
    current_link: str = "current"
    previous_link: str = "previous"

    def releases_dir(self) -> str:
        return f"{self.root}/{self.releases_subdir}"

    def state_dir(self) -> str:
        return f"{self.root}/{self.state_subdir}"

    def bin_dir(self) -> str:
        return f"{self.root}/{self.bin_subdir}"

    def current_path(self) -> str:
        return f"{self.root}/{self.current_link}"

    def previous_path(self) -> str:
        return f"{self.root}/{self.previous_link}"


SLOT_DEFAULTS = SlotPaths()


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


def _optional_str_field(value: object) -> str | None:
    """Normalize a YAML scalar into a non-empty string, or None when unset."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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


def _lane_section_has_path_key(data: dict[str, object], keys: tuple[str, ...]) -> bool:
    """Return whether a YAML mapping explicitly configures one of the lane keys."""
    lane_section = data.get("lane", {})
    if not isinstance(lane_section, dict):
        return False
    return any(_optional_str_field(lane_section.get(key)) is not None for key in keys)


def _dev_lane_path_field(
    *,
    field: str,
    base_data: dict[str, object],
    local_data: dict[str, object],
    lane_value: str,
    default: str,
    lane_keys: tuple[str, ...],
) -> str:
    """Resolve legacy top-level dev path fields against canonical lane config."""
    local_override = _optional_str_field(local_data.get(field))
    if local_override is not None:
        return local_override
    if _lane_section_has_path_key(base_data, lane_keys) or _lane_section_has_path_key(
        local_data, lane_keys
    ):
        return lane_value
    return _str_field(base_data.get(field), default)


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

    base_data = _load_yaml(base)
    local_data = _load_yaml(local)
    merged: dict[str, object] = {}
    merged.update(base_data)
    merged.update(local_data)
    lanes = load_lane_paths(base_path=base, local_path=local)

    # Note: host, user, and branch keys in the YAML are connection concerns handled
    # by yoyopod_cli.remote_shared._resolve_remote_connection, not path concerns.
    # They're silently ignored here.
    return replace(
        PI_DEFAULTS,
        project_dir=_dev_lane_path_field(
            field="project_dir",
            base_data=base_data,
            local_data=local_data,
            lane_value=lanes.dev_checkout,
            default=PI_DEFAULTS.project_dir,
            lane_keys=("dev_root", "dev_checkout"),
        ),
        venv=_dev_lane_path_field(
            field="venv",
            base_data=base_data,
            local_data=local_data,
            lane_value=lanes.dev_venv,
            default=PI_DEFAULTS.venv,
            lane_keys=("dev_root", "dev_venv"),
        ),
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


def load_lane_paths(
    *,
    base_path: Path | None = None,
    local_path: Path | None = None,
) -> LanePaths:
    """Return LanePaths with base + local YAML overrides applied to `lane:`."""
    base = base_path if base_path is not None else HOST.deploy_config
    local = local_path if local_path is not None else HOST.deploy_config_local

    base_section = _load_yaml(base).get("lane", {})
    local_section = _load_yaml(local).get("lane", {})
    base_lane: dict[str, object] = base_section if isinstance(base_section, dict) else {}
    local_lane: dict[str, object] = local_section if isinstance(local_section, dict) else {}

    def lane_field(key: str, default: str) -> str:
        return (
            _optional_str_field(local_lane.get(key))
            or _optional_str_field(base_lane.get(key))
            or default
        )

    dev_root = lane_field("dev_root", LANES.dev_root).rstrip("/")
    prod_root = lane_field("prod_root", LANES.prod_root).rstrip("/")
    local_dev_root = _optional_str_field(local_lane.get("dev_root")) is not None

    def dev_subpath(key: str, suffix: str) -> str:
        local_value = _optional_str_field(local_lane.get(key))
        if local_value is not None:
            return local_value
        if local_dev_root:
            return f"{dev_root}/{suffix}"
        return _optional_str_field(base_lane.get(key)) or f"{dev_root}/{suffix}"

    return replace(
        LANES,
        dev_root=dev_root,
        dev_checkout=dev_subpath("dev_checkout", "checkout"),
        dev_venv=dev_subpath("dev_venv", "venv"),
        dev_state=dev_subpath("dev_state", "state"),
        dev_logs=dev_subpath("dev_logs", "logs"),
        prod_root=prod_root,
        prod_service=lane_field("prod_service", LANES.prod_service),
        prod_rollback_service=lane_field("prod_rollback_service", LANES.prod_rollback_service),
        prod_ota_service=lane_field("prod_ota_service", LANES.prod_ota_service),
        prod_ota_timer=lane_field("prod_ota_timer", LANES.prod_ota_timer),
        dev_service=lane_field("dev_service", LANES.dev_service),
        legacy_slot_service=lane_field("legacy_slot_service", LANES.legacy_slot_service),
    )


def load_slot_paths(
    *,
    base_path: Path | None = None,
    local_path: Path | None = None,
) -> SlotPaths:
    """Return SlotPaths with base + local YAML overrides applied to the `slot:` section."""
    base = base_path if base_path is not None else HOST.deploy_config
    local = local_path if local_path is not None else HOST.deploy_config_local

    merged: dict[str, object] = {}
    for yaml_path in (base, local):
        data = _load_yaml(yaml_path)
        slot_section = data.get("slot", {})
        if isinstance(slot_section, dict):
            merged.update(slot_section)
    lanes = load_lane_paths(base_path=base, local_path=local)

    return replace(
        SLOT_DEFAULTS,
        root=_str_field(merged.get("root"), lanes.prod_root),
        releases_subdir=_str_field(merged.get("releases_subdir"), SLOT_DEFAULTS.releases_subdir),
        state_subdir=_str_field(merged.get("state_subdir"), SLOT_DEFAULTS.state_subdir),
        bin_subdir=_str_field(merged.get("bin_subdir"), SLOT_DEFAULTS.bin_subdir),
        current_link=_str_field(merged.get("current_link"), SLOT_DEFAULTS.current_link),
        previous_link=_str_field(merged.get("previous_link"), SLOT_DEFAULTS.previous_link),
    )
