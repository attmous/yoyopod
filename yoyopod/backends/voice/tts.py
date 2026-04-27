"""Text-to-speech backend interfaces."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
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

    def speak(
        self,
        text: str,
        settings: VoiceSettings,
        *,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """Speak text and return True when playback started successfully."""


class NullTextToSpeechBackend:
    """Default no-op backend used until espeak-ng integration is wired."""

    def is_available(self, settings: VoiceSettings) -> bool:
        return bool(settings.tts_enabled)

    def speak(
        self,
        text: str,
        settings: VoiceSettings,
        *,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        if cancel_event is not None and cancel_event.is_set():
            return False
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

    def speak(
        self,
        text: str,
        settings: VoiceSettings,
        *,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        if not text.strip() or not self.is_available(settings):
            return False
        if cancel_event is not None and cancel_event.is_set():
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
            if cancel_event is None:
                result = subprocess.run(
                    render_command,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=False,
                )
            else:
                result = _run_cancellable_render(
                    render_command,
                    timeout_seconds=10.0,
                    cancel_event=cancel_event,
                )
        except Exception as exc:
            logger.warning("espeak-ng playback failed: {}", exc)
            return False
        finally:
            if audio_path is not None and audio_path.exists() and audio_path.stat().st_size == 0:
                audio_path.unlink(missing_ok=True)

        if cancel_event is not None and cancel_event.is_set():
            if audio_path is not None:
                audio_path.unlink(missing_ok=True)
            return False
        if result.returncode != 0 or audio_path is None or not audio_path.exists():
            logger.warning("espeak-ng render failed: {}", result.stderr.strip())
            return False
        try:
            play_kwargs = {"timeout_seconds": 10.0}
            if settings.speaker_device_id:
                play_kwargs["device_id"] = settings.speaker_device_id
            if cancel_event is not None:
                play_kwargs["cancel_event"] = cancel_event
            if not self.output_player.play_wav(audio_path, **play_kwargs):
                logger.warning("espeak-ng playback could not find a usable ALSA device")
                return False
            return True
        finally:
            audio_path.unlink(missing_ok=True)


def _run_cancellable_render(
    command: list[str],
    *,
    timeout_seconds: float,
    cancel_event: threading.Event,
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        returncode = process.poll()
        if returncode is not None:
            stdout, stderr = process.communicate()
            return subprocess.CompletedProcess(
                command,
                returncode,
                stdout or "",
                stderr or "",
            )
        if cancel_event.is_set():
            process.terminate()
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=0.25)
            stdout, stderr = process.communicate()
            return subprocess.CompletedProcess(
                command,
                process.returncode if process.returncode is not None else -15,
                stdout or "",
                stderr or "",
            )
        if time.monotonic() >= deadline:
            process.kill()
            try:
                process.wait(timeout=0.25)
            except subprocess.TimeoutExpired:
                pass
            raise subprocess.TimeoutExpired(command, timeout_seconds)
        time.sleep(0.02)
