"""
Audio management for YoyoPod.

Provides audio playback, volume control, and device management.
"""

from yoyopy.audio.history import RecentTrackEntry, RecentTrackHistoryStore
from yoyopy.audio.local_service import LocalLibraryItem, LocalMusicService
from yoyopy.audio.manager import AudioManager, AudioDevice
from yoyopy.audio.music import MusicBackend, MockMusicBackend, MpvBackend, Track, Playlist, MusicConfig
from yoyopy.audio.volume import OutputVolumeController

__all__ = [
    'AudioDevice',
    'AudioManager',
    'LocalLibraryItem',
    'LocalMusicService',
    'MockMusicBackend',
    'MpvBackend',
    'MusicBackend',
    'MusicConfig',
    'OutputVolumeController',
    'Playlist',
    'RecentTrackEntry',
    'RecentTrackHistoryStore',
    'Track',
]
