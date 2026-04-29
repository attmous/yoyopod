from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from yoyopod.backends.voip import rust_host
from yoyopod.backends.voip.rust_host import RustHostBackend
from yoyopod.integrations.call.models import (
    BackendRecovered,
    BackendStopped,
    CallState,
    CallStateChanged,
    IncomingCallDetected,
    MessageDeliveryChanged,
    MessageDeliveryState,
    MessageDownloadCompleted,
    MessageFailed,
    MessageKind,
    MessageReceived,
    RegistrationState,
    RegistrationStateChanged,
    VoIPConfig,
)


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


class _SingleRunningSupervisor(_FakeSupervisor):
    def __init__(self) -> None:
        super().__init__()
        self.running = False

    def start(self, domain: str) -> bool:
        if self.running:
            raise RuntimeError("worker already running")
        self.running = True
        return super().start(domain)

    def stop(self, domain: str, *, grace_seconds: float = 1.0) -> None:
        self.running = False
        super().stop(domain, grace_seconds=grace_seconds)


class _RejectingStartupSupervisor(_FakeSupervisor):
    def __init__(self, rejected_type: str) -> None:
        super().__init__()
        self.rejected_type = rejected_type

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
        super().send_command(
            domain,
            type=type,
            payload=payload,
            request_id=request_id,
            timestamp_ms=timestamp_ms,
            deadline_ms=deadline_ms,
        )
        return type != self.rejected_type


class _StrictSupervisor(_FakeSupervisor):
    def stop(self, domain: str, *, grace_seconds: float = 1.0) -> None:
        if not any(registered_domain == domain for registered_domain, _config in self.registered):
            raise KeyError(domain)
        super().stop(domain, grace_seconds=grace_seconds)

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
        if not any(registered_domain == domain for registered_domain, _config in self.registered):
            raise KeyError(domain)
        return super().send_command(
            domain,
            type=type,
            payload=payload,
            request_id=request_id,
            timestamp_ms=timestamp_ms,
            deadline_ms=deadline_ms,
        )


def _config() -> VoIPConfig:
    return VoIPConfig(
        sip_server="sip.example.com",
        sip_username="alice",
        sip_identity="sip:alice@example.com",
    )


def _event(message_type: str, payload: dict[str, Any], *, domain: str = "voip") -> Any:
    return SimpleNamespace(domain=domain, kind="event", type=message_type, payload=payload)


def _reply(
    kind: str,
    message_type: str,
    payload: dict[str, Any],
    *,
    request_id: str | None,
    domain: str = "voip",
) -> Any:
    return SimpleNamespace(
        domain=domain,
        kind=kind,
        type=message_type,
        request_id=request_id,
        payload=payload,
    )


def _state(state: str, reason: str, *, domain: str = "voip") -> Any:
    return SimpleNamespace(domain=domain, state=state, reason=reason)


def test_start_registers_worker_and_sends_configure_register() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")

    assert backend.start() is True

    assert supervisor.registered[0][0] == "voip"
    assert supervisor.registered[0][1].argv == ["/bin/voip"]
    assert supervisor.started == ["voip"]
    assert [item[1] for item in supervisor.sent] == ["voip.configure", "voip.register"]
    assert supervisor.sent[0][2]["sip_identity"] == "sip:alice@example.com"
    assert supervisor.request_ids == ["voip-voip_configure-1", "voip-voip_register-2"]
    assert backend.running is True


def test_stop_before_worker_registration_is_noop() -> None:
    supervisor = _StrictSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")

    backend.stop()

    assert supervisor.sent == []
    assert supervisor.stopped == []
    assert backend.running is False


def test_delayed_intentional_stop_state_does_not_emit_backend_stopped() -> None:
    supervisor = _StrictSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    received: list[object] = []
    backend.on_event(received.append)
    backend.start()

    backend.stop()
    backend.handle_worker_state_change(_state("stopped", "stop"))

    assert not received
    assert backend.running is False


def test_delayed_intentional_lifecycle_stop_does_not_emit_backend_stopped() -> None:
    supervisor = _StrictSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    received: list[object] = []
    backend.on_event(received.append)
    backend.start()

    backend.stop()
    backend.handle_worker_message(
        _event(
            "voip.lifecycle_changed",
            {
                "state": "stopped",
                "previous_state": "registered",
                "reason": "unregistered",
                "recovered": False,
            },
        )
    )

    assert not received
    assert backend.running is False


