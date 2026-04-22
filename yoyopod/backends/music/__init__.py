"""Canonical backend seam for local music playback adapters."""

from yoyopod.backends.music.ipc import MpvIpcClient
from yoyopod.backends.music.models import MusicConfig, PlaybackQueue, Playlist, Track
from yoyopod.backends.music.mpv import MockMusicBackend, MpvBackend, MusicBackend
from yoyopod.backends.music.process import MpvProcess

__all__ = [
    "MockMusicBackend",
    "MpvBackend",
    "MpvIpcClient",
    "MpvProcess",
    "MusicBackend",
    "MusicConfig",
    "PlaybackQueue",
    "Playlist",
    "Track",
]
