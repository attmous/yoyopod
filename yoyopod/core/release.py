"""Compatibility re-export for release metadata helpers.

Active CLI code should import from `yoyopod_cli.contracts.release`.
"""

from __future__ import annotations

from yoyopod_cli.contracts.release import ReleaseInfo, current_release, state_dir

__all__ = [
    "ReleaseInfo",
    "current_release",
    "state_dir",
]
