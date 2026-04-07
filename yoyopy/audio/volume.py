"""Shared output-volume control across ALSA and the music backend."""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from yoyopy.audio.music.backend import MusicBackend


_PERCENT_RE = re.compile(r"\[(\d{1,3})%\]")


class OutputVolumeController:
    """Own one app-facing output volume across ALSA Master and mpv."""

    def __init__(
        self,
        music_backend: "MusicBackend | None" = None,
        *,
        amixer_binary: str = "amixer",
        mixer_control: str = "Master",
    ) -> None:
        self.music_backend = music_backend
        self.amixer_binary = amixer_binary
        self.mixer_control = mixer_control
        self._last_requested_volume: int | None = None

    def attach_music_backend(self, music_backend: "MusicBackend | None") -> None:
        """Attach or replace the active music backend."""
        self.music_backend = music_backend

    def get_volume(self) -> int | None:
        """Return the best current app-facing output volume."""
        system_volume = self.get_system_volume()
        if system_volume is not None:
            self._last_requested_volume = system_volume
            return system_volume

        if self._last_requested_volume is not None:
            return self._last_requested_volume

        if self.music_backend is not None:
            backend_volume = self.music_backend.get_volume()
            if backend_volume is not None:
                self._last_requested_volume = backend_volume
                return backend_volume

        return self._last_requested_volume

    def set_volume(self, volume: int) -> bool:
        """Set ALSA Master and, when connected, the music backend volume."""
        target = max(0, min(100, int(volume)))
        self._last_requested_volume = target

        system_ok = self.set_system_volume(target)
        backend_ok = self.sync_music_backend(target)
        return system_ok or backend_ok

    def step_volume(self, delta: int) -> int | None:
        """Adjust output volume by a signed delta."""
        current = self.get_volume()
        if current is None:
            current = self._last_requested_volume if self._last_requested_volume is not None else 0
        target = max(0, min(100, current + delta))
        self.set_volume(target)
        return self.get_volume() if self.get_volume() is not None else target

    def sync_music_backend(self, volume: int | None = None) -> bool:
        """Push the current shared volume into the live music backend."""
        if self.music_backend is None or not self.music_backend.is_connected:
            return False

        target = volume
        if target is None:
            target = self.get_volume()
        if target is None:
            target = self._last_requested_volume
        if target is None:
            return False

        return self.music_backend.set_volume(target)

    def get_system_volume(self) -> int | None:
        """Read the current ALSA mixer percentage for the configured control."""
        try:
            result = subprocess.run(
                [self.amixer_binary, "sget", self.mixer_control],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except FileNotFoundError:
            logger.debug("amixer not found; system output volume unavailable")
            return None
        except Exception as exc:
            logger.warning("Failed to read ALSA output volume: {}", exc)
            return None

        if result.returncode != 0:
            logger.warning("amixer sget {} failed: {}", self.mixer_control, result.stderr.strip())
            return None

        match = _PERCENT_RE.search(result.stdout)
        if match is None:
            logger.warning("Could not parse ALSA output volume from amixer output")
            return None
        return int(match.group(1))

    def set_system_volume(self, volume: int) -> bool:
        """Write one ALSA mixer percentage for the configured control."""
        target = max(0, min(100, int(volume)))
        try:
            result = subprocess.run(
                [self.amixer_binary, "sset", self.mixer_control, f"{target}%"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except FileNotFoundError:
            logger.debug("amixer not found; skipping ALSA output volume write")
            return False
        except Exception as exc:
            logger.warning("Failed to set ALSA output volume: {}", exc)
            return False

        if result.returncode != 0:
            logger.warning("amixer sset {} {}% failed: {}", self.mixer_control, target, result.stderr.strip())
            return False
        return True
