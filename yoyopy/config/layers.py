"""Board-aware config-layer resolution helpers."""

from __future__ import annotations

import os
from pathlib import Path


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
    filename: str,
) -> tuple[Path, ...]:
    """Return the base config file plus any matching board overlay."""

    layers = [config_dir / filename]
    if config_board:
        board_file = config_dir / "boards" / config_board / filename
        if board_file.exists():
            layers.append(board_file)
    return tuple(layers)
