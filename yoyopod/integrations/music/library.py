"""Local music facade backed by `MusicBackend` and filesystem scanning."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from yoyopod.backends.music import MusicBackend, Playlist, Track
from yoyopod.integrations.music.history import RecentTrackEntry, RecentTrackHistoryStore

AUDIO_EXTENSIONS = (".mp3", ".flac", ".ogg", ".wav", ".m4a", ".opus")


@dataclass(frozen=True, slots=True)
class LocalLibraryItem:
    """One entry in the local Listen landing menu."""

    key: str
    title: str
    subtitle: str


class LocalMusicService:
    """App-facing local music operations backed by `MusicBackend` and filesystem."""

    def __init__(
        self,
        music_backend: MusicBackend | None,
        music_dir: Path = Path("/home/pi/Music"),
        recent_store: RecentTrackHistoryStore | None = None,
    ) -> None:
        self.music_backend = music_backend
        self.music_dir = music_dir
        self.recent_store = recent_store

    @property
    def is_available(self) -> bool:
        """Return True when the music backend is connected."""
        return bool(self.music_backend and self.music_backend.is_connected)

    def is_local_track_uri(self, uri: str) -> bool:
        """Return True when the URI is a path under the music directory."""
        try:
            return Path(uri).is_relative_to(self.music_dir)
        except (ValueError, TypeError):
            return False

    def is_local_playlist_uri(self, uri: str) -> bool:
        """Return True when the URI is an M3U file under the music directory."""
        try:
            path = Path(uri)
            return path.suffix.lower() == ".m3u" and path.is_relative_to(self.music_dir)
        except (ValueError, TypeError):
            return False

    def menu_items(self) -> list[LocalLibraryItem]:
        """Return the static local-first Listen landing menu."""
        if self._backend_owns_library_state():
            menu_items = getattr(self.music_backend, "menu_items", None)
            if callable(menu_items):
                return list(menu_items())
        return [
            LocalLibraryItem("playlists", "Playlists", "Saved mixes"),
            LocalLibraryItem("recent", "Recent", "Played lately"),
            LocalLibraryItem("shuffle", "Shuffle", "Start something fun"),
        ]

    def list_playlists(self, fetch_track_counts: bool = False) -> list[Playlist]:
        """Scan music_dir for M3U files."""
        if self._backend_owns_library_state():
            list_playlists = getattr(self.music_backend, "list_playlists", None)
            if callable(list_playlists):
                return list(list_playlists(fetch_track_counts=fetch_track_counts))

        if self.music_dir.is_dir():
            playlists: list[Playlist] = []
            for path in sorted(self.music_dir.glob("**/*.m3u")):
                track_count = self._count_playlist_tracks(path) if fetch_track_counts else 0
                playlists.append(Playlist(uri=str(path), name=path.stem, track_count=track_count))
            return playlists
        return []

    def playlist_count(self) -> int:
        """Return the number of local playlists."""
        if self._backend_owns_library_state():
            playlist_count = getattr(self.music_backend, "playlist_count", None)
            if callable(playlist_count):
                return int(playlist_count())
        return len(self.list_playlists())

    def load_playlist(self, playlist_uri: str) -> bool:
        """Load and play one local playlist."""
        if self.music_backend is None:
            return False
        if self._backend_owns_library_state():
            load_playlist_file = getattr(self.music_backend, "load_playlist_file", None)
            if callable(load_playlist_file):
                return bool(load_playlist_file(playlist_uri))
        if not self.is_local_playlist_uri(playlist_uri):
            return False

        load_playlist_file = getattr(self.music_backend, "load_playlist_file", None)
        return bool(load_playlist_file and load_playlist_file(playlist_uri))

    def list_recent_tracks(self, limit: int | None = None) -> list[RecentTrackEntry]:
        """Return the current persistent local recent-track list."""
        if self._backend_owns_library_state():
            list_recent_tracks = getattr(self.music_backend, "list_recent_tracks", None)
            if callable(list_recent_tracks):
                return list(list_recent_tracks(limit))
        if self.recent_store is None:
            return []
        return self.recent_store.list_recent(limit)

    def play_recent_track(self, track_uri: str) -> bool:
        """Replace the tracklist with one local track and start playback."""
        if self.music_backend is None:
            return False
        if self._backend_owns_library_state():
            play_recent_track = getattr(self.music_backend, "play_recent_track", None)
            if callable(play_recent_track):
                return bool(play_recent_track(track_uri))
        if not self.is_local_track_uri(track_uri):
            return False

        load_tracks = getattr(self.music_backend, "load_tracks", None)
        return bool(load_tracks and load_tracks([track_uri]))

    def record_recent_track(self, track: Track | None) -> None:
        """Persist one local track play event when it belongs to the local library."""
        if self._backend_owns_library_state():
            return
        if track is None or not self.is_local_track_uri(track.uri) or self.recent_store is None:
            return
        self.recent_store.record_track(track)

    def shuffle_all(self) -> bool:
        """Build a shuffled queue from the local file library and start playback."""
        if self.music_backend is None:
            return False
        if self._backend_owns_library_state():
            shuffle_all = getattr(self.music_backend, "shuffle_all", None)
            if callable(shuffle_all):
                return bool(shuffle_all())

        track_uris = self._collect_local_track_uris()
        if not track_uris:
            logger.warning("Shuffle requested, but no local tracks were found")
            return False

        random.shuffle(track_uris)

        load_tracks = getattr(self.music_backend, "load_tracks", None)
        return bool(load_tracks and load_tracks(track_uris))

    def _collect_local_track_uris(self) -> list[str]:
        """Scan the music directory for audio files."""
        tracks: list[str] = []

        if self.music_dir.is_dir():
            tracks_by_extension: dict[str, list[str]] = {ext: [] for ext in AUDIO_EXTENSIONS}

            # Keep the previous extension bucket ordering without paying for one
            # recursive filesystem glob per extension.
            for root, dirnames, filenames in os.walk(self.music_dir):
                dirnames.sort()
                for filename in sorted(filenames):
                    ext = Path(filename).suffix.lower()
                    if ext not in tracks_by_extension:
                        continue
                    tracks_by_extension[ext].append(str(Path(root) / filename))

            for ext in AUDIO_EXTENSIONS:
                tracks.extend(tracks_by_extension[ext])

        return tracks

    def _count_playlist_tracks(self, path: Path) -> int:
        """Return the number of playable entries declared in one M3U file."""
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return 0
        return sum(1 for line in lines if line.strip() and not line.startswith("#"))

    def _backend_owns_library_state(self) -> bool:
        return bool(getattr(self.music_backend, "owns_library_state", False))


__all__ = [
    "AUDIO_EXTENSIONS",
    "LocalLibraryItem",
    "LocalMusicService",
]
