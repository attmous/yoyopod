from __future__ import annotations

import threading
from pathlib import Path
from collections.abc import Callable

import pytest

from yoyopod.core.events import WorkerMessageReceivedEvent
from yoyopod.integrations.voice.worker_client import (
    VoiceWorkerClient,
    VoiceWorkerTimeout,
    VoiceWorkerUnavailable,
)
from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerAskResult,
    VoiceWorkerAskTurn,
    VoiceWorkerHealthResult,
    VoiceWorkerSpeakResult,
    VoiceWorkerTranscribeResult,
)


class _Scheduler:
    def __init__(self) -> None:
        self.callbacks: list[Callable[[], None]] = []

    def run_on_main(self, callback: Callable[[], None]) -> None:
        self.callbacks.append(callback)

    def drain(self) -> None:
        callbacks = list(self.callbacks)
        self.callbacks.clear()
        for callback in callbacks:
            callback()


class _MainThreadScheduler(_Scheduler):
    def __init__(self) -> None:
        super().__init__()
        self.main_thread_id = threading.get_ident()


class _Supervisor:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.send_result = True

    def send_request(self, domain: str, **kwargs: object) -> bool:
        self.requests.append({"domain": domain, **kwargs})
        return self.send_result


class _BlockingSupervisor(_Supervisor):
    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()
        self.active_domain: str | None = None
        self.active_kwargs: dict[str, object] = {}

    def send_request(self, domain: str, **kwargs: object) -> bool:
        self.active_domain = domain
        self.active_kwargs = dict(kwargs)
        self.entered.set()
        assert self.release.wait(timeout=1.0)
        return super().send_request(domain, **kwargs)


class _ReentrantSupervisor(_Supervisor):
    def __init__(self) -> None:
        super().__init__()
        self.client: VoiceWorkerClient | None = None

    def send_request(self, domain: str, **kwargs: object) -> bool:
        client = self.client
        assert client is not None
        request_id = kwargs["request_id"]
        assert isinstance(request_id, str)
        client.handle_worker_message(
            WorkerMessageReceivedEvent(
                domain=domain,
                kind="result",
                type="voice.transcribe.result",
                request_id=request_id,
                payload={"text": "reentrant result", "confidence": 0.7, "is_final": True},
            )
        )
        return super().send_request(domain, **kwargs)


def test_transcribe_schedules_request_on_main_and_resolves_result() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    results: list[VoiceWorkerTranscribeResult] = []

    thread = threading.Thread(
        target=lambda: results.append(
            client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                model="gpt-4o-transcribe",
                prompt="Transcribe YoYoPod commands in English Latin letters.",
                max_audio_seconds=5.0,
            )
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    assert supervisor.requests == []
    scheduler.drain()

    assert len(supervisor.requests) == 1
    request = supervisor.requests[0]
    assert request["domain"] == "voice"
    assert request["type"] == "voice.transcribe"
    assert isinstance(request["request_id"], str)
    assert str(request["request_id"]).startswith("voice-")
    assert request["timeout_seconds"] == 0.25
    assert request["payload"] == {
        "audio_path": "/tmp/input.wav",
        "format": "wav",
        "sample_rate_hz": 16000,
        "channels": 1,
        "language": "en",
        "model": "gpt-4o-transcribe",
        "prompt": "Transcribe YoYoPod commands in English Latin letters.",
        "max_audio_seconds": 5.0,
        "delete_input_on_success": False,
    }

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.transcribe.result",
            request_id=str(request["request_id"]),
            payload={"text": " play music ", "confidence": 0.9, "is_final": True},
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert results == [
        VoiceWorkerTranscribeResult(text="play music", confidence=0.9, is_final=True)
    ]
    assert client.pending_count == 0


def test_health_probe_marks_client_available() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    results: list[VoiceWorkerHealthResult] = []

    thread = threading.Thread(target=lambda: results.append(client.health()))
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request = supervisor.requests[0]
    assert request["type"] == "voice.health"

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.health.result",
            request_id=str(request["request_id"]),
            payload={"healthy": True, "provider": "mock"},
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert results == [VoiceWorkerHealthResult(healthy=True, provider="mock")]
    assert client.is_available is True
    assert client.availability_reason == "mock"


def test_health_probe_failure_marks_client_unavailable() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(errors, client.health),
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request = supervisor.requests[0]
    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="error",
            type="voice.error",
            request_id=str(request["request_id"]),
            payload={
                "code": "provider_error",
                "message": "OPENAI_API_KEY is not set",
                "retryable": True,
            },
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerUnavailable)
    assert client.is_available is False
    assert client.availability_reason == "OPENAI_API_KEY is not set"