def test_call_commands_send_worker_commands() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    backend.start()
    supervisor.sent.clear()

    assert backend.make_call("sip:bob@example.com") is True
    assert backend.answer_call() is True
    assert backend.reject_call() is True
    assert backend.hangup() is True
    assert backend.mute() is True
    assert backend.unmute() is True

    assert [item[1] for item in supervisor.sent] == [
        "voip.dial",
        "voip.answer",
        "voip.reject",
        "voip.hangup",
        "voip.set_mute",
        "voip.set_mute",
    ]
    assert supervisor.sent[0][2] == {"uri": "sip:bob@example.com"}
    assert supervisor.sent[4][2] == {"muted": True}
    assert supervisor.sent[5][2] == {"muted": False}


def test_send_text_message_returns_client_id_and_sends_worker_command() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    backend.start()
    supervisor.sent.clear()

    message_id = backend.send_text_message("sip:bob@example.com", "hi")

    assert message_id is not None
    assert message_id.startswith("rust-msg-")
    assert supervisor.sent == [
        (
            "voip",
            "voip.send_text_message",
            {
                "uri": "sip:bob@example.com",
                "text": "hi",
                "client_id": message_id,
            },
        )
    ]


def test_text_message_ids_do_not_repeat_across_backend_instances() -> None:
    first = RustHostBackend(_config(), worker_supervisor=_FakeSupervisor(), worker_path="/bin/voip")
    second = RustHostBackend(
        _config(), worker_supervisor=_FakeSupervisor(), worker_path="/bin/voip"
    )
    first.start()
    second.start()

    first_message_id = first.send_text_message("sip:bob@example.com", "hi")
    second_message_id = second.send_text_message("sip:bob@example.com", "hi")

    assert first_message_id is not None
    assert second_message_id is not None
    assert first_message_id.startswith("rust-msg-")
    assert second_message_id.startswith("rust-msg-")
    assert first_message_id != second_message_id


def test_text_message_command_error_emits_message_failed() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    received: list[object] = []
    backend.on_event(received.append)
    backend.start()

    message_id = backend.send_text_message("sip:bob@example.com", "hi")
    backend.handle_worker_message(
        _reply(
            "error",
            "voip.error",
            {"code": "command_failed", "message": "peer offline"},
            request_id=supervisor.request_ids[-1],
        )
    )

    failures = [event for event in received if isinstance(event, MessageFailed)]
    assert failures
    assert failures[-1].message_id == message_id
    assert failures[-1].reason == "voip.send_text_message command_failed: peer offline"


def test_voice_note_recording_commands_send_worker_commands(monkeypatch) -> None:
    monotonic_values = iter([100.0, 102.5])
    monkeypatch.setattr(rust_host.time, "monotonic", lambda: next(monotonic_values))
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    backend.start()
    supervisor.sent.clear()

    assert backend.start_voice_note_recording("/tmp/a.wav") is True
    assert backend.stop_voice_note_recording() == 2500
    assert backend.cancel_voice_note_recording() is True

    assert supervisor.sent == [
        ("voip", "voip.start_voice_note_recording", {"file_path": "/tmp/a.wav"}),
        ("voip", "voip.stop_voice_note_recording", {}),
        ("voip", "voip.cancel_voice_note_recording", {}),
    ]


def test_stop_voice_note_without_active_recording_returns_none() -> None:
    backend = RustHostBackend(
        _config(), worker_supervisor=_FakeSupervisor(), worker_path="/bin/voip"
    )

    assert backend.stop_voice_note_recording() is None


def test_send_voice_note_returns_client_id_and_sends_worker_command() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    backend.start()
    supervisor.sent.clear()

    message_id = backend.send_voice_note(
        "sip:bob@example.com",
        file_path="/tmp/a.wav",
        duration_ms=1200,
        mime_type="audio/wav",
    )

    assert message_id is not None
    assert message_id.startswith("rust-msg-")
    assert supervisor.sent == [
        (
            "voip",
            "voip.send_voice_note",
            {
                "uri": "sip:bob@example.com",
                "file_path": "/tmp/a.wav",
                "duration_ms": 1200,
                "mime_type": "audio/wav",
                "client_id": message_id,
            },
        )
    ]


def test_voice_note_command_errors_emit_message_failed() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    received: list[object] = []
    backend.on_event(received.append)
    backend.start()

    assert backend.start_voice_note_recording("/tmp/a.wav") is True
    backend.handle_worker_message(
        _reply(
            "error",
            "voip.error",
            {"code": "command_failed", "message": "mic unavailable"},
            request_id=supervisor.request_ids[-1],
        )
    )

    message_id = backend.send_voice_note(
        "sip:bob@example.com",
        file_path="/tmp/a.wav",
        duration_ms=1200,
        mime_type="audio/wav",
    )
    backend.handle_worker_message(
        _reply(
            "error",
            "voip.error",
            {"code": "command_failed", "message": "upload failed"},
            request_id=supervisor.request_ids[-1],
        )
    )

    failures = [event for event in received if isinstance(event, MessageFailed)]
    assert failures[0].message_id == ""
    assert failures[0].reason == "voip.start_voice_note_recording command_failed: mic unavailable"
    assert failures[1].message_id == message_id
    assert failures[1].reason == "voip.send_voice_note command_failed: upload failed"


