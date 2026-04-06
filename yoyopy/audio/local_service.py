"""Local-first music facade built on top of Mopidy."""

from __future__ import annotations

import random
from collections import deque
from dataclasses import dataclass
from typing import Any

from loguru import logger

from yoyopy.audio.history import RecentTrackEntry, RecentTrackHistoryStore
from yoyopy.audio.mopidy_client import MopidyClient, MopidyPlaylist, MopidyTrack


LOCAL_PLAYLIST_SCHEMES = ("m3u:",)
LOCAL_TRACK_SCHEMES = ("local:", "file:")
LOCAL_LIBRARY_ROOTS = ("file:", "local:directory")


@dataclass(frozen=True, slots=True)
class LocalLibraryItem:
    """One entry in the local Listen landing menu."""

    key: str
    title: str
    subtitle: str


class LocalMusicService:
    """App-facing local music operations backed by Mopidy."""

    def __init__(
        self,
        mopidy_client: MopidyClient | None,
        recent_store: RecentTrackHistoryStore | None = None,
    ) -> None:
        self.mopidy_client = mopidy_client
        self.recent_store = recent_store

    @property
    def is_available(self) -> bool:
        """Return True when the Mopidy backend is connected."""

        return bool(self.mopidy_client and self.mopidy_client.is_connected)

    @staticmethod
    def is_local_playlist_uri(uri: str) -> bool:
        """Return True when the playlist URI belongs to the local playlist backend."""

        return uri.startswith(LOCAL_PLAYLIST_SCHEMES)

    @staticmethod
    def is_local_track_uri(uri: str) -> bool:
        """Return True when the track URI belongs to the local/file library."""

        return uri.startswith(LOCAL_TRACK_SCHEMES)

    def menu_items(self) -> list[LocalLibraryItem]:
        """Return the static local-first Listen landing menu."""

        return [
            LocalLibraryItem("playlists", "Playlists", "Saved mixes"),
            LocalLibraryItem("recent", "Recent", "Played lately"),
            LocalLibraryItem("shuffle", "Shuffle", "Start something fun"),
        ]

    def list_playlists(self, fetch_track_counts: bool = False) -> list[MopidyPlaylist]:
        """Return only local playlists from the Mopidy playlist registry."""

        if self.mopidy_client is None:
            return []

        playlists = self.mopidy_client.get_playlists(fetch_track_counts=fetch_track_counts)
        return [playlist for playlist in playlists if self.is_local_playlist_uri(playlist.uri)]

    def playlist_count(self) -> int:
        """Return the number of local playlists without fetching track counts."""

        return len(self.list_playlists(fetch_track_counts=False))

    def load_playlist(self, playlist_uri: str) -> bool:
        """Load and play one local playlist."""

        if self.mopidy_client is None or not self.is_local_playlist_uri(playlist_uri):
            return False
        return self.mopidy_client.load_playlist(playlist_uri)

    def list_recent_tracks(self, limit: int | None = None) -> list[RecentTrackEntry]:
        """Return the current persistent local recent-track list."""

        if self.recent_store is None:
            return []
        return self.recent_store.list_recent(limit)

    def play_recent_track(self, track_uri: str) -> bool:
        """Replace the tracklist with one local track and start playback."""

        if self.mopidy_client is None or not self.is_local_track_uri(track_uri):
            return False
        return self.mopidy_client.load_track_uris([track_uri])

    def record_recent_track(self, track: MopidyTrack | None) -> None:
        """Persist one local track play event when it belongs to the local library."""

        if track is None or not self.is_local_track_uri(track.uri) or self.recent_store is None:
            return
        self.recent_store.record_track(track)

    def shuffle_all(self) -> bool:
        """Build a shuffled queue from the local file library and start playback."""

        if self.mopidy_client is None:
            return False

        track_uris = self._collect_local_track_uris()
        if not track_uris:
            logger.warning("Shuffle requested, but no local tracks were found")
            return False

        random.shuffle(track_uris)
        return self.mopidy_client.load_track_uris(track_uris)

    def _collect_local_track_uris(self) -> list[str]:
        """Recursively browse configured local library roots and collect track URIs."""

        if self.mopidy_client is None:
            return []

        tracks: list[str] = []
        seen_uris: set[str] = set()

        for root_uri in LOCAL_LIBRARY_ROOTS:
            queue: deque[str] = deque([root_uri])
            local_seen: set[str] = set()

            while queue:
                current_uri = queue.popleft()
                if current_uri in local_seen:
                    continue
                local_seen.add(current_uri)

                refs = self.mopidy_client.browse_library(current_uri)
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
