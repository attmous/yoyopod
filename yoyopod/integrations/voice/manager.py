"""Canonical domain-owned voice manager for local speech and audio composition."""

from __future__ import annotations

import threading
from pathlib import Path

from yoyopod.backends.voice import (
    AudioCaptureBackend,
    EspeakNgTextToSpeechBackend,
    SpeechToTextBackend,
    SubprocessAudioCaptureBackend,
    TextToSpeechBackend,
    VoskSpeechToTextBackend,
)
from yoyopod.integrations.voice.models import (
    VoiceCaptureRequest,
    VoiceCaptureResult,
    VoiceSettings,
    VoiceTranscript,
)
from yoyopod.integrations.voice.commands import VoiceCommandMatch, match_voice_command


class VoiceManager:
    """Compose local capture, STT, and TTS services for app runtime use."""

    def __init__(
        self,
        *,
        settings: VoiceSettings,
        capture_backend: AudioCaptureBackend | None = None,
        stt_backend: SpeechToTextBackend | None = None,
        tts_backend: TextToSpeechBackend | None = None,
    ) -> None:
        self.settings = settings
        self.capture_backend = capture_backend or SubprocessAudioCaptureBackend()
        self.stt_backend = stt_backend or VoskSpeechToTextBackend()
        self.tts_backend = tts_backend or EspeakNgTextToSpeechBackend()

    def capture_available(self) -> bool:
        """Return True when local audio capture is available."""

        return self.capture_backend.is_available(self.settings)

    def stt_available(self) -> bool:
        """Return True when the configured STT backend is available."""

        return self.stt_backend.is_available(self.settings)

    def tts_available(self) -> bool:
        """Return True when the configured TTS backend is available."""

        return self.tts_backend.is_available(self.settings)

    def capture_audio(self, request: VoiceCaptureRequest) -> VoiceCaptureResult:
        """Record one local audio sample."""

        return self.capture_backend.capture(request, self.settings)

    def transcribe(
        self,
        audio_path: Path,
        *,
        cancel_event: threading.Event | None = None,
    ) -> VoiceTranscript:
        """Transcribe an audio sample using the configured STT backend."""

        return self.stt_backend.transcribe(
            audio_path,
            self.settings,
            cancel_event=cancel_event,
        )

    def capture_and_transcribe(self, request: VoiceCaptureRequest) -> VoiceTranscript:
        """Capture a short audio sample and return a transcript."""

        capture_result = self.capture_audio(request)
        if capture_result.audio_path is None:
            return VoiceTranscript(text="", confidence=0.0, is_final=True)
        should_cleanup = capture_result.recorded and request.audio_path is None
        try:
            return self.transcribe(capture_result.audio_path, cancel_event=request.cancel_event)
        finally:
            if should_cleanup:
                capture_result.audio_path.unlink(missing_ok=True)

    def match_command(self, transcript: str) -> VoiceCommandMatch:
        """Map a transcript to the deterministic local command set."""

        return match_voice_command(transcript)

    def speak(
        self,
        text: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """Speak text using the configured TTS backend."""

        return self.tts_backend.speak(text, self.settings, cancel_event=cancel_event)

    def release_resources(self) -> None:
        """Drop backend-owned caches when this service is being replaced."""

        clear_cache = getattr(self.stt_backend, "clear_cache", None)
        if callable(clear_cache):
            clear_cache()


VoiceService = VoiceManager

__all__ = ["VoiceManager", "VoiceService"]
