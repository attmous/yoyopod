"""Shared output-volume control across ALSA and the music backend."""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from yoyopod.audio.music.backend import MusicBackend


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
        self._last_system_volume_available: bool | None = None

    def attach_music_backend(self, music_backend: "MusicBackend | None") -> None:
        """Attach or replace the active music backend."""
        self.music_backend = music_backend

    def peek_cached_volume(self) -> int | None:
        """Return the last known shared volume without touching ALSA or mpv."""
        return self._last_requested_volume

    def get_volume(self) -> int | None:
        """Return the best current app-facing output volume."""
        if self.music_backend is not None:
            backend_volume = self.music_backend.get_volume()
            if backend_volume is not None:
                self._last_requested_volume = backend_volume
                return backend_volume

        system_volume = self.get_system_volume()
        if system_volume is not None:
            self._last_requested_volume = system_volume
            return system_volume

        if self._last_requested_volume is not None:
            return self._last_requested_volume

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
        for command in self._amixer_get_candidates():
            result = self._run_amixer(command)
            if result is None:
                return None
            if result.returncode != 0:
                continue

            match = _PERCENT_RE.search(result.stdout)
            if match is not None:
                self._last_system_volume_available = True
                return int(match.group(1))

        if self._last_system_volume_available is not False:
            logger.warning("Could not read ALSA output volume for {}", self.mixer_control)
        self._last_system_volume_available = False
        return None

    def set_system_volume(self, volume: int) -> bool:
        """Keep WM8960 output stages at calibrated headroom when available."""
        if self._ensure_wm8960_output_headroom():
            self._last_system_volume_available = True
            return True

        target = max(0, min(100, int(volume)))
        for command in self._amixer_set_candidates(f"{target}%"):
            result = self._run_amixer(command)
            if result is None:
                return False
            if result.returncode == 0:
                self._last_system_volume_available = True
                return True

        if self._last_system_volume_available is not False:
            logger.warning("Failed to set ALSA output volume to {}%", target)
        self._last_system_volume_available = False
        return False

    def _ensure_wm8960_output_headroom(self) -> bool:
        """Pin WM8960 output stages high and leave user volume to mpv."""
        successes = 0
        for command in (
            [self.amixer_binary, "-c", "1", "sset", "Playback", "100%"],
            [self.amixer_binary, "-c", "1", "sset", "Speaker", "100%"],
            [self.amixer_binary, "-c", "1", "sset", "Headphone", "100%"],
        ):
            result = self._run_amixer(command)
            if result is not None and result.returncode == 0:
                successes += 1
        return successes > 0

    def _amixer_get_candidates(self) -> list[list[str]]:
        """Return candidate amixer reads in priority order."""
        return self._commands_for_targets(
            "sget",
            "",
            targets=[
                (None, self.mixer_control),
                ("1", self.mixer_control),
                ("0", self.mixer_control),
                (None, "Playback"),
                ("1", "Playback"),
                ("0", "Playback"),
                ("1", "Headset"),
                ("0", "Headset"),
                ("1", "Speaker"),
                ("1", "Headphone"),
                ("0", "Speaker"),
                ("0", "Headphone"),
            ],
        )

    def _amixer_set_candidates(self, value: str) -> list[list[str]]:
        """Return candidate amixer writes for active output controls."""
        return self._commands_for_targets(
            "sset",
            value,
            targets=[
                (None, self.mixer_control),
                ("1", self.mixer_control),
                ("0", self.mixer_control),
                (None, "Playback"),
                ("1", "Playback"),
                ("0", "Playback"),
                ("1", "Headset"),
                ("0", "Headset"),
                ("1", "Speaker"),
                ("1", "Headphone"),
                ("0", "Speaker"),
                ("0", "Headphone"),
            ],
        )

    def _commands_for_targets(
        self,
        verb: str,
        value: str,
        *,
        targets: list[tuple[str | None, str]],
    ) -> list[list[str]]:
        """Build unique amixer commands for one ordered target list."""
        candidates: list[list[str]] = []
        for card, control in targets:
            command = [self.amixer_binary]
            if card is not None:
                command.extend(["-c", card])
            command.extend([verb, control])
            if value:
                command.append(value)
            candidates.append(command)

        unique: list[list[str]] = []
        seen: set[tuple[str, ...]] = set()
        for command in candidates:
            key = tuple(command)
            if key not in seen:
                seen.add(key)
                unique.append(command)
        return unique

    def _run_amixer(self, command: list[str]) -> subprocess.CompletedProcess[str] | None:
        """Run one amixer command and normalize failure handling."""
        try:
            return subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except FileNotFoundError:
            logger.debug("amixer not found; ALSA output volume unavailable")
            return None
        except Exception as exc:
            logger.warning("Failed to run amixer command {}: {}", command, exc)
            return None