def test_worker_error_raises_unavailable_with_error_code() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    client._set_available(True, "mock")
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=5.0,
            ),
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request_id = str(supervisor.requests[0]["request_id"])

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="error",
            type="voice.error",
            request_id=request_id,
            payload={
                "code": "provider_unavailable",
                "message": "provider down",
                "retryable": True,
            },
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerUnavailable)
    assert "provider_unavailable" in str(errors[0])
    assert client.is_available is True
    assert client.availability_reason == "mock"
    assert client.pending_count == 0


def test_fail_pending_requests_unblocks_waiter_on_worker_exit() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=1.0,
    )
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=5.0,
            ),
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    client.fail_pending_requests("process_exited")
    thread.join(timeout=0.2)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerUnavailable)
    assert "process_exited" in str(errors[0])
    assert client.pending_count == 0
    assert client.is_available is False
    assert client.availability_reason == "process_exited"


def test_cancel_event_sends_worker_cancel_and_unblocks_waiter() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    cancel_event = threading.Event()
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=5.0,
                cancel_event=cancel_event,
            ),
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request_id = str(supervisor.requests[0]["request_id"])

    cancel_event.set()
    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerUnavailable)
    assert supervisor.requests[1]["type"] == "voice.cancel"
    assert supervisor.requests[1]["request_id"] == request_id
    assert supervisor.requests[1]["payload"] == {"request_id": request_id}
    assert supervisor.requests[1]["timeout_seconds"] == 1.0
    assert client.pending_count == 0


def test_cancel_command_uses_voice_protocol_type_with_custom_domain() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        domain="voice-cloud",
        request_timeout_seconds=0.25,
    )
    cancel_event = threading.Event()
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=5.0,
                cancel_event=cancel_event,
            ),
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request_id = str(supervisor.requests[0]["request_id"])

    cancel_event.set()
    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerUnavailable)
    assert supervisor.requests[0]["domain"] == "voice-cloud"
    assert supervisor.requests[0]["type"] == "voice.transcribe"
    assert supervisor.requests[1]["domain"] == "voice-cloud"
    assert supervisor.requests[1]["type"] == "voice.cancel"
    assert supervisor.requests[1]["request_id"] == request_id
    assert supervisor.requests[1]["payload"] == {"request_id": request_id}
    assert client.pending_count == 0


def test_malformed_worker_error_raises_unavailable_and_cleans_pending() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=5.0,
            ),
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request_id = str(supervisor.requests[0]["request_id"])

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="error",
            type="voice.error",
            request_id=request_id,
            payload={},
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerUnavailable)
    assert "malformed voice worker error" in str(errors[0])
    assert client.pending_count == 0


def test_transcribe_raises_timeout_when_no_result_arrives() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.01,
    )

    with pytest.raises(VoiceWorkerTimeout):
        client.transcribe(
            audio_path=Path("/tmp/input.wav"),
            sample_rate_hz=16000,
            language="en",
            max_audio_seconds=5.0,
        )

    assert scheduler.callbacks
    assert supervisor.requests == []
    assert client.pending_count == 0


def test_cancelled_message_raises_unavailable_and_cleans_pending() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=5.0,
            ),
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.cancelled",
            request_id=str(supervisor.requests[0]["request_id"]),
            payload={},
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerUnavailable)
    assert client.pending_count == 0


