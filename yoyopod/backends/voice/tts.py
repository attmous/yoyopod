"""Text-to-speech backend interfaces."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Protocol

from loguru import logger

from yoyopod.backends.voice.output import AlsaOutputPlayer
from yoyopod.integrations.voice.models import VoiceSettings


class TextToSpeechBackend(Protocol):
    """Backend capable of speaking a text response."""

    def is_available(self, settings: VoiceSettings) -> bool:
        """Return True when the TTS backend can be used."""

    def speak(self, text: str, settings: VoiceSettings) -> bool:
        """Speak text and return True when playback started successfully."""


class NullTextToSpeechBackend:
    """Default no-op backend used until espeak-ng integration is wired."""

    def is_available(self, settings: VoiceSettings) -> bool:
        return bool(settings.tts_enabled)

    def speak(self, text: str, settings: VoiceSettings) -> bool:
        return bool(text.strip()) and bool(settings.tts_enabled)


class EspeakNgTextToSpeechBackend:
    """Speak short prompts with espeak-ng."""

    def __init__(self, *, binary: str = "espeak-ng") -> None:
        self.binary = binary
        self.output_player = AlsaOutputPlayer()

    def is_available(self, settings: VoiceSettings) -> bool:
        if not settings.tts_enabled or settings.tts_backend != "espeak-ng":
            return False
        return shutil.which(self.binary) is not None

    def speak(self, text: str, settings: VoiceSettings) -> bool:
        if not text.strip() or not self.is_available(settings):
            return False

        audio_path: Path | None = None
        try:
            with NamedTemporaryFile(prefix="yoyopod-tts-", suffix=".wav", delete=False) as handle:
                audio_path = Path(handle.name)
            render_command = [
                self.binary,
                "-w",
                str(audio_path),
                "-s",
                str(settings.tts_rate_wpm),
                "-v",
                settings.tts_voice,
                text,
            ]
            result = subprocess.run(
                render_command,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception as exc:
            logger.warning("espeak-ng playback failed: {}", exc)
            return False
        finally:
            if audio_path is not None and audio_path.exists() and audio_path.stat().st_size == 0:
                audio_path.unlink(missing_ok=True)

        if result.returncode != 0 or audio_path is None or not audio_path.exists():
            logger.warning("espeak-ng render failed: {}", result.stderr.strip())
            return False
        try:
            play_kwargs = {"timeout_seconds": 10.0}
            if settings.speaker_device_id:
                play_kwargs["device_id"] = settings.speaker_device_id
            if not self.output_player.play_wav(audio_path, **play_kwargs):
                logger.warning("espeak-ng playback could not find a usable ALSA device")
                return False
            return True
        finally:
            audio_path.unlink(missing_ok=True)
