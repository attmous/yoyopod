"""Release metadata helpers used by CLI health checks."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ReleaseInfo:
    """A subset of the manifest the running service cares about."""

    version: str
    channel: str
    released_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.version, str):
            raise ValueError(f"version must be str, got {type(self.version).__name__}")
        if not isinstance(self.channel, str):
            raise ValueError(f"channel must be str, got {type(self.channel).__name__}")
        if not isinstance(self.released_at, str):
            raise ValueError(f"released_at must be str, got {type(self.released_at).__name__}")


_DEFAULT_MANIFEST_PATH = "/opt/yoyopod/current/manifest.json"


def _manifest_path() -> Path:
    return Path(os.environ.get("YOYOPOD_RELEASE_MANIFEST", _DEFAULT_MANIFEST_PATH))


def current_release() -> ReleaseInfo | None:
    """Return the currently-running release, or None if not in a slot deploy."""

    path = _manifest_path()
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text())
        if not isinstance(raw, dict):
            return None
        return ReleaseInfo(
            version=raw["version"],
            channel=raw["channel"],
            released_at=raw["released_at"],
        )
    except (OSError, ValueError, KeyError):
        return None


def state_dir() -> Path:
    """Return the persistent state directory for CLI/deploy consumers."""

    override = os.environ.get("YOYOPOD_STATE_DIR")
    if override:
        return Path(override)
    return Path.home() / ".local" / "share" / "yoyopod"
