"""Helpers for composing canonical app settings from layered YAML sources."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yoyopod.config.layers import resolve_config_board, resolve_config_layers
from yoyopod.config.models import YoyoPodConfig, build_config_model
from yoyopod.config.storage import deep_merge_mappings, load_yaml_layers

APP_CORE_CONFIG = Path("app/core.yaml")
DEVICE_HARDWARE_CONFIG = Path("device/hardware.yaml")


def config_loaded(*layer_groups: tuple[Path, ...]) -> bool:
    """Return whether any layer in any group exists on disk."""

    return any(path.exists() for group in layer_groups for path in group)


def merge_layer_groups(*layer_groups: tuple[Path, ...]) -> dict[str, Any]:
    """Load and merge multiple layer groups in order."""

    merged: dict[str, Any] = {}
    for group in layer_groups:
        merged = deep_merge_mappings(merged, load_yaml_layers(group))
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
