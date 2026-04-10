"""yoyopy/cli/common.py — shared CLI helpers."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


REPO_ROOT = Path(__file__).resolve().parents[2]


def configure_logging(verbose: bool) -> None:
    """Configure loguru for CLI commands."""
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level, format="{time:HH:mm:ss} | {level:<7} | {message}")


def resolve_config_dir(config_dir: str) -> Path:
    """Resolve config directory relative to repo root."""
    p = Path(config_dir)
    if not p.is_absolute():
        p = REPO_ROOT / p
    return p
