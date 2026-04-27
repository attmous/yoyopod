"""Cloud worker speech backend adapters."""

from __future__ import annotations

import tempfile
import threading
import time
import wave
from pathlib import Path
from typing import Protocol

from loguru import logger

from yoyopod.backends.voice.output import AlsaOutputPlayer
from yoyopod.integrations.voice.models import VoiceSettings, VoiceTranscript
from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerSpeakResult,
    VoiceWorkerTranscribeResult,
)

_TTS_PLAYBACK_TIMEOUT_MIN_SECONDS = 6.0
_TTS_PLAYBACK_TIMEOUT_MAX_SECONDS = 20.0
_TTS_PLAYBACK_TIMEOUT_MARGIN_SECONDS = 2.0


class _VoiceWorkerClient(Protocol):
    """Minimal worker-client surface needed by the backend adapters."""

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
        """Return a transcription result for one local WAV file."""

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
        """Return a synthesized WAV result for one text prompt."""

    @property
    def is_available(self) -> bool:
        """Return whether the worker is currently usable."""


class _PlayWav(Protocol):
    def __call__(
        self,
        audio_path: Path,
        *,
        device_id: str | None = None,
        timeout_seconds: float = 6.0,
        cancel_event: threading.Event | None = None,
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
            and self._client.is_available
        )

    def transcribe(
        self,
        audio_path: Path,
        settings: VoiceSettings,
        *,
        cancel_event: threading.Event | None = None,
    ) -> VoiceTranscript:
        if not self.is_available(settings):
            return _empty_transcript()

        try:
            result = self._client.transcribe(
                audio_path=audio_path,
                sample_rate_hz=settings.sample_rate_hz,
                language="en",
                max_audio_seconds=settings.cloud_worker_max_audio_seconds,
                model=settings.cloud_worker_stt_model,
                cancel_event=cancel_event,
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
            and self._client.is_available
        )

    def speak(
        self,
        text: str,
        settings: VoiceSettings,
        *,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        normalized_text = text.strip()
        if not normalized_text or not self.is_available(settings):
            return False
        if cancel_event is not None and cancel_event.is_set():
            return False

        synthesis_started_at = time.monotonic()
        logger.info(
            "Cloud worker speech synthesis started chars={} model={} voice={}",
            len(normalized_text),
            settings.cloud_worker_tts_model,
            settings.cloud_worker_tts_voice,
        )
        try:
            result = self._client.speak(
                text=normalized_text,
                voice=settings.cloud_worker_tts_voice,
                model=settings.cloud_worker_tts_model,
                instructions=settings.cloud_worker_tts_instructions,
                sample_rate_hz=settings.sample_rate_hz,
                cancel_event=cancel_event,
            )
        except Exception as exc:
            logger.warning("Cloud worker speech synthesis failed: {}", exc)
            return False

        if cancel_event is not None and cancel_event.is_set():
            _unlink_output_audio(result.audio_path)
            return False

        try:
            duration_seconds = _wav_duration_seconds(result.audio_path)
            timeout_seconds = _playback_timeout_seconds(result.audio_path)
            try:
                byte_count = result.audio_path.stat().st_size
            except OSError:
                byte_count = -1
            logger.info(
                "Cloud worker speech synthesis completed audio={} bytes={} duration_s={} "
                "synthesis_ms={:.1f} playback_timeout_s={:.1f}",
                result.audio_path,
                byte_count,
                f"{duration_seconds:.2f}" if duration_seconds is not None else "unknown",
                (time.monotonic() - synthesis_started_at) * 1000,
                timeout_seconds,
            )
            try:
                playback_started_at = time.monotonic()
                play_kwargs: dict[str, object] = {
                    "device_id": settings.speaker_device_id,
                    "timeout_seconds": timeout_seconds,
                }
                if cancel_event is not None:
                    play_kwargs["cancel_event"] = cancel_event
                played = self._play_wav(result.audio_path, **play_kwargs)
            except Exception as exc:
                logger.warning("Cloud worker speech playback failed: {}", exc)
                return False

            if not played:
                logger.warning("Cloud worker speech playback returned false")
                return False
            logger.info(
                "Cloud worker speech playback completed in {:.1f}ms",
                (time.monotonic() - playback_started_at) * 1000,
            )
            return True
        finally:
            _unlink_output_audio(result.audio_path)


def _empty_transcript() -> VoiceTranscript:
    return VoiceTranscript(text="", confidence=0.0, is_final=True)


def _playback_timeout_seconds(audio_path: Path) -> float:
    """Return a bounded timeout long enough for the generated WAV to finish."""

    duration_seconds = _wav_duration_seconds(audio_path)
    if duration_seconds is None:
        return _TTS_PLAYBACK_TIMEOUT_MIN_SECONDS
    return max(
        _TTS_PLAYBACK_TIMEOUT_MIN_SECONDS,
        min(
            _TTS_PLAYBACK_TIMEOUT_MAX_SECONDS,
            duration_seconds + _TTS_PLAYBACK_TIMEOUT_MARGIN_SECONDS,
        ),
    )


def _wav_duration_seconds(audio_path: Path) -> float | None:
    try:
        with wave.open(str(audio_path), "rb") as handle:
            frame_rate = handle.getframerate()
            if frame_rate <= 0:
                return None
            return handle.getnframes() / float(frame_rate)
    except (EOFError, OSError, wave.Error):
        return None


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
