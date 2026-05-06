"""Audio capture backends for local voice interactions."""

from __future__ import annotations

import io
import math
import os
import select
import shutil
import struct
import subprocess
import tempfile
import wave
from pathlib import Path
from threading import Event
from typing import Protocol

from loguru import logger

from yoyopod_cli.pi.support.voice_models import (
    VoiceCaptureRequest,
    VoiceCaptureResult,
    VoiceSettings,
)

# VAD tuning constants
_SPEECH_RMS_THRESHOLD = 500  # RMS above this = speech
_SILENCE_RMS_THRESHOLD = 300  # RMS below this = silence
_CHUNK_DURATION_MS = 80  # ms per analysis chunk
_SPEECH_CONFIRM_CHUNKS = 2  # consecutive speech chunks required (filters startup clicks)
_SILENCE_AFTER_SPEECH_MS = 400  # stop after this much silence post-speech
_PRE_SPEECH_TIMEOUT_MS = 3500  # give up if no speech within this window
_HARD_TIMEOUT_EXTRA_S = 1  # extra seconds on top of request timeout
_PIPE_POLL_INTERVAL_S = 0.05


def _rms(chunk: bytes) -> float:
    """Return the RMS amplitude of a 16-bit mono PCM chunk."""
    n = len(chunk) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack(f"<{n}h", chunk[: n * 2])
    return math.sqrt(sum(s * s for s in samples) / n)


def _stream_fileno(stream: object | None) -> int | None:
    """Return a file descriptor for select-based polling when available."""

    if stream is None:
        return None
    fileno = getattr(stream, "fileno", None)
    if fileno is None:
        return None
    try:
        return int(fileno())
    except (AttributeError, io.UnsupportedOperation, OSError, ValueError):
        return None


class AudioCaptureBackend(Protocol):
    """Backend capable of recording one local audio clip."""

    def is_available(self, settings: VoiceSettings) -> bool:
        """Return True when recording is available."""

    def capture(self, request: VoiceCaptureRequest, settings: VoiceSettings) -> VoiceCaptureResult:
        """Capture one audio clip and return its path."""


class NullAudioCaptureBackend:
    """No-op audio capture backend used when recording is unavailable."""

    def is_available(self, settings: VoiceSettings) -> bool:
        return bool(settings.stt_enabled) and not settings.mic_muted

    def capture(self, request: VoiceCaptureRequest, settings: VoiceSettings) -> VoiceCaptureResult:
        return VoiceCaptureResult(audio_path=request.audio_path, recorded=False)