def test_missing_request_id_message_is_ignored_and_request_can_resolve() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    results: list[VoiceWorkerTranscribeResult] = []

    thread = threading.Thread(
        target=lambda: results.append(
            client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=5.0,
            )
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request_id = str(supervisor.requests[0]["request_id"])

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.transcribe.result",
            request_id=None,
            payload={"text": "wrong", "confidence": 1.0, "is_final": True},
        )
    )

    assert results == []
    assert client.pending_count == 1

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.transcribe.result",
            request_id=request_id,
            payload={"text": "correct", "confidence": 0.8, "is_final": True},
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert results == [VoiceWorkerTranscribeResult(text="correct", confidence=0.8, is_final=True)]
    assert client.pending_count == 0


def test_non_matching_expected_result_type_is_ignored() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    results: list[VoiceWorkerTranscribeResult] = []

    thread = threading.Thread(
        target=lambda: results.append(
            client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=5.0,
            )
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request_id = str(supervisor.requests[0]["request_id"])

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.speak.result",
            request_id=request_id,
            payload={
                "audio_path": "/tmp/wrong.wav",
                "format": "wav",
                "sample_rate_hz": 16000,
            },
        )
    )

    assert results == []
    assert client.pending_count == 1

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.transcribe.result",
            request_id=request_id,
            payload={"text": "correct", "confidence": 0.8, "is_final": True},
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert results == [VoiceWorkerTranscribeResult(text="correct", confidence=0.8, is_final=True)]
    assert client.pending_count == 0


def test_malformed_transcribe_result_raises_unavailable_and_cleans_pending() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=5.0,
            ),
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.transcribe.result",
            request_id=str(supervisor.requests[0]["request_id"]),
            payload={"confidence": 0.8, "is_final": True},
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerUnavailable)
    assert "malformed voice worker result" in str(errors[0])
    assert client.pending_count == 0


def test_malformed_speak_result_raises_unavailable_and_cleans_pending() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: client.speak(
                text="Playing music",
                voice="alloy",
                model="gpt-4o-mini-tts",
                instructions="Speak clearly.",
                sample_rate_hz=16000,
            ),
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.speak.result",
            request_id=str(supervisor.requests[0]["request_id"]),
            payload={"format": "wav", "sample_rate_hz": 16000},
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerUnavailable)
    assert "malformed voice worker result" in str(errors[0])
    assert client.pending_count == 0


def test_unavailable_send_result_raises_unavailable_and_cleans_pending() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    supervisor.send_result = False
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=5.0,
            ),
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerUnavailable)
    assert client.pending_count == 0


def test_unavailable_send_exception_raises_unavailable_and_cleans_pending() -> None:
    class _RaisingSupervisor(_Supervisor):
        def send_request(self, domain: str, **kwargs: object) -> bool:
            raise RuntimeError("worker queue closed")

    scheduler = _Scheduler()
    supervisor = _RaisingSupervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=5.0,
            ),
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerUnavailable)
    assert "worker queue closed" in str(errors[0])
    assert client.pending_count == 0


def test_package_level_exports_include_worker_client_types() -> None:
    from yoyopod.integrations.voice import (
        VoiceWorkerClient as ExportedVoiceWorkerClient,
    )
    from yoyopod.integrations.voice import (
        VoiceWorkerTimeout as ExportedVoiceWorkerTimeout,
    )
    from yoyopod.integrations.voice import (
        VoiceWorkerUnavailable as ExportedVoiceWorkerUnavailable,
    )

    assert ExportedVoiceWorkerClient is VoiceWorkerClient
    assert ExportedVoiceWorkerTimeout is VoiceWorkerTimeout
    assert ExportedVoiceWorkerUnavailable is VoiceWorkerUnavailable


def test_transcribe_fast_fails_on_main_thread_without_scheduling() -> None:
    scheduler = _MainThreadScheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )

    with pytest.raises(VoiceWorkerUnavailable, match="main thread"):
        client.transcribe(
            audio_path=Path("/tmp/input.wav"),
            sample_rate_hz=16000,
            language="en",
            max_audio_seconds=5.0,
        )

    assert scheduler.callbacks == []
    assert supervisor.requests == []
    assert client.pending_count == 0


