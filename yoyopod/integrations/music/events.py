"""Typed events owned by the canonical music integration."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.backends.music import Track


@dataclass(frozen=True, slots=True)
class TrackChangedEvent:
    """Published when the current track changes."""

    track: Track | None


@dataclass(frozen=True, slots=True)
class PlaybackStateChangedEvent:
    """Published when playback changes state."""

    state: str


@dataclass(frozen=True, slots=True)
class MusicAvailabilityChangedEvent:
    """Published when music-backend connectivity changes."""

    available: bool
    reason: str = ""


__all__ = [
    "MusicAvailabilityChangedEvent",
    "PlaybackStateChangedEvent",
    "TrackChangedEvent",
]
