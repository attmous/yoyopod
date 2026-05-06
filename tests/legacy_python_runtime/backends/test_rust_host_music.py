from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from yoyopod.backends.music.models import MusicConfig, Playlist, Track
from yoyopod.backends.music.rust_host import RustHostBackend
from yoyopod.core.scheduler import MainThreadScheduler
from yoyopod.integrations.music.history import RecentTrackEntry
from yoyopod.integrations.music.library import LocalLibraryItem


class _FakeSupervisor:
    def __init__(self) -> None:
        self.registered: list[tuple[str, Any]] = []
        self.started: list[str] = []
        self.stopped: list[tuple[str, float]] = []
        self.sent: list[tuple[str, str, dict[str, Any]]] = []
        self.request_ids: list[str | None] = []

    def register(self, domain: str, config: Any) -> None:
        self.registered.append((domain, config))

    def start(self, domain: str) -> bool:
        self.started.append(domain)
        return True

    def stop(self, domain: str, *, grace_seconds: float = 1.0) -> None:
        self.stopped.append((domain, grace_seconds))

    def send_command(
        self,
        domain: str,
        *,
        type: str,
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        timestamp_ms: int = 0,
        deadline_ms: int = 0,
    ) -> bool:
        del timestamp_ms, deadline_ms
        self.sent.append((domain, type, payload or {}))
        self.request_ids.append(request_id)
        return True

    def send_request(
        self,
        domain: str,
        *,
        type: str,
        payload: dict[str, Any],
        request_id: str,
        timeout_seconds: float,
    ) -> bool:
        del timeout_seconds
        self.sent.append((domain, type, payload))
        self.request_ids.append(request_id)
        return True


class _StrictSupervisor(_FakeSupervisor):
    def stop(self, domain: str, *, grace_seconds: float = 1.0) -> None:
        if not any(registered_domain == domain for registered_domain, _config in self.registered):
            raise KeyError(domain)
        super().stop(domain, grace_seconds=grace_seconds)


class _ThreadCheckingSupervisor(_FakeSupervisor):
    def __init__(self, *, main_thread_id: int) -> None:
        super().__init__()
        self.main_thread_id = main_thread_id
        self.register_thread_ids: list[int] = []
        self.start_thread_ids: list[int] = []

    def register(self, domain: str, config: Any) -> None:
        self.register_thread_ids.append(threading.get_ident())
        super().register(domain, config)

    def start(self, domain: str) -> bool:
        self.start_thread_ids.append(threading.get_ident())
        return super().start(domain)


def _config() -> MusicConfig:
    return MusicConfig(
        music_dir=Path("/music"),
        mpv_socket="/tmp/yoyopod-mpv.sock",
        mpv_binary="mpv",
        alsa_device="default",
        default_volume=72,
        recent_tracks_file="data/media/recent_tracks.json",
        remote_cache_dir="data/media/remote_cache",
        remote_cache_max_bytes=64 * 1024 * 1024,
    )


def _event(message_type: str, payload: dict[str, Any], *, domain: str = "media") -> Any:
    return SimpleNamespace(domain=domain, kind="event", type=message_type, payload=payload)


def _state(state: str, reason: str, *, domain: str = "media") -> Any:
    return SimpleNamespace(domain=domain, state=state, reason=reason)


def _reply(
    kind: str,
    message_type: str,
    payload: dict[str, Any],
    *,
    request_id: str | None,
    domain: str = "media",
) -> Any:
    return SimpleNamespace(
        domain=domain,
        kind=kind,
        type=message_type,
        request_id=request_id,
        payload=payload,
    )


class _InlineScheduler:
    main_thread_id = 0

    def run_on_main(self, callback) -> None:
        callback()


def test_start_registers_worker_and_sends_configure_start() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/media")

    assert backend.start() is True

    assert supervisor.registered[0][0] == "media"
    assert supervisor.registered[0][1].argv == ["/bin/media"]
    assert supervisor.started == ["media"]
    assert [item[1] for item in supervisor.sent] == ["media.configure", "media.start"]
    assert supervisor.sent[0][2]["music_dir"] == str(_config().music_dir)
    assert supervisor.sent[0][2]["default_volume"] == 72
    assert supervisor.sent[0][2]["recent_tracks_file"] == "data/media/recent_tracks.json"
    assert supervisor.sent[0][2]["remote_cache_dir"] == "data/media/remote_cache"
    assert supervisor.sent[0][2]["remote_cache_max_bytes"] == 64 * 1024 * 1024
    assert supervisor.request_ids == ["media-media_configure-1", "media-media_start-2"]
    assert backend.running is True
    assert backend.startup_in_progress is False


