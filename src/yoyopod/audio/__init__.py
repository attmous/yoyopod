"""App-facing seam for the media/audio domain."""

from yoyopod.audio.history import RecentTrackEntry, RecentTrackHistoryStore
from yoyopod.audio.local_service import LocalLibraryItem, LocalMusicService
from yoyopod.audio.manager import AudioManager, AudioDevice
from yoyopod.audio.music import (
    MusicBackend,
    MockMusicBackend,
    MpvBackend,
    MusicConfig,
    PlaybackQueue,
    Playlist,
    Track,
)
from yoyopod.audio.volume import OutputVolumeController

__all__ = [
    "AudioDevice",
    "AudioManager",
    "LocalLibraryItem",
    "LocalMusicService",
    "MockMusicBackend",
    "MpvBackend",
    "MusicBackend",
    "MusicConfig",
    "PlaybackQueue",
    "OutputVolumeController",
    "Playlist",
    "RecentTrackEntry",
    "RecentTrackHistoryStore",
    "Track",
]
