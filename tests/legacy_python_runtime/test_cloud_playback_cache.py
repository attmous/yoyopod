from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

from yoyopod.integrations.cloud.playback_cache import RemotePlaybackCache


def test_prepare_sanitizes_track_id_and_stays_within_cache_root(tmp_path: Path) -> None:
    cache = RemotePlaybackCache(tmp_path, 64 * 1024 * 1024)

    def fake_download(*, media_url: str, target_path: Path, checksum_sha256: str | None) -> Path:
        target_path.write_bytes(b"audio")
        return target_path

    cache._download = fake_download  # type: ignore[method-assign]

    asset = cache.prepare(
        track_id="../../evil/nested-track",
        media_url="https://media.example.test/file.mp3",
        checksum_sha256="abc123",
    )

    resolved_root = tmp_path.resolve()
    resolved_path = Path(asset.path).resolve()

    assert resolved_path.parent == resolved_root
    assert ".." not in resolved_path.name
    assert resolved_path.name.startswith("evil-nested-track-abc123")


def test_prune_removes_oldest_files_first(tmp_path: Path) -> None:
    cache = RemotePlaybackCache(tmp_path, 32 * 1024 * 1024)
    cache.max_bytes = 8

    oldest = tmp_path / "oldest.mp3"
    newest = tmp_path / "newest.mp3"
    oldest.write_bytes(b"12345")
    newest.write_bytes(b"67890")

    os.utime(oldest, (100, 100))
    os.utime(newest, (200, 200))

    cache._prune()

    assert not oldest.exists()
    assert newest.exists()


def test_prepare_keeps_new_download_when_it_exceeds_cache_limit(tmp_path: Path) -> None:
    cache = RemotePlaybackCache(tmp_path, 32 * 1024 * 1024)
    cache.max_bytes = 4

    def fake_download(*, media_url: str, target_path: Path, checksum_sha256: str | None) -> Path:
        target_path.write_bytes(b"12345")
        return target_path

    cache._download = fake_download  # type: ignore[method-assign]

    asset = cache.prepare(
        track_id="oversized-track",
        media_url="https://media.example.test/file.mp3",
    )

    assert Path(asset.path).exists()


def test_prune_tolerates_files_disappearing_during_concurrent_maintenance(
    tmp_path: Path, monkeypatch
) -> None:
    cache = RemotePlaybackCache(tmp_path, 32 * 1024 * 1024)
    protected = tmp_path / "protected.mp3"
    protected.write_bytes(b"1234")

    class _FakeEntry:
        def __init__(self, name: str, *, size: int, missing_on_stat: bool = False) -> None:
            self.name = name
            self._size = size
            self._missing_on_stat = missing_on_stat

        def is_file(self) -> bool:
            return True

        def stat(self):
            if self._missing_on_stat:
                raise FileNotFoundError(self.name)
            return SimpleNamespace(st_mtime=1, st_size=self._size)

        def resolve(self, strict: bool = False) -> Path:
            return tmp_path / self.name

        def unlink(self, missing_ok: bool = False) -> None:
            return None

    fake_entries = [_FakeEntry("gone.mp3", size=2, missing_on_stat=True), _FakeEntry("old.mp3", size=8)]

    original_glob = Path.glob

    def fake_glob(self: Path, pattern: str):
        if self == cache.root and pattern == "*":
            return iter(fake_entries)
        return original_glob(self, pattern)

    monkeypatch.setattr(Path, "glob", fake_glob)

    cache.max_bytes = 4
    cache._prune(protected_paths={protected})
