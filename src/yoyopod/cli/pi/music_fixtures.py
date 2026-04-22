"""Compatibility layer for legacy `yoyopod.cli.pi.music_fixtures` imports."""

from __future__ import annotations

from yoyopod_cli.music_fixtures import (
    DEFAULT_TEST_MUSIC_TARGET_DIR,
    ProvisionedTestMusicLibrary,
    TestPlaylistSpec,
    TestToneSpec,
    TEST_MUSIC_LIBRARY_VERSION,
    TEST_MUSIC_MANIFEST_FILENAME,
    TEST_PLAYLIST_SPECS,
    TEST_TONE_SPECS,
    expected_test_music_relative_paths,
    provision_test_music_library,
)

__all__ = [
    "DEFAULT_TEST_MUSIC_TARGET_DIR",
    "ProvisionedTestMusicLibrary",
    "TestPlaylistSpec",
    "TestToneSpec",
    "TEST_MUSIC_LIBRARY_VERSION",
    "TEST_MUSIC_MANIFEST_FILENAME",
    "TEST_PLAYLIST_SPECS",
    "TEST_TONE_SPECS",
    "expected_test_music_relative_paths",
    "provision_test_music_library",
]
