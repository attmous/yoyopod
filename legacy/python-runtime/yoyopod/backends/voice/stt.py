"""Speech-to-text backend interfaces."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Protocol

from yoyopod_cli.pi.support.voice_models import VoiceSettings, VoiceTranscript


class SpeechToTextBackend(Protocol):
    """Backend capable of transcribing captured voice input."""

    def is_available(self, settings: VoiceSettings) -> bool:
        """Return True when the STT backend can be used."""

    def transcribe(
        self,
        audio_path: Path,
        settings: VoiceSettings,
        *,
        cancel_event: threading.Event | None = None,
    ) -> VoiceTranscript:
        """Return the transcript for the provided audio sample."""


class NullSpeechToTextBackend:
    """No-op backend used when no cloud STT backend is attached."""

    def is_available(self, settings: VoiceSettings) -> bool:
        return False

    def transcribe(
        self,
        audio_path: Path,
        settings: VoiceSettings,
        *,
        cancel_event: threading.Event | None = None,
    ) -> VoiceTranscript:
        return VoiceTranscript(text="", confidence=0.0, is_final=True)
