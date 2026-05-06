"""LVGL now-playing scene bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import _LvglBindingHost


class NowPlayingSceneMixin:
    """Bindings for now-playing transport scene."""

    def now_playing_build(self: _LvglBindingHost) -> None:
        self._raise_if_error(self.lib.yoyopod_lvgl_now_playing_build())

    def now_playing_sync(
        self: _LvglBindingHost,
        *,
        title_text: str,
        artist_text: str,
        state_text: str,
        footer: str,
        progress_permille: int,
        voip_state: int,
        battery_percent: int,
        charging: bool,
        power_available: bool,
        accent: tuple[int, int, int],
    ) -> None:
        title_raw = self.ffi.new("char[]", title_text.encode("utf-8"))
        artist_raw = self.ffi.new("char[]", artist_text.encode("utf-8"))
        state_raw = self.ffi.new("char[]", state_text.encode("utf-8"))
        footer_raw = self.ffi.new("char[]", footer.encode("utf-8"))

        self._raise_if_error(
            self.lib.yoyopod_lvgl_now_playing_sync(
                title_raw,
                artist_raw,
                state_raw,
                footer_raw,
                max(0, min(1000, int(progress_permille))),
                voip_state,
                battery_percent,
                1 if charging else 0,
                1 if power_available else 0,
                self._pack_rgb(accent),
            )
        )

    def now_playing_destroy(self: _LvglBindingHost) -> None:
        self.lib.yoyopod_lvgl_now_playing_destroy()
