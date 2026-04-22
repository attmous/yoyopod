"""Local music facade backed by `MusicBackend` and filesystem scanning."""

from __future__ import annotations

import os
import random
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from yoyopod.backends.music import MusicBackend, Playlist, Track
from yoyopod.integrations.music.history import RecentTrackEntry, RecentTrackHistoryStore

AUDIO_EXTENSIONS = (".mp3", ".flac", ".ogg", ".wav", ".m4a", ".opus")
LEGACY_PLAYLIST_SCHEMES = ("m3u:",)
LEGACY_TRACK_SCHEMES = ("local:", "file:")
LEGACY_LIBRARY_ROOTS = ("file:", "local:directory")


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
        if uri.startswith(LEGACY_TRACK_SCHEMES):
            return True
        try:
            return Path(uri).is_relative_to(self.music_dir)
        except (ValueError, TypeError):
            return False

    def is_local_playlist_uri(self, uri: str) -> bool:
        """Return True when the URI is an M3U file under the music directory."""
        if uri.startswith(LEGACY_PLAYLIST_SCHEMES):
            return True
        try:
            path = Path(uri)
            return path.suffix.lower() == ".m3u" and path.is_relative_to(self.music_dir)
        except (ValueError, TypeError):
            return False

    def menu_items(self) -> list[LocalLibraryItem]:
        """Return the static local-first Listen landing menu."""
        return [
            LocalLibraryItem("playlists", "Playlists", "Saved mixes"),
            LocalLibraryItem("recent", "Recent", "Played lately"),
            LocalLibraryItem("shuffle", "Shuffle", "Start something fun"),
        ]

    def list_playlists(self, fetch_track_counts: bool = False) -> list[Playlist]:
        """Scan music_dir for M3U files."""
        if self.music_dir.is_dir():
            playlists: list[Playlist] = []
            for path in sorted(self.music_dir.glob("**/*.m3u")):
                track_count = self._count_playlist_tracks(path) if fetch_track_counts else 0
                playlists.append(Playlist(uri=str(path), name=path.stem, track_count=track_count))
            return playlists

        legacy_get_playlists = getattr(self.music_backend, "get_playlists", None)
        if legacy_get_playlists is None:
            return []

        playlists = legacy_get_playlists(fetch_track_counts=fetch_track_counts)
        return [
            Playlist(
                uri=str(playlist.uri),
                name=str(playlist.name),
                track_count=int(getattr(playlist, "track_count", 0)),
            )
            for playlist in playlists
            if self.is_local_playlist_uri(str(playlist.uri))
        ]

    def playlist_count(self) -> int:
        """Return the number of local playlists."""
        return len(self.list_playlists())

    def load_playlist(self, playlist_uri: str) -> bool:
        """Load and play one local playlist."""
        if self.music_backend is None or not self.is_local_playlist_uri(playlist_uri):
            return False

        load_playlist_file = getattr(self.music_backend, "load_playlist_file", None)
        if load_playlist_file is not None and not playlist_uri.startswith(LEGACY_PLAYLIST_SCHEMES):
            return load_playlist_file(playlist_uri)

        legacy_load_playlist = getattr(self.music_backend, "load_playlist", None)
        if legacy_load_playlist is not None:
            return legacy_load_playlist(playlist_uri)

        return False

    def list_recent_tracks(self, limit: int | None = None) -> list[RecentTrackEntry]:
        """Return the current persistent local recent-track list."""
        if self.recent_store is None:
            return []
        return self.recent_store.list_recent(limit)

    def play_recent_track(self, track_uri: str) -> bool:
        """Replace the tracklist with one local track and start playback."""
        if self.music_backend is None or not self.is_local_track_uri(track_uri):
            return False

        load_tracks = getattr(self.music_backend, "load_tracks", None)
        if load_tracks is not None and not track_uri.startswith(LEGACY_TRACK_SCHEMES):
            return load_tracks([track_uri])

        legacy_load_track_uris = getattr(self.music_backend, "load_track_uris", None)
        if legacy_load_track_uris is not None:
            return legacy_load_track_uris([track_uri])

        return False

    def record_recent_track(self, track: Track | None) -> None:
        """Persist one local track play event when it belongs to the local library."""
        if track is None or not self.is_local_track_uri(track.uri) or self.recent_store is None:
            return
        self.recent_store.record_track(track)

    def shuffle_all(self) -> bool:
        """Build a shuffled queue from the local file library and start playback."""
        if self.music_backend is None:
            return False

        track_uris = self._collect_local_track_uris()
        if not track_uris:
            logger.warning("Shuffle requested, but no local tracks were found")
            return False

        random.shuffle(track_uris)

        load_tracks = getattr(self.music_backend, "load_tracks", None)
        if load_tracks is not None and not any(
            uri.startswith(LEGACY_TRACK_SCHEMES) for uri in track_uris
        ):
            return load_tracks(track_uris)

        legacy_load_track_uris = getattr(self.music_backend, "load_track_uris", None)
        if legacy_load_track_uris is not None:
            return legacy_load_track_uris(track_uris)

        return False

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
            if tracks:
                return tracks

        legacy_browse = getattr(self.music_backend, "browse_library", None)
        if legacy_browse is None:
            return tracks

        seen_uris: set[str] = set()
        for root_uri in LEGACY_LIBRARY_ROOTS:
            queue: deque[str] = deque([root_uri])
            local_seen: set[str] = set()

            while queue:
                current_uri = queue.popleft()
                if current_uri in local_seen:
                    continue
                local_seen.add(current_uri)

                refs = legacy_browse(current_uri)
                if not refs:
                    continue

                for ref in refs:
                    ref_uri = str(ref.get("uri", ""))
                    ref_type = str(ref.get("type", "")).lower()
                    if not ref_uri:
                        continue

                    if ref_type == "track":
                        if self.is_local_track_uri(ref_uri) and ref_uri not in seen_uris:
                            seen_uris.add(ref_uri)
                            tracks.append(ref_uri)
                    elif ref_type == "directory":
                        queue.append(ref_uri)

            if tracks:
                return tracks

        return tracks

    def _count_playlist_tracks(self, path: Path) -> int:
        """Return the number of playable entries declared in one M3U file."""
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            return 0
        return sum(1 for line in lines if line.strip() and not line.startswith("#"))


__all__ = [
    "AUDIO_EXTENSIONS",
    "LEGACY_LIBRARY_ROOTS",
    "LEGACY_PLAYLIST_SCHEMES",
    "LEGACY_TRACK_SCHEMES",
    "LocalLibraryItem",
    "LocalMusicService",
]