def test_late_scheduler_callback_does_not_send_after_timeout_cleanup() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.001,
    )
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=5.0,
            ),
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerTimeout)
    assert client.pending_count == 0
    assert supervisor.requests == []

    scheduler.drain()

    assert supervisor.requests == []


def test_timeout_cleanup_cannot_interleave_with_in_flight_send() -> None:
    scheduler = _Scheduler()
    supervisor = _BlockingSupervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.001,
    )
    completed = threading.Event()
    errors: list[BaseException] = []

    request_thread = threading.Thread(
        target=lambda: _capture_error_and_signal(
            errors,
            completed,
            lambda: client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=5.0,
            ),
        )
    )
    request_thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    drain_thread = threading.Thread(target=scheduler.drain)
    drain_thread.start()
    assert supervisor.entered.wait(timeout=1.0)

    try:
        assert not completed.wait(timeout=0.1)
    finally:
        supervisor.release.set()
        drain_thread.join(timeout=1.0)
        request_thread.join(timeout=1.0)

    assert not drain_thread.is_alive()
    assert not request_thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerTimeout)
    assert client.pending_count == 0


def test_late_result_after_timeout_still_raises_timeout() -> None:
    scheduler = _Scheduler()
    supervisor = _BlockingSupervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.001,
    )
    completed = threading.Event()
    errors: list[BaseException] = []
    results: list[VoiceWorkerTranscribeResult] = []

    request_thread = threading.Thread(
        target=lambda: _capture_error_and_signal(
            errors,
            completed,
            lambda: results.append(
                client.transcribe(
                    audio_path=Path("/tmp/input.wav"),
                    sample_rate_hz=16000,
                    language="en",
                    max_audio_seconds=5.0,
                )
            ),
        )
    )
    request_thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    drain_thread = threading.Thread(target=scheduler.drain)
    drain_thread.start()
    assert supervisor.entered.wait(timeout=1.0)
    assert not completed.wait(timeout=0.1)

    request_id = supervisor.active_kwargs["request_id"]
    assert isinstance(request_id, str)
    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.transcribe.result",
            request_id=request_id,
            payload={"text": "too late", "confidence": 0.8, "is_final": True},
        )
    )

    supervisor.release.set()
    drain_thread.join(timeout=1.0)
    request_thread.join(timeout=1.0)

    assert not drain_thread.is_alive()
    assert not request_thread.is_alive()
    assert results == []
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerTimeout)
    assert client.pending_count == 0


def test_duplicate_terminal_message_does_not_overwrite_first_result() -> None:
    scheduler = _Scheduler()
    supervisor = _BlockingSupervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    errors: list[BaseException] = []
    results: list[VoiceWorkerTranscribeResult] = []

    request_thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: results.append(
                client.transcribe(
                    audio_path=Path("/tmp/input.wav"),
                    sample_rate_hz=16000,
                    language="en",
                    max_audio_seconds=5.0,
                )
            ),
        )
    )
    request_thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    drain_thread = threading.Thread(target=scheduler.drain)
    drain_thread.start()
    assert supervisor.entered.wait(timeout=1.0)
    request_id = supervisor.active_kwargs["request_id"]
    assert isinstance(request_id, str)

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.transcribe.result",
            request_id=request_id,
            payload={"text": "first result", "confidence": 0.8, "is_final": True},
        )
    )
    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="error",
            type="voice.error",
            request_id=request_id,
            payload={
                "code": "late_duplicate",
                "message": "duplicate terminal message",
            },
        )
    )

    supervisor.release.set()
    drain_thread.join(timeout=1.0)
    request_thread.join(timeout=1.0)

    assert not drain_thread.is_alive()
    assert not request_thread.is_alive()
    assert errors == []
    assert results == [
        VoiceWorkerTranscribeResult(text="first result", confidence=0.8, is_final=True)
    ]
    assert client.pending_count == 0


