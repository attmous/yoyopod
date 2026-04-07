"""Tests for MusicBackend protocol and MockMusicBackend."""

from __future__ import annotations

from yoyopy.audio.music.backend import MockMusicBackend, MpvBackend, MusicBackend
from yoyopy.audio.music.models import MusicConfig, Track


def test_mock_backend_satisfies_protocol() -> None:
    backend: MusicBackend = MockMusicBackend()
    assert backend.start() is True
    assert backend.is_connected is True


def test_mock_backend_transport_controls() -> None:
    backend = MockMusicBackend()
    backend.start()
    assert backend.play() is True
    assert backend.pause() is True
    assert backend.stop_playback() is True
    assert backend.next_track() is True
    assert backend.previous_track() is True


def test_mock_backend_volume() -> None:
    backend = MockMusicBackend()
    backend.start()
    assert backend.set_volume(75) is True
    assert backend.get_volume() == 75


def test_mock_backend_audio_device() -> None:
    backend = MockMusicBackend()
    backend.start()
    assert backend.set_audio_device("alsa/hw:1,0") is True


def test_mock_backend_load_tracks() -> None:
    backend = MockMusicBackend()
    backend.start()
    assert backend.load_tracks(["/music/a.mp3", "/music/b.mp3"]) is True
    assert "load_tracks" in backend.commands[-1]


def test_mock_backend_load_playlist_file() -> None:
    backend = MockMusicBackend()
    backend.start()
    assert backend.load_playlist_file("/music/chill.m3u") is True


def test_mock_backend_playback_state() -> None:
    backend = MockMusicBackend()
    backend.start()
    assert backend.get_playback_state() == "stopped"
    backend.play()
    assert backend.get_playback_state() == "playing"
    backend.pause()
    assert backend.get_playback_state() == "paused"


def test_mock_backend_track_change_callback() -> None:
    backend = MockMusicBackend()
    received: list[Track | None] = []
    backend.on_track_change(received.append)
    track = Track(uri="/music/a.mp3", name="A", artists=["X"])
    backend.emit_track_change(track)
    assert received == [track]


def test_mock_backend_playback_state_callback() -> None:
    backend = MockMusicBackend()
    received: list[str] = []
    backend.on_playback_state_change(received.append)
    backend.emit_playback_state_change("playing")
    assert received == ["playing"]


def test_mock_backend_connection_callback() -> None:
    backend = MockMusicBackend()
    received: list[tuple[bool, str]] = []
    backend.on_connection_change(lambda ok, reason: received.append((ok, reason)))
    backend.emit_connection_change(True, "connected")
    assert received == [(True, "connected")]


def test_mock_backend_stop() -> None:
    backend = MockMusicBackend()
    backend.start()
    backend.stop()
    assert backend.is_connected is False


def test_mock_backend_get_current_track() -> None:
    backend = MockMusicBackend()
    assert backend.get_current_track() is None
    track = Track(uri="/music/a.mp3", name="A", artists=["X"])
    backend.current_track = track
    assert backend.get_current_track() == track


def test_mock_backend_get_time_position() -> None:
    backend = MockMusicBackend()
    assert backend.get_time_position() == 0
    backend.time_position = 5000
    assert backend.get_time_position() == 5000


def test_mpv_backend_waits_for_delayed_ipc_ready(monkeypatch) -> None:
    class FakeProcess:
        def spawn(self) -> bool:
            return True

        def kill(self) -> None:
            return None

        def is_alive(self) -> bool:
            return True

    class FakeIpc:
        def __init__(self) -> None:
            self.connect_calls = 0
            self.connected = False
            self.observed: list[tuple[str, int]] = []

        def connect(self) -> bool:
            self.connect_calls += 1
            self.connected = self.connect_calls >= 13
            return self.connected

        def on_event(self, callback) -> None:
            self._callback = callback

        def start_reader(self) -> None:
            return None

        def observe_property(self, name: str, observe_id: int) -> None:
            self.observed.append((name, observe_id))

        def send_command(self, args: list[object]) -> dict[str, object]:
            return {"error": "success"}

        def disconnect(self) -> None:
            self.connected = False

    backend = MpvBackend(MusicConfig())
    fake_ipc = FakeIpc()
    backend._process = FakeProcess()
    backend._ipc = fake_ipc
    monkeypatch.setattr("yoyopy.audio.music.backend.time.sleep", lambda _: None)

    assert backend.start() is True
    assert fake_ipc.connect_calls == 13
    assert backend.is_connected is True


def test_mpv_backend_builds_track_from_property_events() -> None:
    backend = MpvBackend(MusicConfig())

    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "path",
            "data": "/music/alpha.ogg",
        }
    )
    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "metadata",
            "data": {
                "title": "Alpha",
                "artist": "Artist",
                "album": "Sampler",
            },
        }
    )
    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "duration",
            "data": 12.5,
        }
    )

    track = backend.get_current_track()

    assert track is not None
    assert track.uri == "/music/alpha.ogg"
    assert track.name == "Alpha"
    assert track.artists == ["Artist"]
    assert track.album == "Sampler"
    assert track.length == 12500


def test_mpv_backend_get_current_track_refreshes_snapshot_when_cache_empty() -> None:
    class FakeIpc:
        connected = True

        def __init__(self) -> None:
            self.responses = {
                "path": "/music/beta.ogg",
                "metadata": {"artist": "Composer"},
                "duration": 9.0,
                "media-title": "Beta",
            }

        def send_command(self, args: list[object]) -> dict[str, object]:
            return {"error": "success", "data": self.responses[str(args[1])]}

        def disconnect(self) -> None:
            return None

    class FakeProcess:
        def is_alive(self) -> bool:
            return True

        def kill(self) -> None:
            return None

    backend = MpvBackend(MusicConfig())
    backend._connected = True
    backend._ipc = FakeIpc()
    backend._process = FakeProcess()

    track = backend.get_current_track()

    assert track is not None
    assert track.name == "Beta"
    assert track.artists == ["Composer"]
    assert track.length == 9000


def test_mpv_backend_registers_mpv_event_handler_only_once_across_restarts() -> None:
    class FakeIpc:
        def __init__(self) -> None:
            self.connected = False
            self.callbacks: list[object] = []

        def connect(self) -> bool:
            self.connected = True
            return True

        def on_event(self, callback) -> None:
            self.callbacks.append(callback)

        def start_reader(self) -> None:
            return None

        def observe_property(self, name: str, observe_id: int) -> None:
            return None

        def send_command(self, args: list[object]) -> dict[str, object]:
            return {"error": "success"}

        def disconnect(self) -> None:
            self.connected = False

    class FakeProcess:
        def __init__(self) -> None:
            self.alive = False

        def spawn(self) -> bool:
            self.alive = True
            return True

        def kill(self) -> None:
            self.alive = False

        def is_alive(self) -> bool:
            return self.alive

    backend = MpvBackend(MusicConfig())
    fake_ipc = FakeIpc()
    backend._ipc = fake_ipc
    backend._process = FakeProcess()

    assert backend.start() is True
    backend.stop()
    assert backend.start() is True

    assert len(fake_ipc.callbacks) == 1
