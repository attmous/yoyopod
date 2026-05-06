"""Canonical backend seam for local music playback adapters."""

from yoyopod_cli.pi.support.music_backend.ipc import MpvIpcClient
from yoyopod_cli.pi.support.music_backend.models import MusicConfig, PlaybackQueue, Playlist, Track
from yoyopod_cli.pi.support.music_backend.mpv import MockMusicBackend, MpvBackend, MusicBackend
from yoyopod_cli.pi.support.music_backend.process import MpvProcess
from yoyopod_cli.pi.support.music_backend.rust_host import RustHostBackend

__all__ = [
    "MockMusicBackend",
    "MpvBackend",
    "MpvIpcClient",
    "MpvProcess",
    "MusicBackend",
    "MusicConfig",
    "PlaybackQueue",
    "Playlist",
    "RustHostBackend",
    "Track",
]
