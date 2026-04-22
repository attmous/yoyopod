"""Persistent recent-track history for local-first Listen flows."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from yoyopod.backends.music import Track


def _utc_now_iso() -> str:
    """Return the current UTC timestamp as an ISO8601 string."""

    return datetime.now(timezone.utc).isoformat()


@dataclass(slots=True)
class RecentTrackEntry:
    """One persisted local track play event."""

    uri: str
    title: str
    artist: str
    album: str = ""
    played_at: str = field(default_factory=_utc_now_iso)

    @property
    def subtitle(self) -> str:
        """Return the compact subtitle shown in recent-track lists."""

        if self.artist and self.album:
            return f"{self.artist} - {self.album}"
        if self.artist:
            return self.artist
        if self.album:
            return self.album
        return "Played recently"

    @classmethod
    def from_track(cls, track: Track) -> "RecentTrackEntry":
        """Create a persistent recent-entry from the current track."""

        return cls(
            uri=track.uri,
            title=track.name or "Unknown Track",
            artist=track.get_artist_string() or "Unknown Artist",
            album=track.album or "",
            played_at=_utc_now_iso(),
        )

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "RecentTrackEntry":
        """Build an entry from persisted JSON data."""

        return cls(
            uri=str(data.get("uri", "")),
            title=str(data.get("title", "Unknown Track")),
            artist=str(data.get("artist", "Unknown Artist")),
            album=str(data.get("album", "")),
            played_at=str(data.get("played_at", _utc_now_iso())),
        )


class RecentTrackHistoryStore:
    """Persist and query recently played local tracks."""

    def __init__(self, history_file: str | Path, max_entries: int = 50) -> None:
        self.history_file = Path(history_file)
        self.max_entries = max(1, int(max_entries))
        self._entries: list[RecentTrackEntry] = []
        self.load()

    def load(self) -> None:
        """Load history from disk if present."""

        if not self.history_file.exists():
            self._entries = []
            return

        try:
            with open(self.history_file, "r", encoding="utf-8") as handle:
                payload = json.load(handle) or {}
            items = payload.get("entries", [])
            self._entries = [RecentTrackEntry.from_dict(item) for item in items]
            self._entries = self._entries[: self.max_entries]
        except Exception as exc:
            logger.warning(f"Failed to load recent tracks from {self.history_file}: {exc}")
            self._entries = []

    def save(self) -> None:
        """Persist the current recent-track state to disk."""

        try:
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "w", encoding="utf-8") as handle:
                json.dump(
                    {"entries": [asdict(entry) for entry in self._entries[: self.max_entries]]},
                    handle,
                    indent=2,
                )
        except Exception as exc:
            logger.warning(f"Failed to save recent tracks to {self.history_file}: {exc}")

    def record_track(self, track: Track) -> None:
        """Move the current track to the front of the local recents list."""

        entry = RecentTrackEntry.from_track(track)
        self._entries = [item for item in self._entries if item.uri != entry.uri]
        self._entries.insert(0, entry)
        self._entries = self._entries[: self.max_entries]
        self.save()

    def list_recent(self, limit: int | None = None) -> list[RecentTrackEntry]:
        """Return the recent track list, newest first."""

        if limit is None:
            return list(self._entries)
        return list(self._entries[: max(0, limit)])


__all__ = ["RecentTrackEntry", "RecentTrackHistoryStore"]