def test_reentrant_worker_message_during_send_does_not_deadlock() -> None:
    scheduler = _Scheduler()
    supervisor = _ReentrantSupervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    supervisor.client = client
    results: list[VoiceWorkerTranscribeResult] = []
    errors: list[BaseException] = []

    request_thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: results.append(
                client.transcribe(
                    audio_path=Path("/tmp/input.wav"),
                    sample_rate_hz=16000,
                    language="en",
                    max_audio_seconds=5.0,
                )
            ),
        ),
        daemon=True,
    )
    request_thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    drain_thread = threading.Thread(target=scheduler.drain, daemon=True)
    drain_thread.start()
    drain_thread.join(timeout=1.0)
    request_thread.join(timeout=1.0)

    assert not drain_thread.is_alive()
    assert not request_thread.is_alive()
    assert errors == []
    assert results == [
        VoiceWorkerTranscribeResult(
            text="reentrant result",
            confidence=0.7,
            is_final=True,
        )
    ]
    assert client.pending_count == 0


def test_messages_from_other_domain_and_unknown_request_are_ignored() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    results: list[VoiceWorkerTranscribeResult] = []

    thread = threading.Thread(
        target=lambda: results.append(
            client.transcribe(
                audio_path=Path("/tmp/input.wav"),
                sample_rate_hz=16000,
                language="en",
                max_audio_seconds=5.0,
            )
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request_id = str(supervisor.requests[0]["request_id"])

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="music",
            kind="result",
            type="voice.transcribe.result",
            request_id=request_id,
            payload={"text": "wrong", "confidence": 1.0, "is_final": True},
        )
    )
    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.transcribe.result",
            request_id="voice-unknown",
            payload={"text": "wrong", "confidence": 1.0, "is_final": True},
        )
    )
    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="event",
            type="voice.progress",
            request_id=request_id,
            payload={"percent": 50},
        )
    )

    assert results == []
    assert client.pending_count == 1

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.transcribe.result",
            request_id=request_id,
            payload={"text": "correct", "confidence": 0.8, "is_final": True},
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert results == [VoiceWorkerTranscribeResult(text="correct", confidence=0.8, is_final=True)]
    assert client.pending_count == 0


def test_same_request_unrelated_error_kind_message_is_ignored() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    results: list[VoiceWorkerTranscribeResult] = []
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: results.append(
                client.transcribe(
                    audio_path=Path("/tmp/input.wav"),
                    sample_rate_hz=16000,
                    language="en",
                    max_audio_seconds=5.0,
                )
            ),
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request_id = str(supervisor.requests[0]["request_id"])

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="error",
            type="voice.progress",
            request_id=request_id,
            payload={
                "code": "progress_parse_failure",
                "message": "progress event failed upstream",
            },
        )
    )

    assert results == []
    assert errors == []
    assert client.pending_count == 1
    assert thread.is_alive()

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.transcribe.result",
            request_id=request_id,
            payload={"text": "correct", "confidence": 0.8, "is_final": True},
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert errors == []
    assert results == [VoiceWorkerTranscribeResult(text="correct", confidence=0.8, is_final=True)]
    assert client.pending_count == 0


