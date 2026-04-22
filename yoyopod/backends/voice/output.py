"""ALSA-backed playback helpers for voice prompts and attention tones."""

from __future__ import annotations

import shutil
import subprocess
import threading
from pathlib import Path

from loguru import logger

_PLAYBACK_LOCK = threading.Lock()


class AlsaOutputPlayer:
    """Play short WAV prompts through the best available ALSA playback device."""

    def __init__(self, *, aplay_binary: str = "aplay") -> None:
        self.aplay_binary = aplay_binary
        self._preferred_device: str | None = None

    def is_available(self) -> bool:
        """Return True when `aplay` is installed."""

        return shutil.which(self.aplay_binary) is not None

    def play_wav(
        self,
        audio_path: Path,
        *,
        device_id: str | None = None,
        timeout_seconds: float = 6.0,
    ) -> bool:
        """Play one WAV file, retrying through likely ALSA devices."""

        if not self.is_available():
            return False

        with _PLAYBACK_LOCK:
            return self._play_wav_locked(
                audio_path,
                device_id=device_id,
                timeout_seconds=timeout_seconds,
            )

    def _play_wav_locked(
        self,
        audio_path: Path,
        *,
        device_id: str | None,
        timeout_seconds: float = 6.0,
    ) -> bool:
        """Inner play implementation, called with _PLAYBACK_LOCK held."""

        for device in self._device_candidates(device_id):
            command = [self.aplay_binary, "-q"]
            if device:
                command.extend(["-D", device])
            command.append(str(audio_path))
            try:
                result = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=timeout_seconds,
                    check=False,
                )
            except Exception as exc:
                logger.debug("ALSA playback failed for {}: {}", device or "default", exc)
                continue
            if result.returncode == 0:
                self._preferred_device = device
                return True
        return False

    def _device_candidates(self, configured_device_id: str | None) -> list[str | None]:
        """Return playback-device candidates, prioritizing known-good USB routes."""

        candidates: list[str | None] = []
        if configured_device_id:
            normalized = configured_device_id.strip()
            if normalized.upper().startswith("ALSA:"):
                normalized = normalized.split(":", 1)[1].strip()
            candidates.append(normalized or None)
        if self._preferred_device is not None:
            candidates.append(self._preferred_device)

        try:
            result = subprocess.run(
                [self.aplay_binary, "-L"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:
            candidates.extend([None, "default"])
            return self._unique(candidates)

        parsed: list[str] = []
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                device = line.strip()
                if not device or line.startswith(" "):
                    continue
                if device in {"null", "default", "sysdefault"}:
                    continue
                if "vc4hdmi" in device.lower():
                    continue
                if device.startswith(
                    ("default:CARD=", "sysdefault:CARD=", "plughw:CARD=", "dmix:CARD=")
                ):
                    parsed.append(device)

        preferred = [device for device in parsed if "CARD=SE" in device]
        fallback = [device for device in parsed if "CARD=SE" not in device]
        candidates.extend(preferred)
        candidates.extend(fallback)
        candidates.extend([None, "default", "sysdefault"])
        return self._unique(candidates)

    @staticmethod
    def _unique(devices: list[str | None]) -> list[str | None]:
        """Preserve device order while removing duplicates."""

        unique: list[str | None] = []
        seen: set[str | None] = set()
        for device in devices:
            if device not in seen:
                seen.add(device)
                unique.append(device)
        return unique
