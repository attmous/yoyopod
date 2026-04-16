"""Data models for the music backend."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.config import ConfigManager, MediaConfig as RuntimeMediaConfig


def _normalized_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    """Normalize mpv metadata keys for case-insensitive lookups."""
    return {str(key).lower(): value for key, value in metadata.items()}


def _artist_list(value: object) -> list[str]:
    """Coerce one mpv artist field into a normalized artist list."""
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, str) and item]
    return []


def _track_number(value: object) -> int | None:
    """Coerce one runtime track-number field into an integer when possible."""
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if not isinstance(value, str):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _duration_ms(value: object) -> int:
    """Coerce one mpv duration value in seconds into milliseconds."""
    if value in (None, "") or isinstance(value, bool):
        return 0

    try:
        return max(0, int(float(value) * 1000))
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True, slots=True)
class Track:
    """One music track."""

    uri: str
    name: str
    artists: list[str]
    album: str = ""
    length: int = 0  # milliseconds
    track_no: int | None = None

    def get_artist_string(self) -> str:
        """Get comma-separated artist names."""
        return ", ".join(self.artists) if self.artists else "Unknown Artist"

    @classmethod
    def from_mpv_metadata(cls, path: str, metadata: dict) -> Track:
        """Build from mpv's 'metadata' property dict at runtime."""
        metadata_map = _normalized_metadata(metadata)
        path_obj = Path(path)

        duration_ms = _duration_ms(metadata_map.get("duration", 0))

        runtime_title = metadata_map.get("title")
        title = runtime_title if isinstance(runtime_title, str) else ""
        if title == path_obj.name:
            title = path_obj.stem

        artists = _artist_list(metadata_map.get("artist"))
        album = metadata_map.get("album")
        album_name = album if isinstance(album, str) else ""
        track_no = _track_number(
            metadata_map.get("track")
            or metadata_map.get("track_no")
            or metadata_map.get("tracknumber")
        )

        file_track: Track | None = None
        if path_obj.exists() and (not title or not artists or not album_name or track_no is None):
            file_track = cls.from_file_tags(path_obj)

        return cls(
            uri=path,
            name=title or (file_track.name if file_track is not None else path_obj.stem),
            artists=artists or (file_track.artists if file_track is not None else ["Unknown"]),
            album=album_name or (file_track.album if file_track is not None else ""),
            length=duration_ms or (file_track.length if file_track is not None else 0),
            track_no=(
                track_no
                if track_no is not None
                else (file_track.track_no if file_track is not None else None)
            ),
        )

    @classmethod
    def from_file_tags(cls, path: Path) -> Track:
        """Build from file metadata tags using tinytag. Falls back to filename."""
        try:
            from tinytag import TinyTag

            tag = TinyTag.get(str(path))
            artist = tag.artist or getattr(tag, "albumartist", None)
            return cls(
                uri=str(path),
                name=tag.title or path.stem,
                artists=[artist] if artist else ["Unknown"],
                album=tag.album or "",
                length=int((tag.duration or 0) * 1000),
                track_no=int(tag.track) if tag.track is not None else None,
            )
        except Exception:
            return cls(
                uri=str(path),
                name=path.stem,
                artists=["Unknown"],
            )


@dataclass(frozen=True, slots=True)
class Playlist:
    """One M3U playlist."""

    uri: str
    name: str
    track_count: int = 0


@dataclass(slots=True)
class PlaybackQueue:
    """Runtime ordered track queue and current selection state."""

    name: str
    tracks: list[Track] = field(default_factory=list)
    source_uri: str | None = None
    current_index: int = 0

    @property
    def track_count(self) -> int:
        """Return the number of tracks currently loaded into the queue."""

        return len(self.tracks)

    def current_track(self) -> Track | None:
        """Return the selected track when the queue is not empty."""

        if 0 <= self.current_index < len(self.tracks):
            return self.tracks[self.current_index]
        return None

    def next_track(self) -> Track | None:
        """Advance to the next track and return it when available."""

        if self.current_index < len(self.tracks) - 1:
            self.current_index += 1
            return self.current_track()
        return None

    def previous_track(self) -> Track | None:
        """Move back to the previous track and return it when available."""

        if self.current_index > 0:
            self.current_index -= 1
            return self.current_track()
        return None

    def has_next(self) -> bool:
        """Return True when the queue can advance to another track."""

        return self.current_index < len(self.tracks) - 1

    def has_previous(self) -> bool:
        """Return True when the queue can move back to an earlier track."""

        return self.current_index > 0


def _default_mpv_socket() -> str:
    """Return the platform-appropriate default mpv IPC path."""
    if sys.platform == "win32":
        return r"\\.\pipe\yoyopod-mpv"
    return "/tmp/yoyopod-mpv.sock"


@dataclass(slots=True)
class MusicConfig:
    """Configuration for the mpv music backend."""

    music_dir: Path = Path("/home/pi/Music")
    mpv_socket: str = ""
    mpv_binary: str = "mpv"
    alsa_device: str = "default"

    def __post_init__(self) -> None:
        if not self.mpv_socket:
            self.mpv_socket = _default_mpv_socket()

    @classmethod
    def from_media_settings(cls, settings: "RuntimeMediaConfig | None") -> MusicConfig:
        """Translate composed media settings into the backend-facing mpv config."""

        music_settings = settings.music if settings is not None else None
        audio_settings = settings.audio if settings is not None else None
        return cls(
            music_dir=(
                Path(music_settings.music_dir)
                if music_settings is not None
                else Path("/home/pi/Music")
            ),
            mpv_socket=(
                music_settings.mpv_socket
                if music_settings and music_settings.mpv_socket
                else ""
            ),
            mpv_binary=music_settings.mpv_binary if music_settings is not None else "mpv",
            alsa_device=audio_settings.alsa_device if audio_settings is not None else "default",
        )

    @classmethod
    def from_config_manager(cls, config_manager: "ConfigManager | None") -> MusicConfig:
        """Build the backend-facing mpv config from the typed media runtime seam."""

        if config_manager is None:
            return cls()
        return cls.from_media_settings(config_manager.get_media_settings())
