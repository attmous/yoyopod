"""App-facing shared output volume orchestration."""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING, Callable

from loguru import logger

if TYPE_CHECKING:
    from yoyopod.backends.music import MusicBackend
    from yoyopod.core import AppContext


_PERCENT_RE = re.compile(r"\[(\d{1,3})%\]")
_ALSA_CARD_RE = re.compile(r"card\s+(\d+):\s*([^\s\[]+)", re.IGNORECASE)


class OutputVolumeController:
    """Own one app-facing output volume across ALSA Master and mpv."""

    def __init__(
        self,
        music_backend: "MusicBackend | None" = None,
        *,
        amixer_binary: str = "amixer",
        aplay_binary: str = "aplay",
        mixer_control: str = "Master",
    ) -> None:
        self.music_backend = music_backend
        self.amixer_binary = amixer_binary
        self.aplay_binary = aplay_binary
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
        resolved = self.get_volume()
        return resolved if resolved is not None else target

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
        """Write one ALSA mixer percentage for the configured control."""

        if self._ensure_wm8960_output_headroom():
            self._last_system_volume_available = True
            return True

        target = max(0, min(100, int(volume)))
        applied = False
        for command in self._amixer_set_candidates(f"{target}%"):
            result = self._run_amixer(command)
            if result is None:
                return False
            if result.returncode == 0:
                applied = True

        if applied:
            self._last_system_volume_available = True
            return True

        if self._last_system_volume_available is not False:
            logger.warning("Failed to set ALSA output volume to {}%", target)
        self._last_system_volume_available = False
        return False

    def _ensure_wm8960_output_headroom(self) -> bool:
        """Pin WM8960 output stages high and leave user volume to mpv."""

        successes = 0
        for card in self._wm8960_output_card_candidates():
            card_successes = 0
            for control in ("Playback", "Speaker", "Headphone"):
                command = [self.amixer_binary, "-c", card, "sset", control, "100%"]
                result = self._run_amixer(command)
                if result is not None and result.returncode == 0:
                    card_successes += 1
            if card_successes:
                successes += card_successes
                break
        return successes > 0

    def _wm8960_output_card_candidates(self) -> list[str]:
        """Return likely ALSA card indices for the WM8960 output codec."""

        detected: list[str] = []
        try:
            result = subprocess.run(
                [self.aplay_binary, "-l"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.SubprocessError):
            result = None

        if result is not None and result.returncode == 0:
            for line in result.stdout.splitlines():
                match = _ALSA_CARD_RE.search(line)
                if match is None:
                    continue
                card, label = match.groups()
                if "wm8960" in line.lower() or "wm8960" in label.lower():
                    detected.append(card)

        candidates: list[str] = []
        for card in [*detected, "1", "0"]:
            if card not in candidates:
                candidates.append(card)
        return candidates

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


class AudioVolumeController:
    """Coordinate one shared output volume across AppContext, ALSA, and mpv."""

    def __init__(
        self,
        *,
        context: "AppContext",
        default_music_volume_provider: Callable[[], int],
        output_volume: OutputVolumeController | None = None,
        music_backend: "MusicBackend | None" = None,
    ) -> None:
        self._context = context
        self._default_music_volume_provider = default_music_volume_provider
        self._output_volume = output_volume
        self._music_backend = music_backend
        self._attach_music_backend_to_output()

    def attach_output_volume(self, output_volume: OutputVolumeController | None) -> None:
        """Attach or replace the low-level ALSA/mpv output-volume adapter."""

        self._output_volume = output_volume
        self._attach_music_backend_to_output()

    def attach_music_backend(self, music_backend: "MusicBackend | None") -> None:
        """Attach or replace the active music backend reference."""

        self._music_backend = music_backend
        self._attach_music_backend_to_output()

    def resolve_default_music_volume(self) -> int:
        """Return the configured startup volume for music output."""

        raw_volume = self._default_music_volume_provider()
        return max(0, min(100, int(raw_volume)))

    def apply_default_music_volume(self) -> None:
        """Apply startup output volume to ALSA and any connected music backend."""

        volume = self.resolve_default_music_volume()

        if self._output_volume is not None:
            if self._output_volume.set_volume(volume):
                resolved = self._output_volume.get_volume()
                self._cache_context_volume(resolved if resolved is not None else volume)
                logger.info("    Startup output volume set to {}%", resolved or volume)
                return
            logger.warning("    Failed to set startup output volume to {}%", volume)

        self._cache_context_volume(volume)

        if self._music_backend is None or not self._music_backend.is_connected:
            return

        if self._music_backend.set_volume(volume):
            logger.info("    Startup music volume set to {}%", volume)
        else:
            logger.warning("    Failed to set startup music volume to {}%", volume)

    def get_output_volume(self, *, refresh_system: bool = True) -> int | None:
        """Return the current shared output volume."""

        if self._output_volume is not None:
            volume = (
                self._output_volume.get_volume()
                if refresh_system
                else self._output_volume.peek_cached_volume()
            )
            if volume is not None:
                self._cache_context_volume(volume)
                return volume
        return self._context.media.playback.volume

    def set_output_volume(self, volume: int) -> bool:
        """Set shared output volume across ALSA and the music backend."""

        target = max(0, min(100, int(volume)))

        applied = False
        if self._output_volume is not None:
            applied = self._output_volume.set_volume(target)
        elif self._music_backend is not None and self._music_backend.is_connected:
            applied = self._music_backend.set_volume(target)

        resolved = self.get_output_volume()
        self._cache_context_volume(resolved if resolved is not None else target)
        return applied

    def get_output_volume_level(self, *, refresh_system: bool = True) -> int:
        """Return the current shared output volume on the 0-10 user scale."""

        return self._context.output_volume_level(
            self.get_output_volume(refresh_system=refresh_system)
        )

    def set_output_volume_level(self, level: int) -> int | None:
        """Set shared output volume from a 0-10 user-facing level."""

        target = self._context.output_volume_from_level(level)
        self.set_output_volume(target)
        resolved = self.get_output_volume(refresh_system=False)
        return resolved if resolved is not None else target

    def volume_level_up(self, step: int = 1) -> int | None:
        """Increase shared output volume by one or more user-facing levels."""

        current_level = self.get_output_volume_level()
        return self.set_output_volume_level(current_level + max(1, int(step)))

    def volume_level_down(self, step: int = 1) -> int | None:
        """Decrease shared output volume by one or more user-facing levels."""

        current_level = self.get_output_volume_level()
        return self.set_output_volume_level(current_level - max(1, int(step)))

    def volume_up(self, step: int = 5) -> int | None:
        """Increase shared output volume."""

        current = self.get_output_volume()
        target = (current if current is not None else 0) + step
        self.set_output_volume(target)
        return self.get_output_volume()

    def volume_down(self, step: int = 5) -> int | None:
        """Decrease shared output volume."""

        current = self.get_output_volume()
        target = (current if current is not None else 0) - step
        self.set_output_volume(target)
        return self.get_output_volume()

    def sync_output_volume_on_music_connect(self, connected: bool, _reason: str) -> None:
        """Reapply the current shared volume whenever mpv reconnects."""

        if not connected or self._output_volume is None:
            return

        volume = self._output_volume.get_volume()
        if volume is None:
            volume = self.resolve_default_music_volume()

        if self._output_volume.sync_music_backend(volume):
            self._cache_context_volume(volume)

    def _cache_context_volume(self, volume: int) -> int:
        """Keep AppContext playback and voice volume caches aligned."""

        return self._context.cache_output_volume(volume)

    def _attach_music_backend_to_output(self) -> None:
        """Attach the current music backend when the output adapter supports it."""

        if self._output_volume is None:
            return
        attach_music_backend = getattr(self._output_volume, "attach_music_backend", None)
        if callable(attach_music_backend):
            attach_music_backend(self._music_backend)
