from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from yoyopod.backends.voip.rust_host import RustHostBackend
from yoyopod.integrations.call.models import (
    BackendStopped,
    CallState,
    CallStateChanged,
    IncomingCallDetected,
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
    backend.handle_worker_message(
        _event("voip.backend_stopped", {"reason": "iterate failed"})
    )
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


def test_worker_startup_error_marks_backend_stopped() -> None:
    supervisor = _FakeSupervisor()
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
    assert isinstance(received[0], BackendStopped)
    assert received[0].reason == "voip.register command_failed: shim missing"


def test_ready_after_worker_restart_resends_configure_register() -> None:
    supervisor = _FakeSupervisor()
    backend = RustHostBackend(_config(), worker_supervisor=supervisor, worker_path="/bin/voip")
    received: list[object] = []
    backend.on_event(received.append)
    backend.start()

    backend.handle_worker_state_change(_state("running", "started"))
    backend.handle_worker_message(_event("voip.ready", {"capabilities": ["calls"]}))
    assert [item[1] for item in supervisor.sent] == ["voip.configure", "voip.register"]

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


def test_iterate_is_noop_and_unsupported_messaging_fails() -> None:
    backend = RustHostBackend(_config(), worker_supervisor=_FakeSupervisor(), worker_path="/bin/voip")

    assert backend.iterate() == 0
    assert backend.get_iterate_metrics() is None
    assert backend.send_text_message("sip:bob@example.com", "hi") is None
    assert backend.start_voice_note_recording("/tmp/a.wav") is False
    assert backend.stop_voice_note_recording() is None
    assert backend.cancel_voice_note_recording() is False
    assert (
        backend.send_voice_note(
            "sip:bob@example.com",
            file_path="/tmp/a.wav",
            duration_ms=1000,
            mime_type="audio/wav",
        )
        is None
    )
