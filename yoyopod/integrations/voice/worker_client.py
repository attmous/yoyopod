"""Main-thread-safe client for the voice worker protocol."""

from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from yoyopod.core.events import WorkerMessageReceivedEvent
from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerAskResult,
    VoiceWorkerAskTurn,
    VoiceWorkerHealthResult,
    VoiceWorkerSpeakResult,
    VoiceWorkerTranscribeResult,
    build_ask_payload,
    build_speak_payload,
    build_transcribe_payload,
    parse_ask_result,
    parse_health_result,
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
    result: (
        VoiceWorkerTranscribeResult
        | VoiceWorkerSpeakResult
        | VoiceWorkerAskResult
        | VoiceWorkerHealthResult
        | None
    ) = None
    error: BaseException | None = None
    cancel_sent: bool = False


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
        self._available = False
        self._availability_reason = "not_checked"

    @property
    def pending_count(self) -> int:
        """Return the number of requests currently awaiting worker completion."""

        with self._lock:
            return len(self._pending)

    @property
    def is_available(self) -> bool:
        """Return whether the worker has passed its latest health check."""

        with self._lock:
            return self._available

    @property
    def availability_reason(self) -> str:
        """Return a concise reason for the current availability state."""

        with self._lock:
            return self._availability_reason

    def mark_unavailable(self, reason: str) -> None:
        """Mark the worker unavailable after a lifecycle or provider failure."""

        self._set_available(False, reason or "unavailable")

    def fail_pending_requests(self, reason: str) -> None:
        """Fail all in-flight requests because the worker lifecycle changed."""

        normalized_reason = reason or "unavailable"
        self._set_available(False, normalized_reason)
        with self._lock:
            pending_requests = list(self._pending.values())
        for pending in pending_requests:
            self._complete_once(
                pending,
                error=VoiceWorkerUnavailable(f"voice worker unavailable: {normalized_reason}"),
            )

    def health(self) -> VoiceWorkerHealthResult:
        """Probe worker/provider health and update availability."""

        self._raise_if_called_on_main_thread()
        pending = self._send(
            request_type="voice.health",
            expected_type="voice.health.result",
            payload={},
        )
        try:
            result = self._wait_for(pending)
        except Exception as exc:
            if self.availability_reason == "not_checked":
                self._set_available(False, str(exc) or "health_failed")
            raise
        if not isinstance(result, VoiceWorkerHealthResult):
            self._set_available(False, "malformed_health_result")
            raise VoiceWorkerUnavailable("voice worker did not return a health result")
        if not result.healthy:
            self._set_available(False, result.message or "unhealthy")
            raise VoiceWorkerUnavailable(result.message or "voice worker unhealthy")
        self._set_available(True, result.provider)
        return result

    def transcribe(
        self,
        *,
        audio_path: Path,
        sample_rate_hz: int,
        language: str,
        max_audio_seconds: float,
        model: str = "",
        cancel_event: threading.Event | None = None,
    ) -> VoiceWorkerTranscribeResult:
        """Send one transcription request and wait for its normalized result."""

        self._raise_if_called_on_main_thread()
        payload = build_transcribe_payload(
            audio_path=audio_path,
            sample_rate_hz=sample_rate_hz,
            language=language,
            max_audio_seconds=max_audio_seconds,
            model=model,
        )
        pending = self._send(
            request_type="voice.transcribe",
            expected_type="voice.transcribe.result",
            payload=payload,
        )
        result = self._wait_for(pending, cancel_event=cancel_event)
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
        cancel_event: threading.Event | None = None,
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
        result = self._wait_for(pending, cancel_event=cancel_event)
        if isinstance(result, VoiceWorkerSpeakResult):
            return result
        raise VoiceWorkerUnavailable("voice worker did not return a speech result")

    def ask(
        self,
        *,
        question: str,
        history: list[VoiceWorkerAskTurn],
        model: str,
        instructions: str,
        max_output_chars: int,
        cancel_event: threading.Event | None = None,
    ) -> VoiceWorkerAskResult:
        """Send one question answering request and wait for its normalized result."""

        self._raise_if_called_on_main_thread()
        payload = build_ask_payload(
            question=question,
            history=history,
            model=model,
            instructions=instructions,
            max_output_chars=max_output_chars,
        )
        pending = self._send(
            request_type="voice.ask",
            expected_type="voice.ask.result",
            payload=payload,
        )
        result = self._wait_for(pending, cancel_event=cancel_event)
        if isinstance(result, VoiceWorkerAskResult):
            return result
        raise VoiceWorkerUnavailable("voice worker did not return an ask result")

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
            self._complete_once(
                pending,
                error=VoiceWorkerUnavailable("voice worker request cancelled"),
            )

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
        self,
        pending: _PendingRequest,
        *,
        cancel_event: threading.Event | None = None,
    ) -> (
        VoiceWorkerTranscribeResult
        | VoiceWorkerSpeakResult
        | VoiceWorkerAskResult
        | VoiceWorkerHealthResult
    ):
        wait_seconds = self._request_timeout_seconds + self._WAIT_GRACE_SECONDS
        completed = self._wait_until_complete_or_cancel(
            pending,
            wait_seconds=wait_seconds,
            cancel_event=cancel_event,
        )
        with pending.send_lock:
            with self._lock:
                self._pending.pop(pending.request_id, None)

        if not completed:
            raise VoiceWorkerTimeout(f"voice worker request {pending.request_id} timed out")
        if pending.error is not None:
            raise pending.error
        if pending.result is None:
            raise VoiceWorkerUnavailable("voice worker did not return a result")
        return pending.result

    def _wait_until_complete_or_cancel(
        self,
        pending: _PendingRequest,
        *,
        wait_seconds: float,
        cancel_event: threading.Event | None,
    ) -> bool:
        if cancel_event is None:
            return pending.event.wait(wait_seconds)

        deadline = threading.Event()
        timer = threading.Timer(wait_seconds, deadline.set)
        timer.daemon = True
        timer.start()
        try:
            while not pending.event.is_set():
                if cancel_event.is_set():
                    self._request_cancel(pending)
                    self._complete_once(
                        pending,
                        error=VoiceWorkerUnavailable("voice worker request cancelled"),
                    )
                    return True
                if deadline.wait(0.01):
                    return pending.event.is_set()
            return True
        finally:
            timer.cancel()

    def _request_cancel(self, pending: _PendingRequest) -> None:
        with self._lock:
            if self._pending.get(pending.request_id) is not pending:
                return
            if pending.cancel_sent:
                return
            pending.cancel_sent = True

        def send_cancel_on_main() -> None:
            try:
                self._worker_supervisor.send_request(
                    self._domain,
                    type="voice.cancel",
                    payload={"request_id": pending.request_id},
                    request_id=pending.request_id,
                    timeout_seconds=1.0,
                )
            except Exception:
                return

        self._scheduler.run_on_main(send_cancel_on_main)

    def _complete_send_failure(
        self,
        pending: _PendingRequest,
        error: VoiceWorkerUnavailable,
    ) -> None:
        self._set_available(False, str(error) or "send_failed")
        self._complete_once(pending, error=error)

    def _complete_once(
        self,
        pending: _PendingRequest,
        *,
        result: (
            VoiceWorkerTranscribeResult
            | VoiceWorkerSpeakResult
            | VoiceWorkerAskResult
            | VoiceWorkerHealthResult
            | None
        ) = None,
        error: BaseException | None = None,
    ) -> None:
        with self._lock:
            if self._pending.get(pending.request_id) is not pending:
                return
            if pending.event.is_set():
                return
            pending.result = result
            pending.error = error
            pending.event.set()

    def _complete_with_result(
        self, pending: _PendingRequest, event: WorkerMessageReceivedEvent
    ) -> None:
        try:
            result: (
                VoiceWorkerTranscribeResult
                | VoiceWorkerSpeakResult
                | VoiceWorkerAskResult
                | VoiceWorkerHealthResult
            )
            if event.type == "voice.transcribe.result":
                result = parse_transcribe_result(event.payload)
            elif event.type == "voice.speak.result":
                result = parse_speak_result(event.payload)
            elif event.type == "voice.ask.result":
                result = parse_ask_result(event.payload)
            elif event.type == "voice.health.result":
                result = parse_health_result(event.payload)
            else:
                return
        except Exception as exc:
            self._complete_once(
                pending,
                error=VoiceWorkerUnavailable(f"malformed voice worker result: {exc}"),
            )
            return
        self._complete_once(pending, result=result)

    def _complete_with_worker_error(
        self, pending: _PendingRequest, payload: dict[str, Any]
    ) -> None:
        try:
            worker_error = parse_worker_error(payload)
        except Exception as exc:
            self._complete_once(
                pending,
                error=VoiceWorkerUnavailable(f"malformed voice worker error: {exc}"),
            )
        else:
            if worker_error.code in {"provider_error", "provider_unavailable"}:
                self._set_available(False, worker_error.message or worker_error.code)
            self._complete_once(
                pending,
                error=VoiceWorkerUnavailable(f"{worker_error.code}: {worker_error.message}"),
            )

    def _set_available(self, available: bool, reason: str) -> None:
        with self._lock:
            self._available = available
            self._availability_reason = reason


__all__ = [
    "VoiceWorkerClient",
    "VoiceWorkerTimeout",
    "VoiceWorkerUnavailable",
]
