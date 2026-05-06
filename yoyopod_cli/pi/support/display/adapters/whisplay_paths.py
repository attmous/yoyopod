"""Helpers for locating the optional Whisplay driver on disk."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


def _normalize_candidate(candidate: str | Path) -> Path:
    """Normalize a candidate file or directory path into a WhisPlay.py path."""
    path = Path(candidate).expanduser()
    if path.is_dir():
        return path / "WhisPlay.py"
    return path


def get_whisplay_driver_candidates() -> list[Path]:
    """Return the ordered list of candidate Whisplay driver paths."""
    env_candidate = os.getenv("YOYOPOD_WHISPLAY_DRIVER")

    candidates = [
        _normalize_candidate(env_candidate) if env_candidate else None,
        Path.home() / "Whisplay" / "Driver" / "WhisPlay.py",
        Path("/home/tifo/Whisplay/Driver/WhisPlay.py"),
        Path("/opt/whisplay/Driver/WhisPlay.py"),
        Path.cwd() / "Whisplay" / "Driver" / "WhisPlay.py",
        Path.cwd() / "Driver" / "WhisPlay.py",
    ]

    deduped: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        if candidate is None:
            continue
        if candidate not in seen:
            deduped.append(candidate)
            seen.add(candidate)
    return deduped


def find_whisplay_driver() -> Optional[Path]:
    """Find the first Whisplay driver path that exists on disk."""
    for candidate in get_whisplay_driver_candidates():
        if candidate.exists():
            return candidate
    return None


def ensure_whisplay_driver_on_path() -> Optional[Path]:
    """Add the detected Whisplay driver directory to ``sys.path`` if available."""
    driver_path = find_whisplay_driver()
    if driver_path is None:
        return None

    driver_dir = str(driver_path.parent)
    if driver_dir not in sys.path:
        sys.path.append(driver_dir)
    return driver_path
