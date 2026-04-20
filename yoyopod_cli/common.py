"""Shared CLI helpers (logging, repo root, config dir resolution)."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]


def configure_logging(verbose: bool) -> None:
    """Configure loguru for CLI commands."""
    logger.remove()
    level = "DEBUG" if verbose else "INFO"
    logger.add(sys.stderr, level=level, format="{time:HH:mm:ss} | {level:<7} | {message}")


def resolve_config_dir(config_dir: str) -> Path:
    """Resolve a config directory relative to the repo root."""
    path = Path(config_dir)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path
