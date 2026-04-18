"""Tests for MusicBackend protocol and MockMusicBackend."""

from __future__ import annotations

from yoyopod.audio.music.backend import MockMusicBackend, MpvBackend, MusicBackend
from yoyopod.audio.music.models import MusicConfig, Track


def _monotonic_stub(*values: float):
    remaining = list(values)
    fallback = values[-1] if values else 0.0

    def fake_monotonic() -> float:
        if remaining:
            return remaining.pop(0)
        return fallback

    return fake_monotonic


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
    monkeypatch.setattr("yoyopod.audio.music.backend.time.sleep", lambda _: None)

    assert backend.start() is True
    assert fake_ipc.connect_calls == 13
    assert ("time-pos", 7) in fake_ipc.observed
    assert backend.is_connected is True


def test_mpv_backend_retries_spawn_when_early_launches_never_open_ipc(
    monkeypatch,
) -> None:
    class FakeProcess:
        def __init__(self) -> None:
            self.spawn_calls = 0
            self.kill_calls = 0

        def spawn(self) -> bool:
            self.spawn_calls += 1
            return True

        def kill(self) -> None:
            self.kill_calls += 1

        def is_alive(self) -> bool:
            return True

    class FakeIpc:
        def __init__(self, process: FakeProcess) -> None:
            self._process = process
            self.connected = False

        def connect(self) -> bool:
            self.connected = self._process.spawn_calls >= 4
            return self.connected

        def on_event(self, callback) -> None:
            self._callback = callback

        def start_reader(self) -> None:
            return None

        def observe_property(self, name: str, observe_id: int) -> None:
            return None

        def send_command(self, args: list[object]) -> dict[str, object]:
            return {"error": "success"}

        def disconnect(self) -> None:
            self.connected = False

    backend = MpvBackend(MusicConfig())
    fake_process = FakeProcess()
    backend._process = fake_process
    backend._ipc = FakeIpc(fake_process)
    monkeypatch.setattr("yoyopod.audio.music.backend.time.sleep", lambda _: None)

    assert backend.start() is True
    assert fake_process.spawn_calls == 4
    assert fake_process.kill_calls == 3
    assert backend.is_connected is True


def test_mpv_backend_primes_track_cache_from_ipc_before_property_events(
    monkeypatch,
) -> None:
    class FakeProcess:
        def spawn(self) -> bool:
            return True

        def kill(self) -> None:
            return None

        def is_alive(self) -> bool:
            return True

    class FakeIpc:
        def __init__(self) -> None:
            self.connected = False
            self.responses = {
                "path": "/music/primed.ogg",
                "metadata": {"artist": "Composer"},
                "duration": 9.0,
                "media-title": "Primed",
            }

        def connect(self) -> bool:
            self.connected = True
            return True

        def on_event(self, callback) -> None:
            self._callback = callback

        def start_reader(self) -> None:
            return None

        def observe_property(self, name: str, observe_id: int) -> None:
            return None

        def send_command(self, args: list[object]) -> dict[str, object]:
            if args[0] == "get_property":
                return {"error": "success", "data": self.responses.get(str(args[1]))}
            return {"error": "success"}

        def disconnect(self) -> None:
            self.connected = False

    backend = MpvBackend(MusicConfig())
    backend._process = FakeProcess()
    backend._ipc = FakeIpc()
    monkeypatch.setattr("yoyopod.audio.music.backend.time.sleep", lambda _: None)

    assert backend.start() is True

    track = backend.get_current_track()

    assert track is not None
    assert track.name == "Primed"
    assert track.artists == ["Composer"]
    assert track.length == 9000


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


def test_mpv_backend_ignores_stale_metadata_after_stop_end_file() -> None:
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
            },
        }
    )

    assert backend.get_current_track() is not None

    backend._handle_mpv_event({"event": "end-file", "reason": "stop"})
    assert backend.get_current_track() is None

    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "metadata",
            "data": {
                "title": "Stale Alpha",
                "artist": "Artist",
            },
        }
    )

    assert backend.get_playback_state() == "stopped"
    assert backend.get_current_track() is None


def test_mpv_backend_get_current_track_uses_observed_cache_without_sync_round_trip(
) -> None:
    class FakeIpc:
        connected = True

        def send_command(self, args: list[object]) -> dict[str, object]:
            raise AssertionError(f"unexpected synchronous IPC read: {args}")

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

    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "path",
            "data": "/music/beta.ogg",
        }
    )
    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "metadata",
            "data": {"artist": "Composer"},
        }
    )
    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "duration",
            "data": 9.0,
        }
    )
    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "media-title",
            "data": "Beta",
        }
    )

    track = backend.get_current_track()

    assert track is not None
    assert track.name == "Beta"
    assert track.artists == ["Composer"]
    assert track.length == 9000


def test_mpv_backend_get_current_track_returns_none_without_observed_cache() -> None:
    class FakeIpc:
        connected = True

        def send_command(self, args: list[object]) -> dict[str, object]:
            raise AssertionError(f"unexpected synchronous IPC read: {args}")

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

    assert backend.get_current_track() is None


