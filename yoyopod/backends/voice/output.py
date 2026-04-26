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
        """Return playback-device candidates, prioritizing shared ALSA facade routes."""

        candidates: list[str | None] = []
        discovered_devices = self._scan_devices()
        if configured_device_id:
            candidates.extend(
                self._configured_device_candidates(
                    configured_device_id,
                    discovered_devices,
                )
            )
        if self._preferred_device is not None:
            candidates.append(self._preferred_device)
        candidates.extend(discovered_devices)
        candidates.extend([None, "default", "sysdefault"])
        return self._unique(candidates)

    def _scan_devices(self) -> list[str]:
        """Return discovered ALSA playback devices in preferred order."""

        try:
            result = subprocess.run(
                [self.aplay_binary, "-L"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception:
            return []

        parsed: list[str] = []
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                device = line.strip()
                if not device or line.startswith(" "):
                    continue
                if device in {"null", "capture", "array"}:
                    continue
                if "vc4hdmi" in device.lower():
                    continue
                if device in {"playback", "dmixed", "default", "sysdefault"}:
                    parsed.append(device)
                    continue
                if device.startswith(
                    ("default:CARD=", "sysdefault:CARD=", "plughw:CARD=", "dmix:CARD=")
                ):
                    parsed.append(device)

        return sorted(self._unique(parsed), key=self._device_sort_key)

    def _configured_device_candidates(
        self,
        configured_device_id: str,
        discovered_devices: list[str],
    ) -> list[str]:
        """Map configured labels to concrete ALSA playback candidates."""

        candidates: list[str] = []
        normalized_selector = self._normalize_alsa_selector(configured_device_id)
        if self._looks_like_aplay_device(normalized_selector):
            candidates.append(normalized_selector)
        elif "playback" in discovered_devices:
            candidates.append("playback")
        elif "default" in discovered_devices:
            candidates.append("default")

        normalized_target = self._normalize_alsa_name(configured_device_id)
        for device in discovered_devices:
            if normalized_target and normalized_target in self._normalize_alsa_name(device):
                candidates.append(device)
        return sorted(self._unique(candidates), key=self._device_sort_key)

    @staticmethod
    def _normalize_alsa_selector(value: str) -> str:
        """Strip optional UI prefixes from an ALSA selector."""

        raw = value.strip()
        if raw.upper().startswith("ALSA:"):
            raw = raw.split(":", 1)[1].strip()
        return raw

    @staticmethod
    def _looks_like_aplay_device(device: str) -> bool:
        """Return True when the config already looks like an aplay selector."""

        return device in {"playback", "dmixed", "default", "sysdefault"} or device.startswith(
            (
                "plughw:",
                "hw:",
                "default:",
                "sysdefault:",
                "dmix:",
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
        """Prefer shared/facade routes, then USB-style cards, then direct card routes."""

        if device == "playback":
            return (0, device)
        if device == "dmixed":
            return (1, device)
        if device == "default":
            return (2, device)
        if "CARD=SE" in device and device.startswith("plughw:CARD="):
            return (3, device)
        if "CARD=SE" in device and device.startswith("default:CARD="):
            return (4, device)
        if "CARD=SE" in device and device.startswith("sysdefault:CARD="):
            return (5, device)
        if "CARD=SE" in device:
            return (6, device)
        if device.startswith("plughw:CARD="):
            return (7, device)
        if device.startswith("default:CARD="):
            return (8, device)
        if device.startswith("sysdefault:CARD="):
            return (9, device)
        if device.startswith("dmix:CARD="):
            return (10, device)
        if device == "sysdefault":
            return (11, device)
        return (12, device)

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
