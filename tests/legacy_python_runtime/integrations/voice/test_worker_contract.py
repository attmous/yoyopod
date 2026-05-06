from __future__ import annotations

from pathlib import Path

import pytest

from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerAskResult,
    VoiceWorkerAskTurn,
    VoiceWorkerError,
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


def test_build_transcribe_payload_uses_file_metadata() -> None:
    payload = build_transcribe_payload(
        audio_path=Path("/tmp/input.wav"),
        sample_rate_hz=16000,
        language="en",
        model="gpt-4o-transcribe",
        prompt="Transcribe YoYoPod commands in English Latin letters.",
        max_audio_seconds=30.0,
    )

    assert payload == {
        "audio_path": "/tmp/input.wav",
        "format": "wav",
        "sample_rate_hz": 16000,
        "channels": 1,
        "language": "en",
        "model": "gpt-4o-transcribe",
        "prompt": "Transcribe YoYoPod commands in English Latin letters.",
        "max_audio_seconds": 30.0,
        "delete_input_on_success": False,
    }


def test_parse_transcribe_result_rejects_missing_text() -> None:
    with pytest.raises(ValueError, match="text"):
        parse_transcribe_result({"confidence": 0.4})


def test_parse_transcribe_result_normalizes_values() -> None:
    result = parse_transcribe_result(
        {
            "text": " play music ",
            "confidence": 0.92,
            "is_final": True,
            "provider_latency_ms": 481,
            "audio_duration_ms": 2100,
        }
    )

    assert result == VoiceWorkerTranscribeResult(
        text="play music",
        confidence=0.92,
        is_final=True,
        provider_latency_ms=481,
        audio_duration_ms=2100,
    )


def test_parse_transcribe_result_accepts_empty_no_speech_text() -> None:
    result = parse_transcribe_result(
        {
            "text": "",
            "confidence": 0.0,
            "is_final": True,
        }
    )

    assert result == VoiceWorkerTranscribeResult(text="", confidence=0.0, is_final=True)


def test_build_speak_payload_includes_provider_options() -> None:
    payload = build_speak_payload(
        text="Playing music",
        voice="alloy",
        model="gpt-4o-mini-tts",
        instructions="Speak clearly.",
        sample_rate_hz=16000,
    )

    assert payload == {
        "text": "Playing music",
        "voice": "alloy",
        "model": "gpt-4o-mini-tts",
        "instructions": "Speak clearly.",
        "format": "wav",
        "sample_rate_hz": 16000,
    }


def test_build_ask_payload_includes_bounded_history_and_policy() -> None:
    payload = build_ask_payload(
        question="  What is playing?  ",
        history=[
            VoiceWorkerAskTurn(role="user", text="  hi  "),
            VoiceWorkerAskTurn(role="assistant", text="  hello  "),
            VoiceWorkerAskTurn(role="system", text="ignore me"),
            VoiceWorkerAskTurn(role="user", text="   "),
        ],
        model="  gpt-4o-mini  ",
        instructions="  Be brief.  ",
        max_output_chars=320,
    )

    assert payload == {
        "question": "What is playing?",
        "history": [
            {"role": "user", "text": "hi"},
            {"role": "assistant", "text": "hello"},
        ],
        "model": "gpt-4o-mini",
        "instructions": "Be brief.",
        "max_output_chars": 320,
    }


def test_parse_ask_result_normalizes_answer() -> None:
    result = parse_ask_result(
        {
            "answer": "  The song is playing.  ",
            "model": "  gpt-4o-mini  ",
            "provider_latency_ms": "150",
        }
    )

    assert result == VoiceWorkerAskResult(
        answer="The song is playing.",
        model="gpt-4o-mini",
        provider_latency_ms=150,
    )


def test_parse_ask_result_rejects_empty_answer() -> None:
    with pytest.raises(ValueError, match="answer"):
        parse_ask_result({"answer": "   "})


def test_parse_speak_result_requires_audio_path() -> None:
    with pytest.raises(ValueError, match="audio_path"):
        parse_speak_result({"duration_ms": 10})


def test_parse_speak_result_normalizes_path() -> None:
    result = parse_speak_result(
        {
            "audio_path": "/tmp/output.wav",
            "format": "wav",
            "sample_rate_hz": 16000,
            "duration_ms": 830,
            "provider_latency_ms": 352,
        }
    )

    assert result == VoiceWorkerSpeakResult(
        audio_path=Path("/tmp/output.wav"),
        format="wav",
        sample_rate_hz=16000,
        duration_ms=830,
        provider_latency_ms=352,
    )


def test_parse_worker_error_preserves_retryable_code() -> None:
    error = parse_worker_error(
        {
            "code": "provider_unavailable",
            "message": "provider down",
            "retryable": True,
        }
    )

    assert error == VoiceWorkerError(
        code="provider_unavailable",
        message="provider down",
        retryable=True,
    )


def test_parse_health_result_normalizes_provider_status() -> None:
    result = parse_health_result(
        {
            "healthy": True,
            "provider": " mock ",
            "message": "ready",
        }
    )

    assert result == VoiceWorkerHealthResult(
        healthy=True,
        provider="mock",
        message="ready",
    )
