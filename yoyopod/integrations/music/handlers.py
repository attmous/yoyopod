"""State helpers for the scaffold music integration."""

from __future__ import annotations

from typing import Any

from yoyopod.backends.music.models import Track


def seed_music_state(app: Any, *, available: bool, volume_percent: int) -> None:
    """Seed the core music entities owned by the integration."""

    app.states.set("music.state", "idle", {"raw_state": "stopped"})
    app.states.set("music.track", None, {})
    app.states.set("music.backend_available", bool(available), {"reason": "startup"})
    app.states.set("music.volume_percent", max(0, min(100, int(volume_percent))), {})


def apply_playback_state(app: Any, playback_state: str) -> str:
    """Mirror one backend playback state into the state store."""

    normalized = _normalized_playback_state(playback_state)
    app.states.set(
        "music.state",
        normalized,
        {"raw_state": str(playback_state)},
    )
    return normalized


def apply_track(app: Any, track: Track | None) -> Track | None:
    """Mirror the current track into the state store."""

    if track is None:
        app.states.set("music.track", None, {})
        return None

    app.states.set(
        "music.track",
        track,
        {
            "title": track.name,
            "artist": track.get_artist_string(),
            "album": track.album,
            "duration_ms": track.length,
            "track_no": track.track_no,
            "uri": track.uri,
        },
    )
    return track


def apply_backend_availability(app: Any, *, available: bool, reason: str = "") -> bool:
    """Mirror backend connectivity into state."""

    app.states.set(
        "music.backend_available",
        bool(available),
        {"reason": reason},
    )
    return bool(available)


def apply_volume(app: Any, percent: int) -> int:
    """Mirror the effective output volume into state."""

    clamped = max(0, min(100, int(percent)))
    app.states.set("music.volume_percent", clamped, {})
    return clamped


def _normalized_playback_state(playback_state: str) -> str:
    value = str(playback_state).strip().lower()
    if value in {"playing", "paused"}:
        return value
    return "idle"
