"""Backward-compatible shim for recent-track history imports.

The canonical implementation now lives in :mod:`yoyopod.audio.music.history`.
This module preserves historical import paths used by existing callers.
"""

from __future__ import annotations

from yoyopod.audio.music.history import RecentTrackEntry, RecentTrackHistoryStore

__all__ = ["RecentTrackEntry", "RecentTrackHistoryStore"]
