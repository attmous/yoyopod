"""Cloud worker speech backend adapters."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Protocol

from loguru import logger

from yoyopod.backends.voice.output import AlsaOutputPlayer
from yoyopod.integrations.voice.models import VoiceSettings, VoiceTranscript
from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerSpeakResult,
    VoiceWorkerTranscribeResult,
)


class _VoiceWorkerClient(Protocol):
    """Minimal worker-client surface needed by the backend adapters."""

    def transcribe(
        self,
        *,
        audio_path: Path,
        sample_rate_hz: int,
        language: str,
        max_audio_seconds: float,
    ) -> VoiceWorkerTranscribeResult:
        """Return a transcription result for one local WAV file."""

    def speak(
        self,
        *,
        text: str,
        voice: str,
        model: str,
        instructions: str,
        sample_rate_hz: int,
    ) -> VoiceWorkerSpeakResult:
        """Return a synthesized WAV result for one text prompt."""


class _PlayWav(Protocol):
    def __call__(
        self,
        audio_path: Path,
        *,
        device_id: str | None = None,
        timeout_seconds: float = 6.0,
    ) -> bool:
        """Play one WAV file and return whether playback succeeded."""


class CloudWorkerSpeechToTextBackend:
    """Speech-to-text adapter backed by the voice worker client."""

    def __init__(self, *, client: _VoiceWorkerClient) -> None:
        self._client = client

    def is_available(self, settings: VoiceSettings) -> bool:
        return bool(
            settings.cloud_worker_enabled
            and settings.stt_enabled
            and settings.stt_backend == "cloud-worker"
        )

    def transcribe(self, audio_path: Path, settings: VoiceSettings) -> VoiceTranscript:
        if not self.is_available(settings):
            return _empty_transcript()

        try:
            result = self._client.transcribe(
                audio_path=audio_path,
                sample_rate_hz=settings.sample_rate_hz,
                language="en",
                max_audio_seconds=settings.cloud_worker_max_audio_seconds,
            )
        except Exception as exc:
            logger.warning("Cloud worker transcription failed: {}", exc)
            return _empty_transcript()

        return VoiceTranscript(
            text=result.text,
            confidence=result.confidence,
            is_final=result.is_final,
        )


class CloudWorkerTextToSpeechBackend:
    """Text-to-speech adapter backed by the voice worker client."""

    def __init__(
        self,
        *,
        client: _VoiceWorkerClient,
        play_wav: _PlayWav | None = None,
    ) -> None:
        self._client = client
        self._play_wav = play_wav if play_wav is not None else AlsaOutputPlayer().play_wav

    def is_available(self, settings: VoiceSettings) -> bool:
        return bool(
            settings.cloud_worker_enabled
            and settings.tts_enabled
            and settings.tts_backend == "cloud-worker"
        )

    def speak(self, text: str, settings: VoiceSettings) -> bool:
        normalized_text = text.strip()
        if not normalized_text or not self.is_available(settings):
            return False

        try:
            result = self._client.speak(
                text=normalized_text,
                voice=settings.cloud_worker_tts_voice,
                model=settings.cloud_worker_tts_model,
                instructions=settings.cloud_worker_tts_instructions,
                sample_rate_hz=settings.sample_rate_hz,
            )
        except Exception as exc:
            logger.warning("Cloud worker speech synthesis failed: {}", exc)
            return False

        try:
            try:
                played = self._play_wav(
                    result.audio_path,
                    device_id=settings.speaker_device_id,
                    timeout_seconds=6.0,
                )
            except Exception as exc:
                logger.warning("Cloud worker speech playback failed: {}", exc)
                return False

            if not played:
                logger.warning("Cloud worker speech playback returned false")
                return False
            return True
        finally:
            _unlink_output_audio(result.audio_path)


def _empty_transcript() -> VoiceTranscript:
    return VoiceTranscript(text="", confidence=0.0, is_final=True)


def _unlink_output_audio(path: Path) -> None:
    try:
        resolved_path = path.resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        if (
            path.is_file()
            and resolved_path.suffix.lower() == ".wav"
            and resolved_path.is_relative_to(temp_root)
        ):
            path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("Cloud worker speech output cleanup failed for {}: {}", path, exc)


__all__ = [
    "CloudWorkerSpeechToTextBackend",
    "CloudWorkerTextToSpeechBackend",
]
