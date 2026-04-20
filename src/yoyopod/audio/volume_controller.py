"""App-facing shared output volume orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from loguru import logger

from yoyopod.audio.volume import OutputVolumeController

if TYPE_CHECKING:
    from yoyopod.audio.music.backend import MusicBackend
    from yoyopod.app_context import AppContext


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
