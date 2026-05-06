from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from yoyopod_cli.contracts.release import (
    ReleaseInfo,
    current_release,
    state_dir,
)


def test_current_release_returns_none_when_manifest_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YOYOPOD_RELEASE_MANIFEST", str(tmp_path / "missing.json"))
    assert current_release() is None


def test_current_release_returns_none_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("YOYOPOD_RELEASE_MANIFEST", raising=False)
    assert current_release() is None


def test_current_release_reads_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "version": "2026.04.22-abc123",
                "channel": "dev",
                "released_at": "2026-04-22T10:00:00Z",
                "artifacts": {
                    "full": {"type": "full", "sha256": "a" * 64, "size": 10}
                },
                "requires": {
                    "min_os_version": "0.0.0",
                    "min_battery_pct": 0,
                    "min_free_mb": 0,
                },
            }
        )
    )
    monkeypatch.setenv("YOYOPOD_RELEASE_MANIFEST", str(manifest_path))
    info = current_release()
    assert info is not None
    assert info.version == "2026.04.22-abc123"
    assert info.channel == "dev"
    assert info.released_at == "2026-04-22T10:00:00Z"


def test_current_release_returns_none_on_corrupt_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("{not valid json")
    monkeypatch.setenv("YOYOPOD_RELEASE_MANIFEST", str(manifest_path))
    assert current_release() is None


def test_current_release_returns_none_on_non_dict_json_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text("[1, 2, 3]")  # valid JSON, wrong shape
    monkeypatch.setenv("YOYOPOD_RELEASE_MANIFEST", str(manifest_path))
    assert current_release() is None


def test_current_release_returns_none_on_non_string_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "version": 123,  # int, not str
                "channel": "dev",
                "released_at": "2026-04-22T10:00:00Z",
                "artifacts": {"full": {"type": "full", "sha256": "a" * 64, "size": 10}},
                "requires": {"min_os_version": "0.0.0", "min_battery_pct": 0, "min_free_mb": 0},
            }
        )
    )
    monkeypatch.setenv("YOYOPOD_RELEASE_MANIFEST", str(manifest_path))
    assert current_release() is None


def test_state_dir_honours_env_var(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "state"
    target.mkdir()
    monkeypatch.setenv("YOYOPOD_STATE_DIR", str(target))
    assert state_dir() == target


def test_state_dir_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("YOYOPOD_STATE_DIR", raising=False)
    assert state_dir() == Path.home() / ".local" / "share" / "yoyopod"
