"""Speech-to-text backend interfaces."""

from __future__ import annotations

import importlib.util
import json
import wave
from pathlib import Path
from typing import Protocol

from loguru import logger

from yoyopod.integrations.voice.models import VoiceSettings, VoiceTranscript


class SpeechToTextBackend(Protocol):
    """Backend capable of transcribing captured voice input."""

    def is_available(self, settings: VoiceSettings) -> bool:
        """Return True when the STT backend can be used."""

    def transcribe(self, audio_path: Path, settings: VoiceSettings) -> VoiceTranscript:
        """Return the transcript for the provided audio sample."""


class NullSpeechToTextBackend:
    """Default no-op backend used until Vosk integration is wired."""

    def is_available(self, settings: VoiceSettings) -> bool:
        return bool(settings.stt_enabled)

    def transcribe(self, audio_path: Path, settings: VoiceSettings) -> VoiceTranscript:
        return VoiceTranscript(text="", confidence=0.0, is_final=True)


class VoskSpeechToTextBackend:
    """Offline Vosk-based STT backend."""

    def __init__(self) -> None:
        self._model_cache: dict[str, object] = {}

    def is_available(self, settings: VoiceSettings) -> bool:
        if not settings.stt_enabled or settings.stt_backend != "vosk":
            return False
        if importlib.util.find_spec("vosk") is None:
            return False
        return self._resolve_model_path(settings).exists()

    def transcribe(self, audio_path: Path, settings: VoiceSettings) -> VoiceTranscript:
        if not self.is_available(settings):
            return VoiceTranscript(text="", confidence=0.0, is_final=True)

        try:
            from vosk import KaldiRecognizer
        except Exception as exc:
            logger.warning("Vosk import failed: {}", exc)
            return VoiceTranscript(text="", confidence=0.0, is_final=True)

        try:
            with wave.open(str(audio_path), "rb") as handle:
                recognizer = KaldiRecognizer(self._load_model(settings), handle.getframerate())
                while True:
                    chunk = handle.readframes(4000)
                    if not chunk:
                        break
                    recognizer.AcceptWaveform(chunk)
                payload = json.loads(recognizer.FinalResult() or "{}")
        except Exception as exc:
            logger.warning("Vosk transcription failed: {}", exc)
            return VoiceTranscript(text="", confidence=0.0, is_final=True)

        text = str(payload.get("text", "")).strip()
        return VoiceTranscript(text=text, confidence=1.0 if text else 0.0, is_final=True)

    def _load_model(self, settings: VoiceSettings) -> object:
        from vosk import Model

        model_path = str(self._resolve_model_path(settings))
        if not settings.vosk_model_keep_loaded:
            self._model_cache.clear()
            return Model(model_path)
        if model_path not in self._model_cache:
            self._model_cache.clear()
            self._model_cache[model_path] = Model(model_path)
        return self._model_cache[model_path]

    def clear_cache(self) -> None:
        """Drop any cached models held by this backend instance."""

        self._model_cache.clear()

    @staticmethod
    def _resolve_model_path(settings: VoiceSettings) -> Path:
        path = Path(settings.vosk_model_path)
        if path.is_absolute():
            return path
        return Path.cwd() / path
