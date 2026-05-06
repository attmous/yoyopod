"""Contract helpers for the cloud voice worker boundary."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(slots=True, frozen=True)
class VoiceWorkerTranscribeResult:
    """Normalized transcription result returned by a voice worker."""

    text: str
    confidence: float
    is_final: bool
    provider_latency_ms: int | None = None
    audio_duration_ms: int | None = None


@dataclass(slots=True, frozen=True)
class VoiceWorkerSpeakResult:
    """Normalized speech synthesis result returned by a voice worker."""

    audio_path: Path
    format: str
    sample_rate_hz: int
    duration_ms: int | None = None
    provider_latency_ms: int | None = None


@dataclass(slots=True, frozen=True)
class VoiceWorkerAskTurn:
    """One normalized conversation turn sent to a voice worker."""

    role: str
    text: str


@dataclass(slots=True, frozen=True)
class VoiceWorkerAskResult:
    """Normalized answer result returned by a voice worker."""

    answer: str
    model: str
    provider_latency_ms: int | None = None


@dataclass(slots=True, frozen=True)
class VoiceWorkerHealthResult:
    """Normalized health result returned by a voice worker."""

    healthy: bool
    provider: str
    message: str = ""


@dataclass(slots=True, frozen=True)
class VoiceWorkerError:
    """Normalized error returned by a voice worker."""

    code: str
    message: str
    retryable: bool = False


def build_transcribe_payload(
    audio_path: Path,
    sample_rate_hz: int,
    language: str,
    max_audio_seconds: float,
    model: str = "",
    prompt: str = "",
) -> dict[str, Any]:
    """Build a worker payload for audio transcription."""

    payload: dict[str, Any] = {
        "audio_path": audio_path.as_posix(),
        "format": "wav",
        "sample_rate_hz": sample_rate_hz,
        "channels": 1,
        "language": language,
        "max_audio_seconds": max_audio_seconds,
        "delete_input_on_success": False,
    }
    if model:
        payload["model"] = model
    if prompt:
        payload["prompt"] = prompt
    return payload


def build_speak_payload(
    text: str,
    voice: str,
    model: str,
    instructions: str,
    sample_rate_hz: int,
) -> dict[str, Any]:
    """Build a worker payload for speech synthesis."""

    return {
        "text": text,
        "voice": voice,
        "model": model,
        "instructions": instructions,
        "format": "wav",
        "sample_rate_hz": sample_rate_hz,
    }


def build_ask_payload(
    question: str,
    history: list[VoiceWorkerAskTurn],
    model: str,
    instructions: str,
    max_output_chars: int,
) -> dict[str, Any]:
    """Build a worker payload for question answering."""

    return {
        "question": question.strip(),
        "history": [
            {"role": turn.role, "text": text}
            for turn in history
            if turn.role in {"user", "assistant"} and (text := turn.text.strip())
        ],
        "model": model.strip(),
        "instructions": instructions.strip(),
        "max_output_chars": int(max_output_chars),
    }


def parse_transcribe_result(payload: Mapping[str, Any]) -> VoiceWorkerTranscribeResult:
    """Parse and normalize a transcription response payload."""

    text = _required_string(payload, "text").strip()

    return VoiceWorkerTranscribeResult(
        text=text,
        confidence=float(payload.get("confidence", 0.0)),
        is_final=bool(payload.get("is_final", True)),
        provider_latency_ms=_optional_int(payload, "provider_latency_ms"),
        audio_duration_ms=_optional_int(payload, "audio_duration_ms"),
    )


def parse_speak_result(payload: Mapping[str, Any]) -> VoiceWorkerSpeakResult:
    """Parse and normalize a speech synthesis response payload."""

    audio_path = _required_string(payload, "audio_path").strip()
    if not audio_path:
        raise ValueError("audio_path must be a non-empty string")

    return VoiceWorkerSpeakResult(
        audio_path=Path(audio_path),
        format=str(payload.get("format", "wav")),
        sample_rate_hz=int(payload.get("sample_rate_hz", 16000)),
        duration_ms=_optional_int(payload, "duration_ms"),
        provider_latency_ms=_optional_int(payload, "provider_latency_ms"),
    )


def parse_ask_result(payload: Mapping[str, Any]) -> VoiceWorkerAskResult:
    """Parse and normalize a question answering response payload."""

    answer = _required_string(payload, "answer").strip()
    if not answer:
        raise ValueError("answer must be a non-empty string")

    return VoiceWorkerAskResult(
        answer=answer,
        model=str(payload.get("model", "")).strip(),
        provider_latency_ms=_optional_int(payload, "provider_latency_ms"),
    )


def parse_health_result(payload: Mapping[str, Any]) -> VoiceWorkerHealthResult:
    """Parse and normalize a worker health response payload."""

    provider = _required_string(payload, "provider").strip()
    if not provider:
        raise ValueError("provider must be a non-empty string")
    return VoiceWorkerHealthResult(
        healthy=bool(payload.get("healthy", False)),
        provider=provider,
        message=str(payload.get("message", "")).strip(),
    )


def parse_worker_error(payload: Mapping[str, Any]) -> VoiceWorkerError:
    """Parse and normalize an error response payload."""

    code = _required_string(payload, "code").strip()
    message = _required_string(payload, "message").strip()
    if not code:
        raise ValueError("code must be a non-empty string")
    if not message:
        raise ValueError("message must be a non-empty string")

    return VoiceWorkerError(
        code=code,
        message=message,
        retryable=bool(payload.get("retryable", False)),
    )


def _required_string(payload: Mapping[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _optional_int(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if value is None:
        return None
    return int(value)


__all__ = [
    "VoiceWorkerAskResult",
    "VoiceWorkerAskTurn",
    "VoiceWorkerError",
    "VoiceWorkerHealthResult",
    "VoiceWorkerSpeakResult",
    "VoiceWorkerTranscribeResult",
    "build_ask_payload",
    "build_speak_payload",
    "build_transcribe_payload",
    "parse_ask_result",
    "parse_health_result",
    "parse_speak_result",
    "parse_transcribe_result",
    "parse_worker_error",
]
