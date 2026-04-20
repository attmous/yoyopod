"""Compatibility exports for relocated setup contract constants."""

from pathlib import Path

from yoyopod.core.setup_contract import (
    RUNTIME_REQUIRED_CONFIG_FILES,
    SETUP_TRACKED_CONFIG_FILES,
)

__all__ = [
    "Path",
    "RUNTIME_REQUIRED_CONFIG_FILES",
    "SETUP_TRACKED_CONFIG_FILES",
]