def test_stop_before_worker_registration_is_noop() -> None:
    supervisor = _StrictSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/media")

    backend.stop()

    assert supervisor.sent == []
    assert supervisor.stopped == []
    assert backend.running is False


def test_playback_and_library_commands_send_worker_commands() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/media")
    backend.start()
    supervisor.sent.clear()

    assert backend.play() is True
    assert backend.pause() is True
    assert backend.stop_playback() is True
    assert backend.next_track() is True
    assert backend.previous_track() is True
    assert backend.load_tracks(["/music/one.mp3", "/music/two.mp3"]) is True
    assert backend.load_playlist_file("/music/Favorites.m3u") is True
    assert backend.set_volume(63) is True
    assert backend.set_audio_device("alsa/sysdefault") is True
    assert backend.shuffle_all() is True
    assert backend.play_recent_track("/music/one.mp3") is True

    assert [item[1] for item in supervisor.sent] == [
        "media.play",
        "media.pause",
        "media.stop_playback",
        "media.next_track",
        "media.previous_track",
        "media.load_tracks",
        "media.load_playlist",
        "media.set_volume",
        "media.set_audio_device",
        "media.shuffle_all",
        "media.play_recent_track",
    ]
    assert supervisor.sent[5][2] == {"uris": ["/music/one.mp3", "/music/two.mp3"]}
    assert supervisor.sent[6][2] == {"path": "/music/Favorites.m3u"}
    assert supervisor.sent[7][2] == {"volume": 63}
    assert supervisor.sent[8][2] == {"device": "alsa/sysdefault"}
    assert supervisor.sent[10][2] == {"track_uri": "/music/one.mp3"}


def test_snapshot_updates_cached_state_and_fires_callbacks() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/media")
    track_changes: list[Track | None] = []
    playback_states: list[str] = []
    connection_changes: list[tuple[bool, str]] = []
    backend.on_track_change(track_changes.append)
    backend.on_playback_state_change(playback_states.append)
    backend.on_connection_change(lambda connected, reason: connection_changes.append((connected, reason)))

    backend.handle_worker_message(
        _event(
            "media.snapshot",
            {
                "configured": True,
                "connected": True,
                "backend_state": "connected",
                "default_volume": 70,
                "playlist_count": 1,
                "library_menu": [
                    {"key": "playlists", "title": "Playlists", "subtitle": "Saved mixes"}
                ],
                "playlists": [
                    {"uri": "/music/Favorites.m3u", "name": "Favorites", "track_count": 2}
                ],
                "recent_tracks": [
                    {
                        "uri": "/music/one.mp3",
                        "title": "One",
                        "artist": "Artist",
                        "album": "Album",
                    }
                ],
                "current_track": {
                    "uri": "/music/one.mp3",
                    "name": "One",
                    "artists": ["Artist"],
                    "album": "Album",
                    "length_ms": 123000,
                    "track_no": 3,
                },
                "playback_state": "playing",
                "time_position_ms": 4200,
            },
        )
    )

    assert backend.is_connected is True
    assert backend.library_state_ready is True
    assert backend.get_playback_state() == "playing"
    assert backend.get_time_position() == 4200
    assert backend.get_volume() == 70
    assert backend.get_current_track() == Track(
        uri="/music/one.mp3",
        name="One",
        artists=["Artist"],
        album="Album",
        length=123000,
        track_no=3,
    )
    assert backend.list_playlists() == [
        Playlist(uri="/music/Favorites.m3u", name="Favorites", track_count=2)
    ]
    assert backend.menu_items() == [
        LocalLibraryItem(key="playlists", title="Playlists", subtitle="Saved mixes")
    ]
    assert backend.list_recent_tracks() == [
        RecentTrackEntry(
            uri="/music/one.mp3",
            title="One",
            artist="Artist",
            album="Album",
            played_at="",
        )
    ]
    assert connection_changes == [(True, "connected")]
    assert playback_states == ["playing"]
    assert track_changes == [backend.get_current_track()]


