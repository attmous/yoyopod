from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from yoyopod.core.events import WorkerMessageReceivedEvent
from yoyopod.integrations.call import (
    AnswerCommand,
    StartVoiceNoteRecordingCommand,
    StopVoiceNoteRecordingCommand,
)
from yoyopod.integrations.music import LoadPlaylistCommand, PlayRecentTrackCommand
from yoyopod.ui.rust_host.facade import RustUiFacade


class _Supervisor:
    def __init__(
        self,
        *,
        messages: list[SimpleNamespace] | None = None,
        start_result: bool = True,
    ) -> None:
        self.sent: list[tuple[str, str, dict[str, Any] | None, str | None]] = []
        self.registered: list[tuple[str, object]] = []
        self.started: list[str] = []
        self.drain_calls: list[str] = []
        self.stopped: list[str] = []
        self._messages = list(messages or [])
        self._start_result = start_result

    def register(self, domain: str, config: object) -> None:
        self.registered.append((domain, config))

    def start(self, domain: str) -> bool:
        self.started.append(domain)
        return self._start_result

    def drain_worker_messages(self, domain: str) -> list[SimpleNamespace]:
        self.drain_calls.append(domain)
        messages = self._messages
        self._messages = []
        return messages

    def snapshot(self) -> dict[str, dict[str, object]]:
        return {"ui": {"running": True}}

    def stop(self, domain: str, *, grace_seconds: float = 1.0) -> None:
        self.stopped.append(domain)

    def send_command(
        self,
        domain: str,
        *,
        type: str,
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> bool:
        self.sent.append((domain, type, payload, request_id))
        return True


class _Services:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []

    def call(self, domain: str, service: str, data: Any = None) -> None:
        self.calls.append((domain, service, data))


def test_facade_starts_ui_host_worker() -> None:
    supervisor = _Supervisor(messages=[SimpleNamespace(kind="event", type="ui.ready", payload={})])
    app = SimpleNamespace(worker_supervisor=supervisor)
    facade = RustUiFacade(app, worker_domain="ui")

    assert facade.start_worker("device/ui/build/yoyopod-ui-host", hardware="whisplay")

    assert supervisor.started == ["ui"]
    assert supervisor.drain_calls == ["ui"]
    domain, config = supervisor.registered[0]
    assert domain == "ui"
    assert getattr(config, "argv") == [
        "device/ui/build/yoyopod-ui-host",
        "--hardware",
        "whisplay",
    ]


def test_facade_rejects_worker_start_without_ready_event() -> None:
    supervisor = _Supervisor()
    app = SimpleNamespace(worker_supervisor=supervisor)
    facade = RustUiFacade(app, worker_domain="ui")

    assert not facade.start_worker(
        "device/ui/build/yoyopod-ui-host",
        ready_timeout_seconds=0.0,
        ready_poll_interval_seconds=0.0,
    )

    assert supervisor.started == ["ui"]
    assert supervisor.stopped == ["ui"]


def test_facade_rejects_worker_startup_error_before_ready() -> None:
    supervisor = _Supervisor(
        messages=[
            SimpleNamespace(
                kind="error",
                type="display_open_failed",
                payload={"message": "no framebuffer"},
            )
        ]
    )
    app = SimpleNamespace(worker_supervisor=supervisor)
    facade = RustUiFacade(app, worker_domain="ui")

    assert not facade.start_worker(
        "device/ui/build/yoyopod-ui-host",
        ready_timeout_seconds=0.0,
        ready_poll_interval_seconds=0.0,
    )

    assert supervisor.stopped == ["ui"]


def test_facade_sends_snapshot_and_tick_without_request_tracking() -> None:
    supervisor = _Supervisor()
    app = SimpleNamespace(
        worker_supervisor=supervisor,
        context=None,
        app_state_runtime=None,
        people_directory=None,
    )
    facade = RustUiFacade(app, worker_domain="ui")

    assert facade.send_snapshot()
    assert facade.send_tick(renderer="lvgl")

    assert supervisor.sent[0][1] == "ui.runtime_snapshot"
    assert supervisor.sent[0][3] is None
    assert supervisor.sent[1] == ("ui", "ui.tick", {"renderer": "lvgl"}, None)


def test_facade_sends_backlight_commands_to_ui_worker() -> None:
    supervisor = _Supervisor()
    app = SimpleNamespace(worker_supervisor=supervisor)
    facade = RustUiFacade(app, worker_domain="ui")

    assert facade.send_backlight(brightness=1.25)

    assert supervisor.sent == [("ui", "ui.set_backlight", {"brightness": 1.0}, None)]


def test_facade_dispatches_intents_to_python_services() -> None:
    services = _Services()
    app = SimpleNamespace(services=services)
    facade = RustUiFacade(app, worker_domain="ui")

    facade.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="ui",
            kind="event",
            type="ui.intent",
            request_id=None,
            payload={"domain": "call", "action": "answer", "payload": {"source": "rust-ui"}},
        )
    )

    assert services.calls == [("call", "answer", AnswerCommand())]


def test_facade_builds_typed_music_commands() -> None:
    services = _Services()
    app = SimpleNamespace(services=services)
    facade = RustUiFacade(app, worker_domain="ui")

    facade.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="ui",
            kind="event",
            type="ui.intent",
            request_id=None,
            payload={
                "domain": "music",
                "action": "load_playlist",
                "payload": {"id": "m3u:tiny"},
            },
        )
    )
    facade.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="ui",
            kind="event",
            type="ui.intent",
            request_id=None,
            payload={
                "domain": "music",
                "action": "play_recent_track",
                "payload": {"id": "file:///music/little-song.mp3"},
            },
        )
    )

    assert services.calls == [
        ("music", "load_playlist", LoadPlaylistCommand(playlist_uri="m3u:tiny")),
        (
            "music",
            "play_recent_track",
            PlayRecentTrackCommand(track_uri="file:///music/little-song.mp3"),
        ),
    ]


def test_facade_maps_voice_capture_toggle_to_current_runtime_state() -> None:
    services = _Services()
    interaction = SimpleNamespace(capture_in_flight=False, ptt_active=False)
    active_voice_note = SimpleNamespace(
        recipient_address="sip:mama@example.com",
        recipient_name="Mama",
        send_state="idle",
    )
    app = SimpleNamespace(
        services=services,
        context=SimpleNamespace(
            voice=SimpleNamespace(interaction=interaction),
            talk=SimpleNamespace(active_voice_note=active_voice_note),
        ),
    )
    facade = RustUiFacade(app, worker_domain="ui")

    facade.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="ui",
            kind="event",
            type="ui.intent",
            request_id=None,
            payload={"domain": "voice", "action": "capture_toggle", "payload": {}},
        )
    )
    active_voice_note.send_state = "recording"
    facade.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="ui",
            kind="event",
            type="ui.intent",
            request_id=None,
            payload={"domain": "voice", "action": "capture_toggle", "payload": {}},
        )
    )

    assert services.calls == [
        (
            "call",
            "start_voice_note_recording",
            StartVoiceNoteRecordingCommand(
                recipient_address="sip:mama@example.com",
                recipient_name="Mama",
            ),
        ),
        ("call", "stop_voice_note_recording", StopVoiceNoteRecordingCommand()),
    ]
