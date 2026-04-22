"""OTA-ready release manifest: dataclass + JSON load/dump.

The manifest describes a single release slot. It is emitted by the build
script, consumed by the deploy CLI, and read by the running app to report
its own version. The schema is stable (versioned) and has signature +
diff-artifact fields reserved for a future OTA daemon.
"""

from __future__ import annotations

import json
import typing
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Literal

SCHEMA_VERSION = 1

Channel = Literal["dev", "beta", "stable"]
_VALID_CHANNELS: tuple[str, ...] = typing.get_args(Channel)

ArtifactType = Literal["full", "diff"]
_VALID_ARTIFACT_TYPES: tuple[str, ...] = typing.get_args(ArtifactType)


@dataclass(frozen=True)
class Artifact:
    """A downloadable artifact for a release.

    `type="full"` is a complete release tarball. `type="diff"` is a
    zstd-patch-from-base delta; requires `base_version` to be set.
    `url` is optional: during a local-deploy push the artifact is rsync'd
    directly and never hits an HTTP URL.
    """

    type: ArtifactType
    sha256: str
    size: int
    url: str | None = None
    base_version: str | None = None

    def __post_init__(self) -> None:
        if self.type not in _VALID_ARTIFACT_TYPES:
            raise ValueError(f"Artifact.type must be one of {_VALID_ARTIFACT_TYPES}")
        if self.type == "diff" and self.base_version is None:
            raise ValueError("Artifact.base_version is required when type='diff'")
        if len(self.sha256) != 64:
            raise ValueError("Artifact.sha256 must be a 64-char hex digest")
        if not all(c in "0123456789abcdef" for c in self.sha256.lower()):
            raise ValueError("Artifact.sha256 must be lowercase hex")


@dataclass(frozen=True)
class Requirements:
    """Preflight constraints the target must satisfy before applying."""

    min_os_version: str = "0.0.0"
    min_battery_pct: int = 0
    min_free_mb: int = 0

    def __post_init__(self) -> None:
        if self.min_battery_pct < 0:
            raise ValueError("min_battery_pct must be >= 0")
        if self.min_free_mb < 0:
            raise ValueError("min_free_mb must be >= 0")


@dataclass(frozen=True)
class ReleaseManifest:
    """Top-level manifest for one release slot.

    `signature` is a reserved field; filled by the build-and-sign pipeline
    once OTA signing is enabled. Current local-deploy flow leaves it None.
    """

    version: str
    channel: Channel
    released_at: str  # ISO8601 UTC
    artifacts: dict[str, Artifact]
    requires: Requirements = field(default_factory=Requirements)
    signature: str | None = None

    def __post_init__(self) -> None:
        if self.channel not in _VALID_CHANNELS:
            raise ValueError(f"channel must be one of {_VALID_CHANNELS}")
        if not self.version:
            raise ValueError("version must be non-empty")
        if "full" not in self.artifacts:
            raise ValueError("artifacts must include a 'full' entry")


def dump_manifest(manifest: ReleaseManifest, path: Path) -> None:
    """Write `manifest` as JSON with schema header."""
    payload = {"schema": SCHEMA_VERSION, **asdict(manifest)}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def load_manifest(path: Path) -> ReleaseManifest:
    """Parse a manifest JSON file. Raises ValueError on schema mismatch or bad shape."""
    raw = json.loads(path.read_text())
    schema = raw.get("schema")
    if schema != SCHEMA_VERSION:
        raise ValueError(f"Unsupported manifest schema: {schema!r} (expected {SCHEMA_VERSION})")
    try:
        artifacts = {name: Artifact(**entry) for name, entry in raw["artifacts"].items()}
        requires = Requirements(**raw.get("requires", {}))
        return ReleaseManifest(
            version=raw["version"],
            channel=raw["channel"],
            released_at=raw["released_at"],
            artifacts=artifacts,
            requires=requires,
            signature=raw.get("signature"),
        )
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f"Invalid manifest structure: {exc}") from exc