def test_speak_schedules_request_on_main_and_resolves_result() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    results: list[VoiceWorkerSpeakResult] = []

    thread = threading.Thread(
        target=lambda: results.append(
            client.speak(
                text="Playing music",
                voice="alloy",
                model="gpt-4o-mini-tts",
                instructions="Speak clearly.",
                sample_rate_hz=16000,
            )
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request = supervisor.requests[0]

    assert request["domain"] == "voice"
    assert request["type"] == "voice.speak"
    assert request["payload"] == {
        "text": "Playing music",
        "voice": "alloy",
        "model": "gpt-4o-mini-tts",
        "instructions": "Speak clearly.",
        "format": "wav",
        "sample_rate_hz": 16000,
    }

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.speak.result",
            request_id=str(request["request_id"]),
            payload={
                "audio_path": "/tmp/output.wav",
                "format": "wav",
                "sample_rate_hz": 16000,
                "duration_ms": 830,
            },
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert results == [
        VoiceWorkerSpeakResult(
            audio_path=Path("/tmp/output.wav"),
            format="wav",
            sample_rate_hz=16000,
            duration_ms=830,
        )
    ]
    assert client.pending_count == 0


def test_ask_schedules_request_on_main_and_resolves_result() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    results: list[VoiceWorkerAskResult] = []

    thread = threading.Thread(
        target=lambda: results.append(
            client.ask(
                question="  What is playing?  ",
                history=[
                    VoiceWorkerAskTurn(role="user", text="  hi  "),
                    VoiceWorkerAskTurn(role="assistant", text="  hello  "),
                ],
                model="  gpt-4o-mini  ",
                instructions="  Be brief.  ",
                max_output_chars=320,
                timeout_seconds=6.5,
            )
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request = supervisor.requests[0]

    assert request["domain"] == "voice"
    assert request["type"] == "voice.ask"
    assert request["timeout_seconds"] == 6.5
    assert request["payload"] == {
        "question": "What is playing?",
        "history": [
            {"role": "user", "text": "hi"},
            {"role": "assistant", "text": "hello"},
        ],
        "model": "gpt-4o-mini",
        "instructions": "Be brief.",
        "max_output_chars": 320,
    }

    client.handle_worker_message(
        WorkerMessageReceivedEvent(
            domain="voice",
            kind="result",
            type="voice.ask.result",
            request_id=str(request["request_id"]),
            payload={
                "answer": "  The song is playing.  ",
                "model": "gpt-4o-mini",
                "provider_latency_ms": 150,
            },
        )
    )
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert results == [
        VoiceWorkerAskResult(
            answer="The song is playing.",
            model="gpt-4o-mini",
            provider_latency_ms=150,
        )
    ]
    assert client.pending_count == 0


def test_ask_cancel_event_sends_worker_cancel_and_unblocks_waiter() -> None:
    scheduler = _Scheduler()
    supervisor = _Supervisor()
    client = VoiceWorkerClient(
        scheduler=scheduler,
        worker_supervisor=supervisor,
        request_timeout_seconds=0.25,
    )
    cancel_event = threading.Event()
    errors: list[BaseException] = []

    thread = threading.Thread(
        target=lambda: _capture_error(
            errors,
            lambda: client.ask(
                question="What is playing?",
                history=[],
                model="gpt-4o-mini",
                instructions="Be brief.",
                max_output_chars=320,
                cancel_event=cancel_event,
            ),
        )
    )
    thread.start()

    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    request_id = str(supervisor.requests[0]["request_id"])

    cancel_event.set()
    _wait_until(lambda: len(scheduler.callbacks) == 1)
    scheduler.drain()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert len(errors) == 1
    assert isinstance(errors[0], VoiceWorkerUnavailable)
    assert supervisor.requests[0]["type"] == "voice.ask"
    assert supervisor.requests[1]["type"] == "voice.cancel"
    assert supervisor.requests[1]["request_id"] == request_id
    assert supervisor.requests[1]["payload"] == {"request_id": request_id}
    assert supervisor.requests[1]["timeout_seconds"] == 1.0
    assert client.pending_count == 0


def _capture_error(errors: list[BaseException], callback: Callable[[], object]) -> None:
    try:
        callback()
    except BaseException as exc:
        errors.append(exc)


def _capture_error_and_signal(
    errors: list[BaseException],
    completed: threading.Event,
    callback: Callable[[], object],
) -> None:
    try:
        callback()
    except BaseException as exc:
        errors.append(exc)
    finally:
        completed.set()


def _wait_until(predicate: Callable[[], bool], timeout_seconds: float = 1.0) -> None:
    deadline = threading.Event()
    completed = threading.Event()

    def poll() -> None:
        while not completed.is_set() and not predicate():
            completed.wait(0.001)
        deadline.set()

    thread = threading.Thread(target=poll)
    thread.start()
    assert deadline.wait(timeout_seconds)
    completed.set()
    thread.join(timeout=1.0)
