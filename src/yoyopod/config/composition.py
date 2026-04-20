"""Helpers for composing canonical app settings from layered YAML sources."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from yoyopod.config.models import YoyoPodConfig, build_config_model

__all__ = [
    "APP_CORE_CONFIG",
    "DEVICE_HARDWARE_CONFIG",
    "atomic_write_yaml",
    "config_loaded",
    "deep_merge_mappings",
    "detect_config_board",
    "load_composed_app_settings",
    "load_yaml_layers",
    "load_yaml_mapping",
    "merge_layer_groups",
    "read_device_tree_text",
    "resolve_config_board",
    "resolve_config_layers",
]

APP_CORE_CONFIG = Path("app/core.yaml")
DEVICE_HARDWARE_CONFIG = Path("device/hardware.yaml")


def read_device_tree_text(path: Path) -> str:
    """Read one device-tree text node, tolerating missing files off-device."""

    try:
        return path.read_bytes().replace(b"\x00", b"\n").decode("utf-8", errors="ignore")
    except OSError:
        return ""


def detect_config_board() -> str | None:
    """Return the known board config that matches the current hardware."""

    model = read_device_tree_text(Path("/proc/device-tree/model")).lower()
    compatible = read_device_tree_text(Path("/proc/device-tree/compatible")).lower()

    if "cubie a7z" in model or "radxa,cubie-a7z" in compatible:
        return "radxa-cubie-a7z"
    if "raspberry pi zero 2" in model:
        return "rpi-zero-2w"

    return None


def resolve_config_board(*, explicit_board: str | None) -> str | None:
    """Resolve the active board config from args, env, or hardware detection."""

    if explicit_board:
        return explicit_board

    env_board = os.getenv("YOYOPOD_CONFIG_BOARD", "").strip()
    if env_board:
        return env_board

    return detect_config_board()


def resolve_config_layers(
    config_dir: Path,
    config_board: str | None,
    filename: str | Path,
) -> tuple[Path, ...]:
    """Return the base config file plus any matching board overlay."""

    layers = [config_dir / filename]
    if config_board:
        board_file = config_dir / "boards" / config_board / filename
        if board_file.exists():
            layers.append(board_file)
    return tuple(layers)


def config_loaded(*layer_groups: tuple[Path, ...]) -> bool:
    """Return whether any layer in any group exists on disk."""

    return any(path.exists() for group in layer_groups for path in group)


def merge_layer_groups(*layer_groups: tuple[Path, ...]) -> dict[str, Any]:
    """Load and merge multiple layer groups in order."""

    merged: dict[str, Any] = {}
    for group in layer_groups:
        merged = deep_merge_mappings(merged, load_yaml_layers(group))
    return merged


def deep_merge_mappings(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge one config mapping into another."""

    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(merged.get(key), dict) and isinstance(value, dict):
            merged[key] = deep_merge_mappings(merged[key], value)
        else:
            merged[key] = value
    return merged


def atomic_write_yaml(path: Path, data: dict[str, Any]) -> None:
    """Write YAML atomically so power loss never corrupts the config file."""

    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)

    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(directory))
    tmp = Path(tmp_path)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            yaml.dump(data, handle, default_flow_style=False, sort_keys=False)
        os.replace(str(tmp), str(path))
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass


def load_yaml_mapping(path: Path) -> dict[str, Any]:
    """Load one YAML mapping from disk, tolerating missing files."""

    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    return loaded if isinstance(loaded, dict) else {}


def load_yaml_layers(paths: tuple[Path, ...]) -> dict[str, Any]:
    """Load and merge YAML mappings from lowest to highest precedence."""

    merged: dict[str, Any] = {}
    for path in paths:
        if not path.exists():
            continue
        merged = deep_merge_mappings(merged, load_yaml_mapping(path))
    return merged


def load_composed_app_settings(
    config_dir: str | Path = "config",
    *,
    config_board: str | None = None,
) -> YoyoPodConfig:
    """Load the typed app settings from the canonical app/device topology."""

    base_dir = Path(config_dir)
    active_board = resolve_config_board(explicit_board=config_board)
    payload = merge_layer_groups(
        resolve_config_layers(base_dir, active_board, APP_CORE_CONFIG),
        resolve_config_layers(base_dir, active_board, DEVICE_HARDWARE_CONFIG),
    )
    return build_config_model(YoyoPodConfig, payload)
