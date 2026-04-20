"""Music backend subpackage for YoyoPod."""

from yoyopod.audio.music.backend import MockMusicBackend, MpvBackend, MusicBackend
from yoyopod.audio.music.models import MusicConfig, PlaybackQueue, Playlist, Track
from yoyopod.audio.music.history import RecentTrackEntry, RecentTrackHistoryStore
from yoyopod.audio.music.library import LocalLibraryItem, LocalMusicService

__all__ = [
    "MockMusicBackend",
    "MpvBackend",
    "MusicBackend",
    "MusicConfig",
    "PlaybackQueue",
    "Playlist",
    "LocalLibraryItem",
    "LocalMusicService",
    "RecentTrackEntry",
    "RecentTrackHistoryStore",
    "Track",
]
