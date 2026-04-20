"""App-facing seam for the media/audio domain."""

from yoyopod.audio.manager import AudioDevice, AudioManager
from yoyopod.audio.music import (
    LocalLibraryItem,
    LocalMusicService,
    MockMusicBackend,
    MpvBackend,
    MusicBackend,
    MusicConfig,
    PlaybackQueue,
    Playlist,
    RecentTrackEntry,
    RecentTrackHistoryStore,
    Track,
)
from yoyopod.audio.volume import OutputVolumeController
from yoyopod.audio.volume_controller import AudioVolumeController

__all__ = [
    "AudioDevice",
    "AudioManager",
    "AudioVolumeController",
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