class SubprocessAudioCaptureBackend:
    """Record a WAV clip via arecord with VAD-based early stop."""

    def __init__(self, *, arecord_binary: str = "arecord") -> None:
        self.arecord_binary = arecord_binary
        self._preferred_device: str | None = None

    def is_available(self, settings: VoiceSettings) -> bool:
        if not settings.stt_enabled or settings.mic_muted:
            return False
        return shutil.which(self.arecord_binary) is not None

    def capture(self, request: VoiceCaptureRequest, settings: VoiceSettings) -> VoiceCaptureResult:
        if request.audio_path is not None:
            return VoiceCaptureResult(audio_path=request.audio_path, recorded=False)
        if not self.is_available(settings):
            return VoiceCaptureResult(audio_path=None, recorded=False)

        with tempfile.NamedTemporaryFile(
            prefix="yoyopod-voice-", suffix=".wav", delete=False
        ) as handle:
            audio_path = Path(handle.name)

        max_seconds = float(request.timeout_seconds or settings.record_seconds)
        stop_on_voice_activity = request.mode != "voice_commands_ptt"

        for device in self._device_candidates(settings):
            try:
                recorded = self._capture_vad(
                    audio_path=audio_path,
                    device=device,
                    sample_rate_hz=settings.sample_rate_hz,
                    max_seconds=max_seconds,
                    cancel_event=request.cancel_event,
                    stop_on_voice_activity=stop_on_voice_activity,
                )
            except Exception as exc:
                logger.warning("VAD capture failed on device {}: {}", device, exc)
                continue

            if recorded:
                self._preferred_device = device
                return VoiceCaptureResult(audio_path=audio_path, recorded=True)

        logger.warning("Voice capture failed: no usable ALSA capture device found")
        audio_path.unlink(missing_ok=True)
        return VoiceCaptureResult(audio_path=None, recorded=False)

    def _capture_vad(
        self,
        *,
        audio_path: Path,
        device: str | None,
        sample_rate_hz: int,
        max_seconds: float,
        cancel_event: Event | None,
        stop_on_voice_activity: bool,
    ) -> bool:
        """Stream raw PCM from arecord, stop on silence after speech, write WAV.

        Returns True if audio was captured successfully.
        """
        chunk_frames = int(sample_rate_hz * _CHUNK_DURATION_MS / 1000)
        chunk_bytes = chunk_frames * 2  # 16-bit mono

        silence_chunks_needed = math.ceil(_SILENCE_AFTER_SPEECH_MS / _CHUNK_DURATION_MS)
        pre_speech_chunks_max = math.ceil(_PRE_SPEECH_TIMEOUT_MS / _CHUNK_DURATION_MS)
        hard_max_chunks = math.ceil(
            (max_seconds + _HARD_TIMEOUT_EXTRA_S) * 1000 / _CHUNK_DURATION_MS
        )

        command = [
            self.arecord_binary,
            "-t",
            "raw",
            "-f",
            "S16_LE",
            "-r",
            str(sample_rate_hz),
            "-c",
            "1",
            "-q",
        ]
        if device:
            command.extend(["-D", device])
        command.append("-")

        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        frames = bytearray()
        speech_detected = False
        speech_run = 0  # consecutive loud chunks (filters startup click)
        silence_run = 0
        pre_speech_chunk_count = 0

        try:
            for _chunk_idx in range(hard_max_chunks):
                if cancel_event is not None and cancel_event.is_set():
                    break
                raw = self._read_capture_chunk(
                    stdout=proc.stdout,
                    chunk_bytes=chunk_bytes,
                    cancel_event=cancel_event,
                )
                if not raw:
                    break
                frames.extend(raw)
                rms = _rms(raw)

                if not speech_detected:
                    if rms >= _SPEECH_RMS_THRESHOLD:
                        speech_run += 1
                        if speech_run >= _SPEECH_CONFIRM_CHUNKS:
                            speech_detected = True
                            silence_run = 0
                    else:
                        speech_run = 0
                        if stop_on_voice_activity:
                            pre_speech_chunk_count += 1
                        if stop_on_voice_activity and pre_speech_chunk_count >= pre_speech_chunks_max:
                            break
                else:
                    if stop_on_voice_activity and rms < _SILENCE_RMS_THRESHOLD:
                        silence_run += 1
                        if silence_run >= silence_chunks_needed:
                            break
                    else:
                        silence_run = 0
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()

        if proc.returncode not in (0, -15, None) and not frames:
            return False

        if not frames:
            return False

        with wave.open(str(audio_path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate_hz)
            wf.writeframes(bytes(frames))

        return True

    def _read_capture_chunk(
        self,
        *,
        stdout: object | None,
        chunk_bytes: int,
        cancel_event: Event | None,
    ) -> bytes:
        """Read one PCM chunk while still allowing PTT cancellation to interrupt."""

        if stdout is None:
            return b""

        fileno = _stream_fileno(stdout)
        if fileno is None:
            return stdout.read(chunk_bytes)  # type: ignore[union-attr]

        buffer = bytearray()
        while len(buffer) < chunk_bytes:
            if cancel_event is not None and cancel_event.is_set():
                break
            ready, _, _ = select.select([fileno], [], [], _PIPE_POLL_INTERVAL_S)
            if not ready:
                continue
            chunk = os.read(fileno, chunk_bytes - len(buffer))
            if not chunk:
                break
            buffer.extend(chunk)
        return bytes(buffer)

    def _device_candidates(self, settings: VoiceSettings) -> list[str | None]:
        """Return capture-device candidates, prioritizing any known-good device."""

        discovered_devices = self._scan_devices()
        configured_devices = self._configured_device_candidates(
            settings.capture_device_id,
            discovered_devices,
        )
        candidates: list[str | None] = []
        if self._preferred_device is not None:
            candidates.append(self._preferred_device)
        candidates.extend(configured_devices)
        candidates.extend(discovered_devices)
        candidates.extend([None, "default", "sysdefault"])
        return self._unique_devices(candidates)

    def _scan_devices(self) -> list[str]:
        """Return discovered ALSA capture devices in preferred order."""

        try:
            result = subprocess.run(
                [self.arecord_binary, "-L"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:
            return []

        if result.returncode != 0:
            return []

        parsed_devices: list[str] = []
        for line in result.stdout.splitlines():
            device = line.strip()
            if not device or device.startswith(" "):
                continue
            if device in {"null", "playback", "dmixed"}:
                continue
            if device in {"capture", "array", "default", "sysdefault"}:
                parsed_devices.append(device)
                continue
            if device.startswith(
                (
                    "plughw:",
                    "default:CARD=",
                    "sysdefault:CARD=",
                    "front:CARD=",
                    "dsnoop:CARD=",
                    "hw:",
                )
            ):
                parsed_devices.append(device)
        return sorted(parsed_devices, key=self._device_sort_key)

    def _configured_device_candidates(
        self,
        capture_device_id: str | None,
        discovered_devices: list[str],
    ) -> list[str]:
        """Map the configured capture device to concrete arecord candidates."""

        if not capture_device_id:
            return []

        candidates: list[str] = []
        normalized_target = self._normalize_alsa_name(capture_device_id)
        if self._looks_like_arecord_device(capture_device_id):
            candidates.append(capture_device_id)

        for device in discovered_devices:
            if normalized_target and normalized_target in self._normalize_alsa_name(device):
                candidates.append(device)
        if not candidates:
            if "capture" in discovered_devices:
                candidates.append("capture")
            elif "default" in discovered_devices:
                candidates.append("default")
        return [device for device in self._unique_devices(candidates) if device is not None]

    @staticmethod
    def _looks_like_arecord_device(device: str) -> bool:
        """Return True when the config already looks like an arecord device selector."""

        return device in {"capture", "array", "default", "sysdefault"} or device.startswith(
            (
                "plughw:",
                "hw:",
                "default:",
                "sysdefault:",
                "front:",
                "dsnoop:",
            )
        )

    @staticmethod
    def _normalize_alsa_name(value: str) -> str:
        """Normalize ALSA identifiers so config names match discovered routes."""

        raw = value.strip()
        if raw.upper().startswith("ALSA:"):
            raw = raw.split(":", 1)[1]
        return "".join(ch for ch in raw.lower() if ch.isalnum())

    @staticmethod
    def _device_sort_key(device: str) -> tuple[int, str]:
        """Prefer plughw/default-style routes over raw hw devices."""

        if device == "capture":
            return (0, device)
        if device == "array":
            return (1, device)
        if device == "default":
            return (2, device)
        if device == "sysdefault":
            return (3, device)
        if device.startswith("plughw:"):
            return (4, device)
        if device.startswith("default:CARD="):
            return (5, device)
        if device.startswith("sysdefault:CARD="):
            return (6, device)
        if device.startswith("front:CARD="):
            return (7, device)
        if device.startswith("dsnoop:CARD="):
            return (8, device)
        if device.startswith("hw:"):
            return (9, device)
        return (10, device)

    @staticmethod
    def _unique_devices(devices: list[str | None]) -> list[str | None]:
        """Preserve device order while removing duplicates."""

        unique: list[str | None] = []
        seen: set[str | None] = set()
        for device in devices:
            if device not in seen:
                seen.add(device)
                unique.append(device)
        return unique
