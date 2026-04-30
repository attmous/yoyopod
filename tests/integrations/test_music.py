"""Tests for the scaffold music integration."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from yoyopod.backends.music import Track
from tests.fixtures.app import build_test_app, drain_all
from yoyopod.core import AudioFocusLostEvent
from yoyopod.core.focus import setup as setup_focus
from yoyopod.integrations.music import (
    LoadPlaylistCommand,
    MusicIntegration,
    NextTrackCommand,
    PauseCommand,
    PlayCommand,
    PlayRecentTrackCommand,
    PreviousTrackCommand,
    ResumeCommand,
    SetVolumeCommand,
    ShuffleAllCommand,
    StopCommand,
    setup,
    teardown,
)


class FakeMusicBackend:
    """Minimal backend double for the scaffold music integration tests."""

    def __init__(self) -> None:
        self._connected = False
        self._volume = 42
        self.commands: list[str] = []
        self.loaded_tracks: list[list[str]] = []
        self.track_change_callback = None
        self.playback_state_callback = None
        self.connection_change_callback = None
        self.time_position_ms = 1337

    def start(self) -> bool:
        self._connected = True
        return True

    def stop(self) -> None:
        self._connected = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def load_tracks(self, uris: list[str]) -> bool:
        self.loaded_tracks.append(list(uris))
        self.commands.append("load_tracks")
        if self.playback_state_callback is not None:
            self.playback_state_callback("playing")
        return True

    def load_playlist_file(self, path: str) -> bool:
        self.commands.append(f"playlist:{path}")
        if self.playback_state_callback is not None:
            self.playback_state_callback("playing")
        return True

    def play(self) -> bool:
        self.commands.append("play")
        if self.playback_state_callback is not None:
            self.playback_state_callback("playing")
        return True

    def pause(self) -> bool:
        self.commands.append("pause")
        if self.playback_state_callback is not None:
            self.playback_state_callback("paused")
        return True

    def stop_playback(self) -> bool:
        self.commands.append("stop")
        if self.playback_state_callback is not None:
            self.playback_state_callback("stopped")
        return True

    def next_track(self) -> bool:
        self.commands.append("next")
        return True

    def previous_track(self) -> bool:
        self.commands.append("previous")
        return True

    def set_volume(self, volume: int) -> bool:
        self._volume = volume
        self.commands.append(f"volume:{volume}")
        return True

    def get_volume(self) -> int:
        return self._volume

    def get_time_position(self) -> int:
        return self.time_position_ms

    def on_track_change(self, callback) -> None:
        self.track_change_callback = callback

    def on_playback_state_change(self, callback) -> None:
        self.playback_state_callback = callback

    def on_connection_change(self, callback) -> None:
        self.connection_change_callback = callback

    def emit_track(self, track: Track | None) -> None:
        if self.track_change_callback is not None:
            self.track_change_callback(track)

    def emit_connection_change(self, connected: bool, reason: str) -> None:
        if self.connection_change_callback is not None:
            self.connection_change_callback(connected, reason)


class FakeLibrary:
    """Minimal local-library double for exercising integration services."""

    def __init__(self) -> None:
        self.load_playlist_calls: list[str] = []
        self.play_recent_track_calls: list[str] = []
        self.shuffle_all_calls = 0
        self.recorded_tracks: list[Track] = []

    def load_playlist(self, playlist_uri: str) -> bool:
        self.load_playlist_calls.append(playlist_uri)
        return True

    def play_recent_track(self, track_uri: str) -> bool:
        self.play_recent_track_calls.append(track_uri)
        return True

    def shuffle_all(self) -> bool:
        self.shuffle_all_calls += 1
        return True

    def record_recent_track(self, track: Track | None) -> None:
        if track is not None:
            self.recorded_tracks.append(track)


def test_music_setup_seeds_state_and_helpers(tmp_path: Path) -> None:
    app = build_test_app()
    app.config = SimpleNamespace(
        audio=SimpleNamespace(default_volume=61),
        media=SimpleNamespace(
            music=SimpleNamespace(recent_tracks_file=str(tmp_path / "recent_tracks.json")),
        ),
    )
    setup_focus(app)

    integration = setup(app, backend=FakeMusicBackend())

    assert isinstance(integration, MusicIntegration)
    assert integration is app.integrations["music"]
    assert app.states.get_value("music.state") == "idle"
    assert app.states.get_value("music.backend_available") is True
    assert app.states.get_value("music.volume_percent") == 42
    assert callable(app.get_music_position)
    assert app.get_music_position() == 1337


def test_music_setup_defaults_to_rust_media_host_backend(monkeypatch) -> None:
    app = build_test_app()
    app.config = SimpleNamespace(
        audio=SimpleNamespace(default_volume=61),
        media=SimpleNamespace(
            music=SimpleNamespace(recent_tracks_file="data/media/recent_tracks.json"),
        ),
    )
    captured: dict[str, object] = {}

    class _FakeRustBackend:
        def __init__(
            self,
            config,
            *,
            worker_supervisor,
            worker_path,
            scheduler,
        ) -> None:
            captured["config"] = config
            captured["worker_supervisor"] = worker_supervisor
            captured["worker_path"] = worker_path
            captured["scheduler"] = scheduler
            self._connected = False
            self._volume = 42
            self.track_change_callback = None
            self.playback_state_callback = None
            self.connection_change_callback = None

        def start(self) -> bool:
            self._connected = True
            return True

        def stop(self) -> None:
            self._connected = False

        @property
        def is_connected(self) -> bool:
            return self._connected

        def load_tracks(self, _uris: list[str]) -> bool:
            return True

        def load_playlist_file(self, _path: str) -> bool:
            return True

        def play(self) -> bool:
            return True

        def pause(self) -> bool:
            return True

        def stop_playback(self) -> bool:
            return True

        def next_track(self) -> bool:
            return True

        def previous_track(self) -> bool:
            return True

        def set_volume(self, volume: int) -> bool:
            self._volume = volume
            return True

        def get_volume(self) -> int:
            return self._volume

        def set_audio_device(self, _device: str) -> bool:
            return True

        def get_current_track(self):
            return None

        def get_playback_state(self) -> str:
            return "stopped"

        def get_time_position(self) -> int:
            return 0

        def on_track_change(self, callback) -> None:
            self.track_change_callback = callback

        def on_playback_state_change(self, callback) -> None:
            self.playback_state_callback = callback

        def on_connection_change(self, callback) -> None:
            self.connection_change_callback = callback

    monkeypatch.setattr("yoyopod.backends.music.rust_host.RustHostBackend", _FakeRustBackend)
    monkeypatch.setattr(
        "yoyopod.backends.music.rust_host.default_worker_path",
        lambda: "/bin/yoyopod-media-host",
    )

    integration = setup(app)

    assert integration.backend is app.music_backend
    assert captured["worker_supervisor"] is app.worker_supervisor
    assert captured["worker_path"] == "/bin/yoyopod-media-host"
    assert captured["scheduler"] is app.scheduler


def test_music_services_drive_focus_and_state() -> None:
    app = build_test_app()
    setup_focus(app)
    backend = FakeMusicBackend()
    library = FakeLibrary()
    setup(app, backend=backend, library=library, default_volume=70)

    assert app.services.call("music", "play", PlayCommand(track_uri="/music/a.mp3")) is True
    drain_all(app)
    assert backend.loaded_tracks == [["/music/a.mp3"]]
    assert app.states.get_value("focus.owner") == "music"
    assert app.states.get_value("music.state") == "playing"

    assert (
        app.services.call(
            "music",
            "load_playlist",
            LoadPlaylistCommand(playlist_uri="/music/set.m3u"),
        )
        is True
    )
    assert library.load_playlist_calls == ["/music/set.m3u"]

    assert (
        app.services.call(
            "music",
            "play_recent_track",
            PlayRecentTrackCommand(track_uri="/music/recent.mp3"),
        )
        is True
    )
    assert library.play_recent_track_calls == ["/music/recent.mp3"]

    assert app.services.call("music", "shuffle_all", ShuffleAllCommand()) is True
    assert library.shuffle_all_calls == 1

    assert app.services.call("music", "pause", PauseCommand()) is True
    drain_all(app)
    assert app.states.get_value("music.state") == "paused"
    assert app.states.get_value("focus.owner") == "music"

    assert app.services.call("music", "resume", ResumeCommand()) is True
    drain_all(app)
    assert app.states.get_value("music.state") == "playing"
    assert app.states.get_value("focus.owner") == "music"

    assert app.services.call("music", "set_volume", SetVolumeCommand(percent=120)) == 100
    assert app.states.get_value("music.volume_percent") == 100
    assert backend._volume == 100

    assert app.services.call("music", "next_track", NextTrackCommand()) is True
    assert app.services.call("music", "previous_track", PreviousTrackCommand()) is True
    assert app.services.call("music", "stop", StopCommand()) is True
    drain_all(app)
    assert app.states.get_value("music.state") == "idle"
    assert app.states.get_value("focus.owner") is None

    teardown(app)
    assert "music" not in app.integrations


def test_music_callbacks_update_track_and_availability_and_record_recents() -> None:
    app = build_test_app()
    setup_focus(app)
    backend = FakeMusicBackend()
    library = FakeLibrary()
    setup(app, backend=backend, library=library)

    track = Track(
        uri="/music/demo.mp3",
        name="Demo",
        artists=["Artist"],
        album="Album",
        length=5432,
        track_no=3,
    )
    backend.emit_track(track)
    backend.emit_connection_change(False, "lost")
    drain_all(app)

    stored_track = app.states.get_value("music.track")
    assert stored_track == track
    assert library.recorded_tracks == [track]
    assert app.states.get("music.track").attrs == {
        "title": "Demo",
        "artist": "Artist",
        "album": "Album",
        "duration_ms": 5432,
        "track_no": 3,
        "uri": "/music/demo.mp3",
    }
    assert app.states.get_value("music.backend_available") is False
    assert app.states.get("music.backend_available").attrs == {"reason": "lost"}


def test_music_focus_loss_auto_pauses_playing_music() -> None:
    app = build_test_app()
    setup_focus(app)
    backend = FakeMusicBackend()
    setup(app, backend=backend)

    app.services.call("music", "play", PlayCommand(track_uri="/music/alpha.mp3"))
    drain_all(app)

    app.bus.publish(AudioFocusLostEvent(owner="music", preempted_by="call"))
    drain_all(app)

    assert backend.commands[-1] == "pause"
    assert app.states.get_value("music.state") == "paused"


def test_music_services_reject_wrong_payload_types() -> None:
    app = build_test_app()
    setup_focus(app)
    setup(app, backend=FakeMusicBackend())

    try:
        app.services.call("music", "play", {"track_uri": "/music/a.mp3"})  # type: ignore[arg-type]
    except TypeError as exc:
        assert str(exc) == "music.play expects PlayCommand"
    else:
        raise AssertionError("music.play accepted an untyped payload")
