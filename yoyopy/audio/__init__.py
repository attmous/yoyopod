"""
Audio management for YoyoPod.

Provides audio playback, volume control, and device management.
"""

from yoyopy.audio.history import RecentTrackEntry, RecentTrackHistoryStore
from yoyopy.audio.local_service import LocalLibraryItem, LocalMusicService
from yoyopy.audio.manager import AudioManager, AudioDevice
from yoyopy.audio.mopidy_client import MopidyClient, MopidyTrack, MopidyPlaylist

__all__ = [
    'AudioManager',
    'AudioDevice',
    'LocalLibraryItem',
    'LocalMusicService',
    'RecentTrackEntry',
    'RecentTrackHistoryStore',
    'MopidyClient',
    'MopidyTrack',
    'MopidyPlaylist',
]
