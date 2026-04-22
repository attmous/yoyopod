"""Canonical shared voice datatypes used by local STT/TTS flows."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event


@dataclass(slots=True, frozen=True)
class VoiceSettings:
    """Voice-related runtime settings passed into backends."""

    commands_enabled: bool = True
    ai_requests_enabled: bool = True
    screen_read_enabled: bool = False
    stt_enabled: bool = True
    tts_enabled: bool = True
    mic_muted: bool = False
    output_volume: int = 50
    stt_backend: str = "vosk"
    tts_backend: str = "espeak-ng"
    vosk_model_path: str = "models/vosk-model-small-en-us"
    vosk_model_keep_loaded: bool = True
    speaker_device_id: str | None = None
    capture_device_id: str | None = None
    sample_rate_hz: int = 16000
    record_seconds: int = 4
    tts_rate_wpm: int = 155
    tts_voice: str = "en"


@dataclass(slots=True, frozen=True)
class VoiceCaptureRequest:
    """Request to capture or transcribe audio for a voice interaction."""

    mode: str
    audio_path: Path | None = None
    prompt: str = ""
    timeout_seconds: float = 4.0
    cancel_event: Event | None = None


@dataclass(slots=True, frozen=True)
class VoiceTranscript:
    """Normalized STT result returned by a speech backend."""

    text: str
    confidence: float = 0.0
    is_final: bool = True


@dataclass(slots=True, frozen=True)
class VoiceCaptureResult:
    """Result from capturing one local audio sample."""

    audio_path: Path | None
    recorded: bool = False


__all__ = [
    "VoiceCaptureRequest",
    "VoiceCaptureResult",
    "VoiceSettings",
    "VoiceTranscript",
]
