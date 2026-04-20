"""Backward-compatible shim for local music service imports.

The canonical implementation now lives in :mod:`yoyopod.audio.music.library`.
This module preserves historical import paths used by existing callers.
"""

from __future__ import annotations

from yoyopod.audio.music.library import (
    AUDIO_EXTENSIONS,
    LEGACY_LIBRARY_ROOTS,
    LEGACY_PLAYLIST_SCHEMES,
    LEGACY_TRACK_SCHEMES,
    LocalLibraryItem,
    LocalMusicService,
)

__all__ = [
    "AUDIO_EXTENSIONS",
    "LocalLibraryItem",
    "LocalMusicService",
    "LEGACY_LIBRARY_ROOTS",
    "LEGACY_PLAYLIST_SCHEMES",
    "LEGACY_TRACK_SCHEMES",
]
