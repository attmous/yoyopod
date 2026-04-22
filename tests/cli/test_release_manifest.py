from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoyopod_cli.release_manifest import (
    Artifact,
    ReleaseManifest,
    Requirements,
    dump_manifest,
    load_manifest,
)


def test_roundtrip_minimal_manifest(tmp_path: Path) -> None:
    manifest = ReleaseManifest(
        version="2026.04.22-abc123",
        channel="dev",
        released_at="2026-04-22T10:00:00Z",
        artifacts={
            "full": Artifact(
                type="full",
                sha256="a" * 64,
                size=1024,
            ),
        },
        requires=Requirements(),
    )
    path = tmp_path / "manifest.json"
    dump_manifest(manifest, path)
    loaded = load_manifest(path)
    assert loaded == manifest


def test_schema_version_is_present_on_disk(tmp_path: Path) -> None:
    manifest = ReleaseManifest(
        version="2026.04.22-abc123",
        channel="dev",
        released_at="2026-04-22T10:00:00Z",
        artifacts={"full": Artifact(type="full", sha256="a" * 64, size=1024)},
        requires=Requirements(),
    )
    path = tmp_path / "manifest.json"
    dump_manifest(manifest, path)
    payload = json.loads(path.read_text())
    assert payload["schema"] == 1


def test_load_rejects_unknown_schema_version(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"schema": 99, "version": "x", "channel": "dev"}))
    with pytest.raises(ValueError, match="schema"):
        load_manifest(path)


def test_load_rejects_missing_required_fields(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "version": "x",
                "channel": "dev",
                "artifacts": {"full": {"type": "full", "sha256": "a" * 64, "size": 1}},
            }
        )
    )
    with pytest.raises(ValueError, match="released_at"):
        load_manifest(path)


def test_artifact_with_diff_requires_base_version() -> None:
    with pytest.raises(ValueError, match="base_version"):
        Artifact(type="diff", sha256="a" * 64, size=10, base_version=None)


def test_channel_must_be_known() -> None:
    with pytest.raises(ValueError, match="channel"):
        ReleaseManifest(
            version="x",
            channel="weird",  # type: ignore[arg-type]
            released_at="2026-04-22T10:00:00Z",
            artifacts={"full": Artifact(type="full", sha256="a" * 64, size=10)},
            requires=Requirements(),
        )


def test_signature_field_is_reserved_and_optional() -> None:
    manifest = ReleaseManifest(
        version="x",
        channel="dev",
        released_at="2026-04-22T10:00:00Z",
        artifacts={"full": Artifact(type="full", sha256="a" * 64, size=10)},
        requires=Requirements(),
    )
    assert manifest.signature is None


def test_load_rejects_non_dict_artifacts(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "version": "x",
                "channel": "dev",
                "released_at": "2026-04-22T10:00:00Z",
                "artifacts": "not a dict",
                "requires": {},
            }
        )
    )
    with pytest.raises(ValueError):
        load_manifest(path)


def test_artifact_sha256_must_be_hex() -> None:
    with pytest.raises(ValueError, match="hex"):
        Artifact(type="full", sha256="z" * 64, size=10)


def test_requirements_rejects_negative_battery_pct() -> None:
    with pytest.raises(ValueError, match="min_battery_pct"):
        Requirements(min_battery_pct=-1)


def test_requirements_rejects_negative_free_mb() -> None:
    with pytest.raises(ValueError, match="min_free_mb"):
        Requirements(min_free_mb=-1)
