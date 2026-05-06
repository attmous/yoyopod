"""Compatibility re-export for setup contracts.

Active CLI and deploy code should import from `yoyopod_cli.contracts.setup`.
"""

from __future__ import annotations

from yoyopod_cli.contracts.setup import (
    RUNTIME_REQUIRED_CONFIG_FILES,
    SETUP_TRACKED_CONFIG_FILES,
)

__all__ = [
    "RUNTIME_REQUIRED_CONFIG_FILES",
    "SETUP_TRACKED_CONFIG_FILES",
]