def test_worker_restart_ready_resends_configure_and_start() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/media")
    connection_changes: list[tuple[bool, str]] = []
    backend.on_connection_change(lambda connected, reason: connection_changes.append((connected, reason)))
    backend.start()
    backend.handle_worker_message(
        _event(
            "media.snapshot",
            {
                "connected": True,
                "backend_state": "connected",
                "playback_state": "stopped",
                "time_position_ms": 0,
            },
        )
    )

    backend.handle_worker_state_change(_state("degraded", "process_exited"))
    backend.handle_worker_state_change(_state("running", "started"))
    backend.handle_worker_message(_event("media.ready", {"capabilities": ["playback"]}))

    assert [item[1] for item in supervisor.sent] == [
        "media.configure",
        "media.start",
        "media.configure",
        "media.start",
    ]
    assert connection_changes == [(True, "connected"), (False, "process_exited")]
    assert backend.running is True


def test_wrong_domain_worker_messages_are_ignored() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/media")

    backend.handle_worker_message(_event("media.snapshot", {"connected": True}, domain="ui"))
    backend.handle_worker_state_change(_state("degraded", "wrong", domain="ui"))

    assert backend.is_connected is False
    assert backend.get_current_track() is None


def test_correlated_runtime_command_error_does_not_stop_backend() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/media")

    assert backend.start() is True
    assert backend.load_playlist_file("/music/missing.m3u") is True

    request_id = supervisor.request_ids[-1]
    assert request_id is not None

    backend.handle_worker_message(
        _reply(
            "error",
            "media.error",
            {"code": "command_failed", "message": "playlist missing"},
            request_id=request_id,
        )
    )

    assert backend.running is True
    assert supervisor.stopped == []


def test_prepare_remote_playback_asset_waits_for_worker_result() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(
        _config(),
        worker_supervisor=supervisor,
        worker_path="/bin/media",
        scheduler=_InlineScheduler(),
    )
    result: dict[str, object] = {}

    def _run() -> None:
        result["asset"] = backend.prepare_remote_playback_asset(
            track_id="track-1",
            media_url="https://media.example.test/track.mp3",
            checksum_sha256="abc123",
            extension=".mp3",
        )

    import threading
    import time

    thread = threading.Thread(target=_run)
    thread.start()
    deadline = time.monotonic() + 1.0
    while not supervisor.request_ids and time.monotonic() < deadline:
        time.sleep(0.01)
    backend.handle_worker_message(
        _reply(
            "result",
            "media.prepare_remote_asset",
            {"path": "/tmp/cached-track.mp3", "cache_hit": False},
            request_id=supervisor.request_ids[-1],
        )
    )
    thread.join(timeout=1.0)

    asset = result["asset"]
    assert getattr(asset, "path") == "/tmp/cached-track.mp3"
    assert getattr(asset, "cache_hit") is False


def test_import_remote_media_asset_waits_for_worker_result() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(
        _config(),
        worker_supervisor=supervisor,
        worker_path="/bin/media",
        scheduler=_InlineScheduler(),
    )
    result: dict[str, object] = {}

    def _run() -> None:
        result["path"] = backend.import_remote_media_asset(
            track_id="track-2",
            cached_path="/tmp/cached-track.mp3",
            title="Track Two",
            filename="track-two.mp3",
        )

    import threading
    import time

    thread = threading.Thread(target=_run)
    thread.start()
    deadline = time.monotonic() + 1.0
    while not supervisor.request_ids and time.monotonic() < deadline:
        time.sleep(0.01)
    backend.handle_worker_message(
        _reply(
            "result",
            "media.import_remote_asset",
            {"path": "/music/dashboard_uploads/Track-Two-track-2.mp3"},
            request_id=supervisor.request_ids[-1],
        )
    )
    thread.join(timeout=1.0)

    assert result["path"] == "/music/dashboard_uploads/Track-Two-track-2.mp3"


def test_warm_start_posts_worker_start_back_to_main_thread() -> None:
    scheduler = MainThreadScheduler()
    supervisor = _ThreadCheckingSupervisor(main_thread_id=scheduler.main_thread_id)
    backend = RustHostBackend(
        _config(),
        worker_supervisor=supervisor,
        worker_path="/bin/media",
        scheduler=scheduler,
    )

    backend.warm_start()

    deadline = time.monotonic() + 1.0
    while scheduler.pending_count() == 0 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert scheduler.pending_count() == 1
    assert supervisor.start_thread_ids == []
    assert backend.startup_in_progress is True

    assert scheduler.drain() == 1

    deadline = time.monotonic() + 1.0
    while backend.startup_in_progress and time.monotonic() < deadline:
        time.sleep(0.01)

    assert supervisor.register_thread_ids == [scheduler.main_thread_id]
    assert supervisor.start_thread_ids == [scheduler.main_thread_id]
    assert backend.running is True
