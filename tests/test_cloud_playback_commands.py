from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from yoyopod.integrations.cloud.manager import CloudManager


class _FakeMqttClient:
    def __init__(self) -> None:
        self.is_connected = True
        self.acks: list[dict[str, object]] = []
        self.events: list[dict[str, object]] = []

    def publish_ack(self, **payload) -> bool:
        self.acks.append(payload)
        return True

    def publish_playback_event(self, payload: dict[str, object]) -> bool:
        self.events.append(payload)
        return True

    def publish_event(self, event_type: str, payload: dict[str, object]) -> bool:
        self.events.append({"type": event_type, "payload": payload})
        return True


class _FakeMusicBackend:
    def __init__(self) -> None:
        self.is_connected = True
        self.loaded: list[list[str]] = []
        self.playback_state_callbacks = []
        self.track_callbacks = []
        self.position_ms = 0
        self.stop_calls = 0
        self.pause_calls = 0
        self.play_calls = 0
        self.prepare_calls: list[dict[str, object]] = []
        self.import_calls: list[dict[str, object]] = []

    def on_track_change(self, callback) -> None:
        self.track_callbacks.append(callback)

    def on_playback_state_change(self, callback) -> None:
        self.playback_state_callbacks.append(callback)

    def load_tracks(self, uris: list[str]) -> bool:
        self.loaded.append(uris)
        return True

    def stop_playback(self) -> bool:
        self.stop_calls += 1
        return True

    def pause(self) -> bool:
        self.pause_calls += 1
        return True

    def play(self) -> bool:
        self.play_calls += 1
        return True

    def get_time_position(self) -> int:
        return self.position_ms

    def prepare_remote_playback_asset(
        self,
        *,
        track_id: str,
        media_url: str,
        checksum_sha256: str | None = None,
        extension: str = ".mp3",
        timeout_seconds: float | None = None,
    ):
        self.prepare_calls.append(
            {
                "track_id": track_id,
                "media_url": media_url,
                "checksum_sha256": checksum_sha256,
                "extension": extension,
                "timeout_seconds": timeout_seconds,
            }
        )
        return SimpleNamespace(path="/tmp/rust-cached-track.mp3", cache_hit=False)

    def import_remote_media_asset(
        self,
        *,
        track_id: str,
        cached_path: str,
        title: str | None = None,
        filename: str | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        self.import_calls.append(
            {
                "track_id": track_id,
                "cached_path": cached_path,
                "title": title,
                "filename": filename,
                "timeout_seconds": timeout_seconds,
            }
        )
        display_stem = _safe_media_stem(title or filename or track_id, default_stem=track_id)
        unique_stem = _safe_media_stem(track_id, default_stem="track")
        safe_name = (
            f"{display_stem}.mp3"
            if display_stem == unique_stem
            else f"{display_stem}-{unique_stem}.mp3"
        )
        return f"/music/dashboard_uploads/{safe_name}"

    def emit_playback(self, state: str) -> None:
        for callback in self.playback_state_callbacks:
            callback(state)


class _MissingRustMediaBackend(_FakeMusicBackend):
    def prepare_remote_playback_asset(self, *args, **kwargs):
        raise AttributeError

    def import_remote_media_asset(self, *args, **kwargs):
        raise AttributeError


class _FakeConfigManager:
    def __init__(self) -> None:
        backend = SimpleNamespace(
            api_base_url="https://backend.example.test",
            auth_path="/v1/auth/device",
            refresh_path="/v1/auth/device/refresh",
            config_path_template="/v1/devices/{device_id}/config",
            contacts_bootstrap_path_template="/v1/devices/{device_id}/contacts/bootstrap",
            timeout_seconds=3.0,
            battery_report_interval_seconds=60,
            mqtt_broker_host="broker.example.test",
            mqtt_broker_port=1883,
            mqtt_username="",
            mqtt_password="",
            mqtt_use_tls=False,
            mqtt_transport="tcp",
        )
        self._cloud = SimpleNamespace(backend=backend)
        self.cloud_secrets_error = ""

    def get_cloud_settings(self):
        return self._cloud

    def get_cloud_device_id(self) -> str:
        return "YYP-DEV-0001"

    def get_cloud_device_secret(self) -> str:
        return "secret"

    def get_media_settings(self):
        return SimpleNamespace(
            music=SimpleNamespace(
                remote_cache_dir="data/media/remote_cache",
                remote_cache_max_bytes=64 * 1024 * 1024,
            )
        )

    def resolve_runtime_path(self, value: str) -> str:
        return value


class _FakeApp:
    def __init__(self, music_backend: _FakeMusicBackend) -> None:
        self.music_backend = music_backend
        self.context = None

    def _queue_main_thread_callback(self, callback) -> None:
        callback()


def test_play_track_command_acks_and_publishes_buffering_then_playing() -> None:
    music_backend = _FakeMusicBackend()
    manager = CloudManager(
        app=_FakeApp(music_backend),
        config_manager=_FakeConfigManager(),
        client=SimpleNamespace(),
    )
    manager._mqtt = _FakeMqttClient()
    manager._bind_playback_callbacks()
    manager._start_worker = lambda *, name, work: work()  # type: ignore[method-assign]
    manager._start_media_worker = lambda *, name, work: work()  # type: ignore[method-assign]

    manager._apply_mqtt_command(
        {
            "messageType": "playback.command",
            "commandId": "cmd-1",
            "command": "play_track",
            "payload": {
                "trackId": "track-1",
                "mediaUrl": "https://media.example.test/file.mp3",
                "title": "Song",
                "artist": "Artist",
                "durationMs": 120000,
            },
        }
    )

    assert music_backend.prepare_calls == [
        {
            "track_id": "track-1",
            "media_url": "https://media.example.test/file.mp3",
            "checksum_sha256": None,
            "extension": ".mp3",
            "timeout_seconds": None,
        }
    ]
    assert music_backend.loaded == [["/tmp/rust-cached-track.mp3"]]
    assert manager._mqtt.acks[0]["command_id"] == "cmd-1"
    assert manager._mqtt.acks[0]["ok"] is True
    assert manager._mqtt.events[0]["eventType"] == "buffering"
    assert manager._remote_playback_session["cached_path"] == "/tmp/rust-cached-track.mp3"

    music_backend.position_ms = 500
    music_backend.emit_playback("playing")

    assert manager._mqtt.events[-1]["eventType"] == "playing"
    assert manager._mqtt.events[-1]["payload"]["positionMs"] == 500


def test_stop_command_acks_and_emits_completed_when_near_end() -> None:
    music_backend = _FakeMusicBackend()
    manager = CloudManager(
        app=_FakeApp(music_backend),
        config_manager=_FakeConfigManager(),
        client=SimpleNamespace(),
    )
    manager._mqtt = _FakeMqttClient()
    manager._bind_playback_callbacks()

    manager._remote_playback_session = {
        "command_id": "cmd-1",
        "track_id": "track-1",
        "duration_ms": 10000,
        "media_url": "https://media.example.test/file.mp3",
    }

    manager._apply_mqtt_command(
        {
            "commandId": "cmd-2",
            "command": "stop",
            "payload": {"trackId": "track-1"},
        }
    )

    assert music_backend.stop_calls == 1
    assert manager._mqtt.acks[-1]["command_id"] == "cmd-2"

    music_backend.position_ms = 9800
    music_backend.emit_playback("stopped")

    assert manager._mqtt.events[-1]["commandId"] == "cmd-1"
    assert manager._mqtt.events[-1]["eventType"] == "completed"


def test_invalid_play_command_nacks() -> None:
    music_backend = _FakeMusicBackend()
    manager = CloudManager(
        app=_FakeApp(music_backend),
        config_manager=_FakeConfigManager(),
        client=SimpleNamespace(),
    )
    manager._mqtt = _FakeMqttClient()
    manager._bind_playback_callbacks()

    manager._apply_mqtt_command(
        {
            "commandId": "cmd-3",
            "command": "play_track",
            "payload": {"trackId": "track-1"},
        }
    )

    assert manager._mqtt.acks == [
        {
            "command_id": "cmd-3",
            "ok": False,
            "reason": "invalid_command",
        }
    ]


def test_stopped_callback_during_pending_remote_fetch_does_not_clear_session() -> None:
    music_backend = _FakeMusicBackend()
    manager = CloudManager(
        app=_FakeApp(music_backend),
        config_manager=_FakeConfigManager(),
        client=SimpleNamespace(),
    )
    manager._mqtt = _FakeMqttClient()
    manager._bind_playback_callbacks()

    queued_work: list[object] = []
    manager._start_worker = lambda *, name, work: queued_work.append(work)  # type: ignore[method-assign]
    manager._start_media_worker = lambda *, name, work: queued_work.append(work)  # type: ignore[method-assign]

    manager._apply_mqtt_command(
        {
            "messageType": "playback.command",
            "commandId": "cmd-4",
            "command": "play_track",
            "payload": {
                "trackId": "track-4",
                "mediaUrl": "https://media.example.test/file.mp3",
                "title": "Song",
            },
        }
    )

    assert manager._remote_playback_session is not None
    assert manager._remote_playback_session["activation_pending"] is True

    music_backend.emit_playback("stopped")

    assert manager._remote_playback_session is not None
    assert music_backend.loaded == []
    assert len(queued_work) == 1


def test_stop_during_buffering_prevents_late_load_after_fetch_completes() -> None:
    music_backend = _FakeMusicBackend()
    manager = CloudManager(
        app=_FakeApp(music_backend),
        config_manager=_FakeConfigManager(),
        client=SimpleNamespace(),
    )
    manager._mqtt = _FakeMqttClient()
    manager._bind_playback_callbacks()

    queued_work: list[object] = []
    manager._start_worker = lambda *, name, work: queued_work.append(work)  # type: ignore[method-assign]
    manager._start_media_worker = lambda *, name, work: queued_work.append(work)  # type: ignore[method-assign]

    manager._apply_mqtt_command(
        {
            "commandId": "cmd-5",
            "command": "play_track",
            "payload": {
                "trackId": "track-5",
                "mediaUrl": "https://media.example.test/file.mp3",
            },
        }
    )
    manager._apply_mqtt_command(
        {
            "commandId": "cmd-6",
            "command": "stop",
            "payload": {"trackId": "track-5"},
        }
    )

    assert manager._remote_playback_session is not None
    assert manager._remote_playback_session["stop_requested"] is True

    queued_work[0]()

    assert music_backend.loaded == []
    assert manager._remote_playback_session is None
    assert manager._mqtt.events[-1]["eventType"] == "stopped"


def test_store_media_command_acks_and_publishes_imported_event() -> None:
    music_backend = _FakeMusicBackend()
    manager = CloudManager(
        app=_FakeApp(music_backend),
        config_manager=_FakeConfigManager(),
        client=SimpleNamespace(),
    )
    manager._mqtt = _FakeMqttClient()
    manager._start_worker = lambda *, name, work: work()  # type: ignore[method-assign]
    manager._start_media_worker = lambda *, name, work: work()  # type: ignore[method-assign]

    manager._apply_mqtt_command(
        {
            "commandId": "cmd-7",
            "command": "store_media",
            "payload": {
                "trackId": "track-7",
                "mediaUrl": "https://media.example.test/file.mp3",
                "title": "Track Seven",
            },
        }
    )

    assert manager._mqtt.acks[-1] == {
        "command_id": "cmd-7",
        "ok": True,
        "payload": {"command": "store_media"},
    }
    assert music_backend.import_calls == [
        {
            "track_id": "track-7",
            "cached_path": "/tmp/rust-cached-track.mp3",
            "title": "Track Seven",
            "filename": None,
            "timeout_seconds": None,
        }
    ]
    assert manager._mqtt.events[-1]["type"] == "media_library"
    assert manager._mqtt.events[-1]["payload"]["eventType"] == "imported"
    imported_path = manager._mqtt.events[-1]["payload"]["payload"]["path"]
    assert imported_path.endswith("Track-Seven-track-7.mp3")


def test_store_media_sanitizes_fallback_track_id_in_target_filename() -> None:
    music_backend = _FakeMusicBackend()
    manager = CloudManager(
        app=_FakeApp(music_backend),
        config_manager=_FakeConfigManager(),
        client=SimpleNamespace(),
    )
    manager._mqtt = _FakeMqttClient()
    manager._start_worker = lambda *, name, work: work()  # type: ignore[method-assign]
    manager._start_media_worker = lambda *, name, work: work()  # type: ignore[method-assign]

    manager._apply_mqtt_command(
        {
            "commandId": "cmd-8",
            "command": "store_media",
            "payload": {
                "trackId": "///",
                "mediaUrl": "https://media.example.test/file.mp3",
            },
        }
    )

    imported_path = manager._mqtt.events[-1]["payload"]["payload"]["path"]
    assert imported_path.startswith("/music/dashboard_uploads/")
    assert imported_path.endswith("track.mp3")


def test_stopped_after_asset_load_is_not_dropped_when_activation_pending() -> None:
    music_backend = _FakeMusicBackend()
    manager = CloudManager(
        app=_FakeApp(music_backend),
        config_manager=_FakeConfigManager(),
        client=SimpleNamespace(),
    )
    manager._mqtt = _FakeMqttClient()
    manager._bind_playback_callbacks()
    manager._start_worker = lambda *, name, work: work()  # type: ignore[method-assign]
    manager._start_media_worker = lambda *, name, work: work()  # type: ignore[method-assign]

    manager._apply_mqtt_command(
        {
            "commandId": "cmd-9",
            "command": "play_track",
            "payload": {
                "trackId": "track-9",
                "mediaUrl": "https://media.example.test/file.mp3",
            },
        }
    )

    assert manager._remote_playback_session is not None
    assert manager._remote_playback_session["activation_pending"] is True
    assert manager._remote_playback_session["cached_path"] == "/tmp/rust-cached-track.mp3"

    music_backend.emit_playback("stopped")

    assert manager._remote_playback_session is None
    assert manager._mqtt.events[-1]["eventType"] == "stopped"


def test_store_media_keeps_distinct_files_for_same_title() -> None:
    music_backend = _FakeMusicBackend()
    manager = CloudManager(
        app=_FakeApp(music_backend),
        config_manager=_FakeConfigManager(),
        client=SimpleNamespace(),
    )
    manager._mqtt = _FakeMqttClient()
    manager._start_worker = lambda *, name, work: work()  # type: ignore[method-assign]
    manager._start_media_worker = lambda *, name, work: work()  # type: ignore[method-assign]

    for command_id, track_id in (("cmd-10", "track-10"), ("cmd-11", "track-11")):
        manager._apply_mqtt_command(
            {
                "commandId": command_id,
                "command": "store_media",
                "payload": {
                    "trackId": track_id,
                    "mediaUrl": "https://media.example.test/file.mp3",
                    "title": "Shared Name",
                },
            }
        )

    imported_paths = [
        event["payload"]["payload"]["path"]
        for event in manager._mqtt.events
        if event.get("type") == "media_library"
    ]
    assert len(imported_paths) == 2
    assert imported_paths[0] != imported_paths[1]
    assert imported_paths[0].endswith("Shared-Name-track-10.mp3")
    assert imported_paths[1].endswith("Shared-Name-track-11.mp3")


def test_play_track_command_uses_rust_media_host_asset_prepare() -> None:
    music_backend = _FakeMusicBackend()
    manager = CloudManager(
        app=_FakeApp(music_backend),
        config_manager=_FakeConfigManager(),
        client=SimpleNamespace(),
    )
    manager._mqtt = _FakeMqttClient()
    manager._bind_playback_callbacks()
    manager._start_worker = lambda *, name, work: work()  # type: ignore[method-assign]
    manager._start_media_worker = lambda *, name, work: work()  # type: ignore[method-assign]

    manager._apply_mqtt_command(
        {
            "messageType": "playback.command",
            "commandId": "cmd-rust-1",
            "command": "play_track",
            "payload": {
                "trackId": "track-rust-1",
                "mediaUrl": "https://media.example.test/file.mp3",
                "checksumSha256": "abc123",
            },
        }
    )

    assert music_backend.prepare_calls == [
        {
            "track_id": "track-rust-1",
            "media_url": "https://media.example.test/file.mp3",
            "checksum_sha256": "abc123",
            "extension": ".mp3",
            "timeout_seconds": None,
        }
    ]
    assert music_backend.loaded == [["/tmp/rust-cached-track.mp3"]]


def test_store_media_command_uses_rust_media_host_import() -> None:
    music_backend = _FakeMusicBackend()
    manager = CloudManager(
        app=_FakeApp(music_backend),
        config_manager=_FakeConfigManager(),
        client=SimpleNamespace(),
    )
    manager._mqtt = _FakeMqttClient()
    manager._start_worker = lambda *, name, work: work()  # type: ignore[method-assign]
    manager._start_media_worker = lambda *, name, work: work()  # type: ignore[method-assign]

    manager._apply_mqtt_command(
        {
            "commandId": "cmd-rust-2",
            "command": "store_media",
            "payload": {
                "trackId": "track-7",
                "mediaUrl": "https://media.example.test/file.mp3",
                "title": "Track Seven",
                "filename": "track-seven.mp3",
            },
        }
    )

    assert music_backend.prepare_calls == [
        {
            "track_id": "track-7",
            "media_url": "https://media.example.test/file.mp3",
            "checksum_sha256": None,
            "extension": ".mp3",
            "timeout_seconds": None,
        }
    ]
    assert music_backend.import_calls == [
        {
            "track_id": "track-7",
            "cached_path": "/tmp/rust-cached-track.mp3",
            "title": "Track Seven",
            "filename": "track-seven.mp3",
            "timeout_seconds": None,
        }
    ]
    assert manager._mqtt.events[-1]["payload"]["payload"]["path"] == (
        "/music/dashboard_uploads/Track-Seven-track-7.mp3"
    )


def test_play_track_command_fails_without_rust_media_host_remote_prepare() -> None:
    music_backend = SimpleNamespace(
        is_connected=True,
        loaded=[],
        playback_state_callbacks=[],
        track_callbacks=[],
        position_ms=0,
        stop_calls=0,
        pause_calls=0,
        play_calls=0,
        on_track_change=lambda callback: None,
        on_playback_state_change=lambda callback: None,
        load_tracks=lambda uris: True,
        stop_playback=lambda: True,
        pause=lambda: True,
        play=lambda: True,
        get_time_position=lambda: 0,
    )
    manager = CloudManager(
        app=_FakeApp(music_backend),  # type: ignore[arg-type]
        config_manager=_FakeConfigManager(),
        client=SimpleNamespace(),
    )
    manager._mqtt = _FakeMqttClient()
    manager._bind_playback_callbacks()
    manager._start_worker = lambda *, name, work: work()  # type: ignore[method-assign]
    manager._start_media_worker = lambda *, name, work: work()  # type: ignore[method-assign]

    manager._apply_mqtt_command(
        {
            "messageType": "playback.command",
            "commandId": "cmd-fail-1",
            "command": "play_track",
            "payload": {
                "trackId": "track-fail-1",
                "mediaUrl": "https://media.example.test/file.mp3",
            },
        }
    )

    assert manager._mqtt.events[-1]["eventType"] == "failed"
    assert manager._mqtt.events[-1]["payload"]["reason"] == "media_fetch_failed"


def _safe_media_stem(value: str, *, default_stem: str) -> str:
    stem = Path(value).stem if value else default_stem
    normalized = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in stem)
    normalized = normalized.strip(".-_")
    if normalized:
        return normalized
    fallback = "".join(
        char if char.isalnum() or char in {"-", "_"} else "-" for char in default_stem
    ).strip(".-_")
    return fallback or "track"