def test_worker_events_translate_to_voip_events() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    received: list[object] = []
    backend.on_event(received.append)

    backend.handle_worker_message(
        _event("voip.registration_changed", {"state": "ok", "reason": ""})
    )
    backend.handle_worker_message(
        _event("voip.incoming_call", {"call_id": "call-1", "from_uri": "sip:bob@example.com"})
    )
    backend.handle_worker_message(
        _event("voip.call_state_changed", {"call_id": "call-1", "state": "streams_running"})
    )
    backend.handle_worker_message(_event("voip.backend_stopped", {"reason": "iterate failed"}))
    backend.handle_worker_message(_event("voip.backend_stopped", {"reason": "wrong"}, domain="ui"))

    assert isinstance(received[0], RegistrationStateChanged)
    assert received[0].state == RegistrationState.OK
    assert isinstance(received[1], IncomingCallDetected)
    assert received[1].caller_address == "sip:bob@example.com"
    assert isinstance(received[2], CallStateChanged)
    assert received[2].state == CallState.STREAMS_RUNNING
    assert isinstance(received[3], BackendStopped)
    assert received[3].reason == "iterate failed"
    assert len(received) == 4


def test_worker_snapshot_updates_registration_and_call_state_without_duplicates() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    received: list[object] = []
    backend.on_event(received.append)

    backend.handle_worker_message(
        _event(
            "voip.snapshot",
            {
                "configured": True,
                "registered": True,
                "registration_state": "ok",
                "call_state": "streams_running",
                "active_call_id": "call-1",
                "pending_outbound_messages": 0,
                "voice_note": {"state": "idle", "file_path": "", "duration_ms": 0},
            },
        )
    )
    backend.handle_worker_message(
        _event(
            "voip.snapshot",
            {
                "configured": True,
                "registered": True,
                "registration_state": "ok",
                "call_state": "streams_running",
                "active_call_id": "call-1",
                "pending_outbound_messages": 0,
                "voice_note": {"state": "idle", "file_path": "", "duration_ms": 0},
            },
        )
    )

    assert [type(event) for event in received] == [RegistrationStateChanged, CallStateChanged]
    assert received[0].state == RegistrationState.OK
    assert received[1].state == CallState.STREAMS_RUNNING


def test_worker_message_events_translate_to_voip_events() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    received: list[object] = []
    backend.on_event(received.append)

    backend.handle_worker_message(
        _event(
            "voip.message_received",
            {
                "message_id": "msg-1",
                "peer_sip_address": "sip:bob@example.com",
                "sender_sip_address": "sip:bob@example.com",
                "recipient_sip_address": "sip:alice@example.com",
                "kind": "text",
                "direction": "incoming",
                "delivery_state": "delivered",
                "created_at": "2026-04-29T00:00:00+00:00",
                "updated_at": "2026-04-29T00:00:00+00:00",
                "text": "hello",
                "local_file_path": "",
                "mime_type": "",
                "duration_ms": 0,
                "unread": True,
            },
        )
    )
    backend.handle_worker_message(
        _event(
            "voip.message_delivery_changed",
            {
                "message_id": "msg-1",
                "delivery_state": "delivered",
                "local_file_path": "",
                "error": "",
            },
        )
    )
    backend.handle_worker_message(
        _event(
            "voip.message_download_completed",
            {"message_id": "msg-1", "local_file_path": "/tmp/a.wav", "mime_type": "audio/wav"},
        )
    )
    backend.handle_worker_message(
        _event("voip.message_failed", {"message_id": "msg-1", "reason": "peer offline"})
    )

    assert isinstance(received[0], MessageReceived)
    assert received[0].message.id == "msg-1"
    assert received[0].message.kind == MessageKind.TEXT
    assert received[0].message.delivery_state == MessageDeliveryState.DELIVERED
    assert received[0].message.text == "hello"
    assert isinstance(received[1], MessageDeliveryChanged)
    assert received[1].message_id == "msg-1"
    assert received[1].delivery_state == MessageDeliveryState.DELIVERED
    assert isinstance(received[2], MessageDownloadCompleted)
    assert received[2].local_file_path == "/tmp/a.wav"
    assert isinstance(received[3], MessageFailed)
    assert received[3].reason == "peer offline"


