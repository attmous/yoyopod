"""Typed services exposed by the scaffold music integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlayCommand:
    """Start playback of one explicit track URI."""

    track_uri: str


@dataclass(frozen=True, slots=True)
class LoadPlaylistCommand:
    """Replace the queue with one playlist and start playback."""

    playlist_uri: str


@dataclass(frozen=True, slots=True)
class PlayRecentTrackCommand:
    """Start playback from the local recent-tracks list."""

    track_uri: str


@dataclass(frozen=True, slots=True)
class ShuffleAllCommand:
    """Shuffle the local library and start playback."""


@dataclass(frozen=True, slots=True)
class PauseCommand:
    """Pause playback without releasing focus."""


@dataclass(frozen=True, slots=True)
class ResumeCommand:
    """Resume playback, reacquiring focus if needed."""


@dataclass(frozen=True, slots=True)
class StopCommand:
    """Stop playback and release focus."""


@dataclass(frozen=True, slots=True)
class NextTrackCommand:
    """Advance to the next track."""


@dataclass(frozen=True, slots=True)
class PreviousTrackCommand:
    """Go back to the previous track."""


@dataclass(frozen=True, slots=True)
class SetVolumeCommand:
    """Set playback volume as an integer percent."""

    percent: int
