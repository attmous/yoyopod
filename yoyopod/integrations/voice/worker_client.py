"""Main-thread-safe client for the voice worker protocol."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from yoyopod.core.events import WorkerMessageReceivedEvent
from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerSpeakResult,
    VoiceWorkerTranscribeResult,
    build_speak_payload,
    build_transcribe_payload,
    parse_speak_result,
    parse_transcribe_result,
    parse_worker_error,
)


class VoiceWorkerTimeout(TimeoutError):
    """Raised when the voice worker does not complete a request in time."""


class VoiceWorkerUnavailable(RuntimeError):
    """Raised when the voice worker cannot accept or complete a request."""


class _Scheduler(Protocol):
    def run_on_main(self, callback: Callable[[], None]) -> None:
        """Schedule one callback onto the app's main runtime thread."""


class _WorkerSupervisor(Protocol):
    def send_request(
        self,
        domain: str,
        *,
        type: str,
        payload: dict[str, Any],
        request_id: str,
        timeout_seconds: float,
    ) -> bool:
        """Send one worker request from the main runtime thread."""


@dataclass(slots=True)
class _PendingRequest:
    request_id: str
    expected_type: str
    send_lock: threading.Lock = field(default_factory=threading.Lock)
    event: threading.Event = field(default_factory=threading.Event)
    result: VoiceWorkerTranscribeResult | VoiceWorkerSpeakResult | None = None
    error: BaseException | None = None


class VoiceWorkerClient:
    """Request/response helper for the voice worker sidecar."""

    _WAIT_GRACE_SECONDS = 0.05

    def __init__(
        self,
        *,
        scheduler: _Scheduler,
        worker_supervisor: _WorkerSupervisor,
        domain: str = "voice",
        request_timeout_seconds: float = 30.0,
    ) -> None:
        self._scheduler = scheduler
        self._worker_supervisor = worker_supervisor
        self._domain = domain
        self._request_timeout_seconds = max(0.0, request_timeout_seconds)
        self._lock = threading.Lock()
        self._pending: dict[str, _PendingRequest] = {}

    @property
    def pending_count(self) -> int:
        """Return the number of requests currently awaiting worker completion."""

        with self._lock:
            return len(self._pending)

    def transcribe(
        self,
        *,
        audio_path: Path,
        sample_rate_hz: int,
        language: str,
        max_audio_seconds: float,
    ) -> VoiceWorkerTranscribeResult:
        """Send one transcription request and wait for its normalized result."""

        self._raise_if_called_on_main_thread()
        payload = build_transcribe_payload(
            audio_path=audio_path,
            sample_rate_hz=sample_rate_hz,
            language=language,
            max_audio_seconds=max_audio_seconds,
        )
        pending = self._send(
            request_type="voice.transcribe",
            expected_type="voice.transcribe.result",
            payload=payload,
        )
        result = self._wait_for(pending)
        if isinstance(result, VoiceWorkerTranscribeResult):
            return result
        raise VoiceWorkerUnavailable("voice worker did not return a transcription result")

    def speak(
        self,
        *,
        text: str,
        voice: str,
        model: str,
        instructions: str,
        sample_rate_hz: int,
    ) -> VoiceWorkerSpeakResult:
        """Send one speech synthesis request and wait for its normalized result."""

        self._raise_if_called_on_main_thread()
        payload = build_speak_payload(
            text=text,
            voice=voice,
            model=model,
            instructions=instructions,
            sample_rate_hz=sample_rate_hz,
        )
        pending = self._send(
            request_type="voice.speak",
            expected_type="voice.speak.result",
            payload=payload,
        )
        result = self._wait_for(pending)
        if isinstance(result, VoiceWorkerSpeakResult):
            return result
        raise VoiceWorkerUnavailable("voice worker did not return a speech result")

    def handle_worker_message(self, event: WorkerMessageReceivedEvent) -> None:
        """Resolve a pending request from one worker message when it matches."""

        if event.domain != self._domain or event.request_id is None:
            return
        with self._lock:
            pending = self._pending.get(event.request_id)
        if pending is None:
            return

        if event.type == pending.expected_type:
            self._complete_with_result(pending, event)
            return
        if event.type == "voice.error":
            self._complete_with_worker_error(pending, event.payload)
            return
        if event.type == "voice.cancelled":
            pending.error = VoiceWorkerUnavailable("voice worker request cancelled")
            pending.event.set()

    def _send(
        self,
        *,
        request_type: str,
        expected_type: str,
        payload: dict[str, Any],
    ) -> _PendingRequest:
        request_id = f"voice-{uuid.uuid4().hex}"
        pending = _PendingRequest(request_id=request_id, expected_type=expected_type)
        with self._lock:
            self._pending[request_id] = pending

        def send_on_main() -> None:
            with pending.send_lock:
                with self._lock:
                    if self._pending.get(request_id) is not pending:
                        return
                try:
                    sent = self._worker_supervisor.send_request(
                        self._domain,
                        type=request_type,
                        payload=payload,
                        request_id=request_id,
                        timeout_seconds=self._request_timeout_seconds,
                    )
                except Exception as exc:
                    self._complete_send_failure(
                        pending,
                        VoiceWorkerUnavailable(str(exc) or "voice worker unavailable"),
                    )
                    return
                if not sent:
                    self._complete_send_failure(
                        pending,
                        VoiceWorkerUnavailable("voice worker unavailable"),
                    )

        self._scheduler.run_on_main(send_on_main)
        return pending

    def _raise_if_called_on_main_thread(self) -> None:
        main_thread_id = getattr(self._scheduler, "main_thread_id", None)
        if main_thread_id is not None and threading.get_ident() == main_thread_id:
            raise VoiceWorkerUnavailable("voice worker client cannot block the main thread")

    def _wait_for(
        self, pending: _PendingRequest
    ) -> VoiceWorkerTranscribeResult | VoiceWorkerSpeakResult:
        wait_seconds = self._request_timeout_seconds + self._WAIT_GRACE_SECONDS
        completed = pending.event.wait(wait_seconds)
        with pending.send_lock:
            with self._lock:
                self._pending.pop(pending.request_id, None)

        if not completed and not pending.event.is_set():
            raise VoiceWorkerTimeout(f"voice worker request {pending.request_id} timed out")
        if pending.error is not None:
            raise pending.error
        if pending.result is None:
            raise VoiceWorkerUnavailable("voice worker did not return a result")
        return pending.result

    def _complete_send_failure(
        self,
        pending: _PendingRequest,
        error: VoiceWorkerUnavailable,
    ) -> None:
        with self._lock:
            if self._pending.get(pending.request_id) is not pending:
                return
            if pending.event.is_set():
                return
            pending.error = error
            pending.event.set()

    def _complete_with_result(
        self, pending: _PendingRequest, event: WorkerMessageReceivedEvent
    ) -> None:
        try:
            if event.type == "voice.transcribe.result":
                pending.result = parse_transcribe_result(event.payload)
            elif event.type == "voice.speak.result":
                pending.result = parse_speak_result(event.payload)
            else:
                return
        except Exception as exc:
            pending.error = exc
        pending.event.set()

    def _complete_with_worker_error(
        self, pending: _PendingRequest, payload: dict[str, Any]
    ) -> None:
        try:
            worker_error = parse_worker_error(payload)
        except Exception as exc:
            pending.error = exc
        else:
            pending.error = VoiceWorkerUnavailable(f"{worker_error.code}: {worker_error.message}")
        pending.event.set()


__all__ = [
    "VoiceWorkerClient",
    "VoiceWorkerTimeout",
    "VoiceWorkerUnavailable",
]
