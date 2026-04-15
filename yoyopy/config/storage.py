"""Shared YAML storage helpers for YoyoPod config."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


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