def test_worker_startup_error_stops_worker_and_marks_backend_stopped() -> None:
    supervisor = _SingleRunningSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    received: list[object] = []
    backend.on_event(received.append)
    backend.start()

    backend.handle_worker_message(
        _reply(
            "error",
            "voip.error",
            {"code": "command_failed", "message": "shim missing"},
            request_id=supervisor.request_ids[1],
        )
    )

    assert backend.running is False
    assert supervisor.stopped == [("voip", 1.0)]
    assert isinstance(received[0], BackendStopped)
    assert received[0].reason == "voip.register command_failed: shim missing"

    assert backend.start() is True
    assert supervisor.started == ["voip", "voip"]


def test_worker_lifecycle_failure_owns_startup_stopped_event() -> None:
    supervisor = _SingleRunningSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    received: list[object] = []
    backend.on_event(received.append)
    backend.start()

    backend.handle_worker_message(
        _event(
            "voip.lifecycle_changed",
            {
                "state": "failed",
                "previous_state": "registering",
                "reason": "shim missing",
                "recovered": False,
            },
        )
    )
    backend.handle_worker_message(
        _reply(
            "error",
            "voip.error",
            {"code": "command_failed", "message": "shim missing"},
            request_id=supervisor.request_ids[1],
        )
    )

    assert backend.running is False
    assert supervisor.stopped == [("voip", 1.0)]
    stopped = [event for event in received if isinstance(event, BackendStopped)]
    assert len(stopped) == 1
    assert stopped[0].reason == "shim missing"


def test_restart_register_error_without_lifecycle_event_reports_backend_stopped() -> None:
    supervisor = _SingleRunningSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    received: list[object] = []
    backend.on_event(received.append)
    backend.start()

    backend.stop()
    received.clear()

    assert backend.start() is True
    backend.handle_worker_message(
        _reply(
            "error",
            "voip.error",
            {"code": "command_failed", "message": "shim missing"},
            request_id=supervisor.request_ids[-1],
        )
    )

    assert backend.running is False
    stopped = [event for event in received if isinstance(event, BackendStopped)]
    assert len(stopped) == 1
    assert stopped[0].reason == "voip.register command_failed: shim missing"


def test_startup_send_failure_stops_worker_before_returning_false() -> None:
    supervisor = _RejectingStartupSupervisor("voip.register")
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")

    assert backend.start() is False

    assert backend.running is False
    assert supervisor.stopped == [("voip", 1.0)]


def test_worker_call_command_errors_surface_call_error_events() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    received: list[object] = []
    backend.on_event(received.append)
    backend.start()

    commands = [
        lambda: backend.make_call("sip:bob@example.com"),
        backend.answer_call,
        backend.reject_call,
        backend.hangup,
        backend.mute,
        backend.unmute,
    ]
    for send_command in commands:
        assert send_command() is True
        backend.handle_worker_message(
            _reply(
                "error",
                "voip.error",
                {"code": "command_failed", "message": "shim rejected command"},
                request_id=supervisor.request_ids[-1],
            )
        )

    assert backend.running is True
    call_errors = [event for event in received if isinstance(event, CallStateChanged)]
    assert len(call_errors) == len(commands)
    assert all(event.state == CallState.ERROR for event in call_errors)


def test_ready_after_worker_restart_resends_configure_register() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    received: list[object] = []
    backend.on_event(received.append)
    backend.start()

    backend.handle_worker_state_change(_state("running", "started"))
    backend.handle_worker_message(_event("voip.ready", {"capabilities": ["calls"]}))
    assert [item[1] for item in supervisor.sent] == ["voip.configure", "voip.register"]
    assert received == []

    backend.handle_worker_state_change(_state("degraded", "process_exited"))
    backend.handle_worker_state_change(_state("running", "started"))
    backend.handle_worker_message(_event("voip.ready", {"capabilities": ["calls"]}))

    assert [item[1] for item in supervisor.sent] == [
        "voip.configure",
        "voip.register",
        "voip.configure",
        "voip.register",
    ]
    assert backend.running is True
    assert isinstance(received[0], BackendStopped)
    assert received[0].reason == "process_exited"
    assert len(received) == 1

    backend.handle_worker_message(
        _event(
            "voip.lifecycle_changed",
            {
                "state": "registered",
                "previous_state": "registering",
                "reason": "registered",
                "recovered": True,
            },
        )
    )

    assert isinstance(received[1], BackendRecovered)
    assert received[1].reason == "registered"


def test_iterate_is_noop() -> None:
    backend = RustHostBackend(
        _config(), worker_supervisor=_FakeSupervisor(), worker_path="/bin/voip"
    )

    assert backend.iterate() == 0
    assert backend.get_iterate_metrics() is None