def test_mpv_backend_get_current_track_tolerates_non_numeric_duration_in_observed_cache(
) -> None:
    class FakeIpc:
        connected = True

        def send_command(self, args: list[object]) -> dict[str, object]:
            raise AssertionError(f"unexpected synchronous IPC read: {args}")

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

    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "path",
            "data": "/music/beta.ogg",
        }
    )
    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "metadata",
            "data": {"artist": "Composer"},
        }
    )
    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "duration",
            "data": "N/A",
        }
    )
    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "media-title",
            "data": "Beta",
        }
    )

    track = backend.get_current_track()

    assert track is not None
    assert track.name == "Beta"
    assert track.artists == ["Composer"]
    assert track.length == 0


def test_mpv_backend_get_time_position_uses_observed_cache(monkeypatch) -> None:
    class FakeIpc:
        connected = True

        def send_command(self, args: list[object]) -> dict[str, object]:
            raise AssertionError(f"unexpected synchronous IPC read: {args}")

    class FakeProcess:
        def is_alive(self) -> bool:
            return True

    backend = MpvBackend(MusicConfig())
    backend._connected = True
    backend._ipc = FakeIpc()
    backend._process = FakeProcess()
    monkeypatch.setattr(
        "yoyopod.audio.music.backend.time.monotonic",
        _monotonic_stub(100.0),
    )

    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "time-pos",
            "data": 12.5,
        }
    )

    assert backend.get_time_position() == 12500


def test_mpv_backend_get_time_position_throttles_small_observed_updates(
    monkeypatch,
) -> None:
    class FakeIpc:
        connected = True

    class FakeProcess:
        def is_alive(self) -> bool:
            return True

    monkeypatch.setattr(
        "yoyopod.audio.music.backend.time.monotonic",
        _monotonic_stub(100.0, 100.1, 100.2),
    )

    backend = MpvBackend(MusicConfig())
    backend._connected = True
    backend._ipc = FakeIpc()
    backend._process = FakeProcess()
    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "time-pos",
            "data": 12.0,
        }
    )
    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "time-pos",
            "data": 12.1,
        }
    )
    assert backend.get_time_position() == 12000

    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "time-pos",
            "data": 14.0,
        }
    )
    assert backend.get_time_position() == 14000


def test_mpv_backend_get_time_position_returns_zero_for_non_numeric_observed_value(
    monkeypatch,
) -> None:
    class FakeIpc:
        connected = True

    class FakeProcess:
        def is_alive(self) -> bool:
            return True

    monkeypatch.setattr(
        "yoyopod.audio.music.backend.time.monotonic",
        _monotonic_stub(100.0),
    )

    backend = MpvBackend(MusicConfig())
    backend._connected = True
    backend._ipc = FakeIpc()
    backend._process = FakeProcess()
    backend._handle_mpv_event(
        {
            "event": "property-change",
            "name": "time-pos",
            "data": "N/A",
        }
    )

    assert backend.get_time_position() == 0


def test_mpv_backend_get_time_position_returns_zero_when_disconnected() -> None:
    class FakeIpc:
        connected = False

    class FakeProcess:
        def is_alive(self) -> bool:
            return True

    backend = MpvBackend(MusicConfig())
    backend._connected = True
    backend._ipc = FakeIpc()
    backend._process = FakeProcess()
    backend._cached_time_position_ms = 12500

    assert backend.get_time_position() == 0


def test_mpv_backend_get_time_position_returns_zero_when_cache_is_stale(
    monkeypatch,
) -> None:
    class FakeIpc:
        connected = True

    class FakeProcess:
        def is_alive(self) -> bool:
            return True

    backend = MpvBackend(MusicConfig())
    backend._connected = True
    backend._ipc = FakeIpc()
    backend._process = FakeProcess()
    backend._playback_state = "playing"
    backend._cached_time_position_ms = 12500
    backend._last_time_position_cache_update = 100.0
    monkeypatch.setattr(
        "yoyopod.audio.music.backend.time.monotonic",
        _monotonic_stub(100.0 + backend._TIME_POSITION_STALE_SECONDS + 1.0),
    )

    assert backend.get_time_position() == 0


def test_mpv_backend_get_time_position_keeps_cached_value_when_paused_and_stale(
    monkeypatch,
) -> None:
    class FakeIpc:
        connected = True

    class FakeProcess:
        def is_alive(self) -> bool:
            return True

    backend = MpvBackend(MusicConfig())
    backend._connected = True
    backend._ipc = FakeIpc()
    backend._process = FakeProcess()
    backend._playback_state = "paused"
    backend._cached_time_position_ms = 12500
    backend._last_time_position_cache_update = 100.0
    monkeypatch.setattr(
        "yoyopod.audio.music.backend.time.monotonic",
        _monotonic_stub(100.0 + backend._TIME_POSITION_STALE_SECONDS + 1.0),
    )

    assert backend.get_time_position() == 12500


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
