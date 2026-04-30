"""Scaffold music integration for the Phase A spine rewrite."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from yoyopod.core import AudioFocusLostEvent
from yoyopod.integrations.music.events import (
    MusicAvailabilityChangedEvent,
    PlaybackStateChangedEvent,
    TrackChangedEvent,
)
from yoyopod.core.focus import ReleaseFocusCommand, RequestFocusCommand
from yoyopod.integrations.music.commands import (
    LoadPlaylistCommand,
    NextTrackCommand,
    PauseCommand,
    PlayCommand,
    PlayRecentTrackCommand,
    PreviousTrackCommand,
    ResumeCommand,
    SetVolumeCommand,
    ShuffleAllCommand,
    StopCommand,
)
from yoyopod.integrations.music.handlers import (
    apply_backend_availability,
    apply_playback_state,
    apply_track,
    apply_volume,
    seed_music_state,
)
from yoyopod.integrations.music.history import RecentTrackHistoryStore
from yoyopod.integrations.music.history import RecentTrackEntry
from yoyopod.integrations.music.library import LocalLibraryItem, LocalMusicService

if TYPE_CHECKING:
    from yoyopod.backends.music import MusicBackend, MusicConfig, Track
    from yoyopod.integrations.music.runtime import MusicRuntime


@dataclass(slots=True)
class MusicIntegration:
    """Runtime handles owned by the scaffold music integration."""

    backend: Any
    library: LocalMusicService
    recent_store: RecentTrackHistoryStore | None
    focus_owner: str = "music"


__all__ = [
    "MusicRuntime",
    "LoadPlaylistCommand",
    "LocalLibraryItem",
    "LocalMusicService",
    "MusicFSM",
    "MusicIntegration",
    "MusicAvailabilityChangedEvent",
    "MusicState",
    "NextTrackCommand",
    "PauseCommand",
    "PlaybackStateChangedEvent",
    "PlayCommand",
    "PlayRecentTrackCommand",
    "PreviousTrackCommand",
    "RecentTrackEntry",
    "RecentTrackHistoryStore",
    "ResumeCommand",
    "SetVolumeCommand",
    "ShuffleAllCommand",
    "StopCommand",
    "TrackChangedEvent",
    "setup",
    "teardown",
]


def __getattr__(name: str) -> Any:
    """Load relocated music exports lazily when needed."""

    if name in {"MusicFSM", "MusicState"}:
        from yoyopod.integrations.music.fsm import MusicFSM, MusicState

        return {"MusicFSM": MusicFSM, "MusicState": MusicState}[name]
    if name == "MusicRuntime":
        from yoyopod.integrations.music.runtime import MusicRuntime

        return MusicRuntime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def setup(
    app: Any,
    *,
    config: Any | None = None,
    backend: Any | None = None,
    library: LocalMusicService | None = None,
    recent_store: RecentTrackHistoryStore | None = None,
    default_volume: int | None = None,
) -> MusicIntegration:
    """Register the scaffold music services and state mirroring."""

    from yoyopod.backends.music import MusicConfig
    from yoyopod.backends.music.rust_host import RustHostBackend, default_worker_path

    actual_config = _resolve_music_config(app, explicit=config)
    actual_backend = backend or RustHostBackend(
        actual_config,
        worker_supervisor=app.worker_supervisor,
        worker_path=default_worker_path(),
        scheduler=app.scheduler,
    )
    actual_recent_store = recent_store
    if actual_recent_store is None and not getattr(actual_backend, "owns_library_state", False):
        actual_recent_store = _build_recent_store(app)
    actual_library = library or LocalMusicService(
        actual_backend,
        music_dir=Path(actual_config.music_dir),
        recent_store=actual_recent_store,
    )

    integration = MusicIntegration(
        backend=actual_backend,
        library=actual_library,
        recent_store=actual_recent_store,
    )
    app.integrations["music"] = integration
    app.music_backend = actual_backend
    app.local_music_service = actual_library

    backend_started = bool(actual_backend.start())
    effective_volume = (
        _resolve_default_volume(app)
        if default_volume is None
        else max(0, min(100, int(default_volume)))
    )
    seed_music_state(
        app,
        available=backend_started,
        volume_percent=effective_volume,
    )
    apply_backend_availability(app, available=backend_started, reason="startup")
    current_volume = getattr(actual_backend, "get_volume", lambda: None)()
    if current_volume is not None:
        apply_volume(app, int(current_volume))

    def on_track_change(track: Track | None) -> None:
        app.scheduler.run_on_main(lambda: _handle_track_change(app, integration, track))

    def on_playback_state_change(playback_state: str) -> None:
        app.scheduler.run_on_main(
            lambda: _handle_playback_state_change(app, integration, playback_state)
        )

    def on_connection_change(connected: bool, reason: str) -> None:
        app.scheduler.run_on_main(
            lambda: _handle_connection_change(app, connected=connected, reason=reason)
        )

    actual_backend.on_track_change(on_track_change)
    actual_backend.on_playback_state_change(on_playback_state_change)
    actual_backend.on_connection_change(on_connection_change)
    app.bus.subscribe(
        AudioFocusLostEvent,
        lambda event: _handle_focus_lost(app, integration, event),
    )

    app.services.register("music", "play", lambda data: _play_track(app, integration, data))
    app.services.register(
        "music",
        "load_playlist",
        lambda data: _load_playlist(app, integration, data),
    )
    app.services.register(
        "music",
        "play_recent_track",
        lambda data: _play_recent_track(app, integration, data),
    )
    app.services.register(
        "music",
        "shuffle_all",
        lambda data: _shuffle_all(app, integration, data),
    )
    app.services.register("music", "pause", lambda data: _pause(app, integration, data))
    app.services.register("music", "resume", lambda data: _resume(app, integration, data))
    app.services.register("music", "stop", lambda data: _stop(app, integration, data))
    app.services.register("music", "next_track", lambda data: _next_track(integration, data))
    app.services.register(
        "music",
        "previous_track",
        lambda data: _previous_track(integration, data),
    )
    app.services.register(
        "music",
        "set_volume",
        lambda data: _set_volume(app, integration, data),
    )

    app.get_music_position = lambda: _safe_time_position_ms(actual_backend)
    app.get_music_library = lambda: integration.library
    return integration


def teardown(app: Any) -> None:
    """Stop the backend and drop exposed integration helpers."""

    integration = app.integrations.pop("music", None)
    if integration is None:
        return

    stop = getattr(integration.backend, "stop", None)
    if callable(stop):
        stop()
    if getattr(app, "music_backend", None) is integration.backend:
        app.music_backend = None
    if getattr(app, "local_music_service", None) is integration.library:
        app.local_music_service = None
    if hasattr(app, "get_music_position"):
        delattr(app, "get_music_position")
    if hasattr(app, "get_music_library"):
        delattr(app, "get_music_library")


def _resolve_music_config(app: Any, *, explicit: Any | None) -> Any:
    if explicit is not None:
        return explicit

    if getattr(app, "config_manager", None) is not None:
        from yoyopod.backends.music import MusicConfig

        return MusicConfig.from_config_manager(app.config_manager)

    config = getattr(app, "config", None)
    media = getattr(config, "media", None)
    if media is not None:
        from yoyopod.backends.music import MusicConfig

        music = getattr(media, "music", None)
        audio = getattr(media, "audio", None)
        if music is not None and audio is not None:
            return MusicConfig.from_media_settings(media)
        return MusicConfig(
            music_dir=Path(getattr(music, "music_dir", "/home/pi/Music")),
            mpv_socket=str(getattr(music, "mpv_socket", "") or ""),
            mpv_binary=str(getattr(music, "mpv_binary", "mpv") or "mpv"),
            alsa_device=str(getattr(audio, "alsa_device", "default") or "default"),
        )

    from yoyopod.backends.music import MusicConfig

    return MusicConfig()


def _resolve_default_volume(app: Any) -> int:
    if getattr(app, "config_manager", None) is not None:
        try:
            return int(app.config_manager.get_default_output_volume())
        except Exception:
            pass

    config = getattr(app, "config", None)
    media = getattr(config, "media", None)
    if media is not None:
        music = getattr(media, "music", None)
        if music is not None and hasattr(music, "default_volume"):
            return max(0, min(100, int(music.default_volume)))
    audio = getattr(config, "audio", None)
    if audio is not None and hasattr(audio, "default_volume"):
        return max(0, min(100, int(audio.default_volume)))
    return 70


def _build_recent_store(app: Any) -> RecentTrackHistoryStore | None:
    if getattr(app, "config_manager", None) is not None:
        try:
            return RecentTrackHistoryStore(app.config_manager.get_recent_tracks_file())
        except Exception:
            return None

    config = getattr(app, "config", None)
    media = getattr(config, "media", None)
    if media is not None:
        music = getattr(media, "music", None)
        recent_tracks_file = getattr(music, "recent_tracks_file", None)
        if recent_tracks_file:
            return RecentTrackHistoryStore(recent_tracks_file)
    return None


def _request_focus(app: Any) -> bool:
    return bool(
        app.services.call(
            "focus",
            "request",
            RequestFocusCommand(owner="music"),
        )
    )


def _release_focus_if_owned(app: Any) -> None:
    if app.states.get_value("focus.owner") != "music":
        return
    app.services.call("focus", "release", ReleaseFocusCommand(owner="music"))


def _play_track(app: Any, integration: MusicIntegration, data: PlayCommand) -> bool:
    if not isinstance(data, PlayCommand):
        raise TypeError("music.play expects PlayCommand")
    if not _request_focus(app):
        return False
    return bool(integration.backend.load_tracks([data.track_uri]))


def _load_playlist(app: Any, integration: MusicIntegration, data: LoadPlaylistCommand) -> bool:
    if not isinstance(data, LoadPlaylistCommand):
        raise TypeError("music.load_playlist expects LoadPlaylistCommand")
    if not _request_focus(app):
        return False
    return bool(integration.library.load_playlist(data.playlist_uri))


def _play_recent_track(
    app: Any,
    integration: MusicIntegration,
    data: PlayRecentTrackCommand,
) -> bool:
    if not isinstance(data, PlayRecentTrackCommand):
        raise TypeError("music.play_recent_track expects PlayRecentTrackCommand")
    if not _request_focus(app):
        return False
    return bool(integration.library.play_recent_track(data.track_uri))


def _shuffle_all(app: Any, integration: MusicIntegration, data: ShuffleAllCommand | None) -> bool:
    if data is not None and not isinstance(data, ShuffleAllCommand):
        raise TypeError("music.shuffle_all expects ShuffleAllCommand")
    if not _request_focus(app):
        return False
    return bool(integration.library.shuffle_all())


def _pause(app: Any, integration: MusicIntegration, data: PauseCommand) -> bool:
    if not isinstance(data, PauseCommand):
        raise TypeError("music.pause expects PauseCommand")
    return bool(integration.backend.pause())


def _resume(app: Any, integration: MusicIntegration, data: ResumeCommand) -> bool:
    if not isinstance(data, ResumeCommand):
        raise TypeError("music.resume expects ResumeCommand")
    if not _request_focus(app):
        return False
    return bool(integration.backend.play())


def _stop(app: Any, integration: MusicIntegration, data: StopCommand) -> bool:
    if not isinstance(data, StopCommand):
        raise TypeError("music.stop expects StopCommand")
    stopped = bool(integration.backend.stop_playback())
    _release_focus_if_owned(app)
    return stopped


def _next_track(integration: MusicIntegration, data: NextTrackCommand) -> bool:
    if not isinstance(data, NextTrackCommand):
        raise TypeError("music.next_track expects NextTrackCommand")
    return bool(integration.backend.next_track())


def _previous_track(integration: MusicIntegration, data: PreviousTrackCommand) -> bool:
    if not isinstance(data, PreviousTrackCommand):
        raise TypeError("music.previous_track expects PreviousTrackCommand")
    return bool(integration.backend.previous_track())


def _set_volume(app: Any, integration: MusicIntegration, data: SetVolumeCommand) -> int:
    if not isinstance(data, SetVolumeCommand):
        raise TypeError("music.set_volume expects SetVolumeCommand")
    percent = apply_volume(app, data.percent)
    integration.backend.set_volume(percent)
    return percent


def _handle_track_change(app: Any, integration: MusicIntegration, track: Track | None) -> None:
    applied_track = apply_track(app, track)
    if applied_track is None:
        return
    integration.library.record_recent_track(applied_track)


def _handle_playback_state_change(
    app: Any,
    integration: MusicIntegration,
    playback_state: str,
) -> None:
    normalized = apply_playback_state(app, playback_state)
    if normalized == "idle":
        _release_focus_if_owned(app)


def _handle_connection_change(app: Any, *, connected: bool, reason: str) -> None:
    apply_backend_availability(app, available=connected, reason=reason)


def _handle_focus_lost(
    app: Any,
    integration: MusicIntegration,
    event: AudioFocusLostEvent,
) -> None:
    if event.owner != "music":
        return
    if app.states.get_value("music.state") != "playing":
        return
    integration.backend.pause()


def _safe_time_position_ms(backend: Any) -> int:
    try:
        return int(backend.get_time_position())
    except Exception:
        return 0
