"""Tests for deterministic playback-validation music provisioning."""

from __future__ import annotations

from pathlib import Path

from yoyopod_cli.music_fixtures import (
    TEST_MUSIC_MANIFEST_FILENAME,
    TEST_TONE_SPECS,
    expected_test_music_relative_paths,
    provision_test_music_library,
)


def test_provision_test_music_library_writes_expected_assets(tmp_path: Path) -> None:
    """Provisioning should create the full known-good validation library."""

    library = provision_test_music_library(tmp_path / "YoyoPod_Test_Music")

    expected_relative = set(expected_test_music_relative_paths())
    actual_relative = {
        path.relative_to(library.target_dir).as_posix()
        for path in (*library.track_paths, *library.playlist_paths)
    }

    assert actual_relative == expected_relative
    assert library.manifest_path.name == TEST_MUSIC_MANIFEST_FILENAME
    assert library.manifest_path.exists()

    playlist_text = library.default_playlist_path.read_text(encoding="utf-8")
    assert "#EXTM3U" in playlist_text
    assert "tracks/alpha-beacon.wav" in playlist_text
    assert "tracks/bravo-lantern.wav" in playlist_text


def test_provision_test_music_library_replaces_managed_assets_only(tmp_path: Path) -> None:
    """Reprovisioning should refresh managed files without deleting unrelated ones."""

    library = provision_test_music_library(tmp_path / "YoyoPod_Test_Music")
    extra_file = library.target_dir / "keep-me.txt"
    extra_file.write_text("user-media-stays\n", encoding="utf-8")

    first_track = library.track_paths[0]
    first_track.write_bytes(b"bad")

    reprovisioned = provision_test_music_library(library.target_dir)

    assert extra_file.exists()
    assert first_track.stat().st_size > 3
    assert reprovisioned.default_playlist_path.exists()


def test_validation_music_library_is_long_enough_for_navigation_soak() -> None:
    """Validation tracks should outlast the default Now Playing idle dwell on hardware."""

    total_duration = sum(spec.duration_seconds for spec in TEST_TONE_SPECS)

    assert total_duration > 6.0
