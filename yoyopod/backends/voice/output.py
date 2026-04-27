"""ALSA-backed playback helpers for voice prompts and attention tones."""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
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
        block_if_busy: bool = True,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """Play one WAV file, retrying through likely ALSA devices."""

        if not self.is_available():
            return False
        if cancel_event is not None and cancel_event.is_set():
            return False

        if cancel_event is not None and block_if_busy:
            while not _PLAYBACK_LOCK.acquire(blocking=False):
                if cancel_event.is_set():
                    logger.debug("ALSA playback skipped because cancellation was requested")
                    return False
                time.sleep(0.02)
            lock_acquired = True
        else:
            lock_acquired = _PLAYBACK_LOCK.acquire(blocking=block_if_busy)
        if not lock_acquired:
            logger.debug("ALSA playback skipped because another playback is active")
            return False
        try:
            if cancel_event is not None and cancel_event.is_set():
                return False
            return self._play_wav_locked(
                audio_path,
                device_id=device_id,
                timeout_seconds=timeout_seconds,
                cancel_event=cancel_event,
            )
        finally:
            _PLAYBACK_LOCK.release()

    def _play_wav_locked(
        self,
        audio_path: Path,
        *,
        device_id: str | None,
        timeout_seconds: float = 6.0,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """Inner play implementation, called with _PLAYBACK_LOCK held."""

        for device in self._device_candidates(device_id, cancel_event=cancel_event):
            if cancel_event is not None and cancel_event.is_set():
                return False
            command = [self.aplay_binary, "-q"]
            if device:
                command.extend(["-D", device])
            command.append(str(audio_path))
            started_at = time.monotonic()
            try:
                if cancel_event is None:
                    result = subprocess.run(
                        command,
                        capture_output=True,
                        text=True,
                        timeout=timeout_seconds,
                        check=False,
                    )
                else:
                    result = self._run_cancellable_playback(
                        command,
                        timeout_seconds=timeout_seconds,
                        cancel_event=cancel_event,
                    )
            except subprocess.TimeoutExpired:
                logger.warning(
                    "ALSA playback timed out for {} after {:.1f}s",
                    device or "default",
                    timeout_seconds,
                )
                continue
            except Exception as exc:
                logger.debug("ALSA playback failed for {}: {}", device or "default", exc)
                continue
            elapsed_ms = (time.monotonic() - started_at) * 1000
            if result.returncode == 0:
                logger.info(
                    "ALSA playback succeeded on {} in {:.1f}ms",
                    device or "default",
                    elapsed_ms,
                )
                self._preferred_device = device
                return True
            if cancel_event is not None and cancel_event.is_set():
                logger.info("ALSA playback cancelled on {}", device or "default")
                return False
            stderr = result.stderr.strip().replace("\n", " ")[:180]
            logger.warning(
                "ALSA playback failed on {} rc={} elapsed_ms={:.1f} stderr={}",
                device or "default",
                result.returncode,
                elapsed_ms,
                stderr or "<empty>",
            )
        return False

    def _run_cancellable_playback(
        self,
        command: list[str],
        *,
        timeout_seconds: float,
        cancel_event: threading.Event,
    ) -> subprocess.CompletedProcess[str]:
        """Run one aplay process while polling for cancellation."""

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

    def _device_candidates(
        self,
        configured_device_id: str | None,
        *,
        cancel_event: threading.Event | None = None,
    ) -> list[str | None]:
        """Return playback-device candidates, prioritizing shared ALSA facade routes."""

        if cancel_event is not None and cancel_event.is_set():
            return []
        candidates: list[str | None] = []
        discovered_devices = self._scan_devices(cancel_event=cancel_event)
        if cancel_event is not None and cancel_event.is_set():
            return []
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

    def _scan_devices(
        self,
        *,
        cancel_event: threading.Event | None = None,
    ) -> list[str]:
        """Return discovered ALSA playback devices in preferred order."""

        if cancel_event is not None and cancel_event.is_set():
            return []
        try:
            result = subprocess.run(
                [self.aplay_binary, "-L"],
                capture_output=True,
                text=True,
                timeout=1 if cancel_event is not None else 5,
                check=False,
            )
        except Exception:
            return []

        if cancel_event is not None and cancel_event.is_set():
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

        normalized_target = self._normalize_alsa_name(configured_device_id)
        for device in discovered_devices:
            if normalized_target and normalized_target in self._normalize_alsa_name(device):
                candidates.append(device)
        if not candidates:
            if "playback" in discovered_devices:
                candidates.append("playback")
            elif "default" in discovered_devices:
                candidates.append("default")
        return [device for device in self._unique(candidates) if device is not None]

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
