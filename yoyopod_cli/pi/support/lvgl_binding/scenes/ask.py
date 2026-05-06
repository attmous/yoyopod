"""LVGL Ask scene bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import _LvglBindingHost


class AskSceneMixin:
    """Bindings for the Ask scene."""

    def ask_build(self: _LvglBindingHost) -> None:
        self._raise_if_error(self.lib.yoyopod_lvgl_ask_build())

    def ask_sync(
        self: _LvglBindingHost,
        *,
        icon_key: str,
        title_text: str,
        subtitle_text: str,
        footer: str,
        voip_state: int,
        battery_percent: int,
        charging: bool,
        power_available: bool,
        accent: tuple[int, int, int],
    ) -> None:
        icon_raw = self._new_char_array(icon_key)
        title_raw = self._new_char_array(title_text)
        subtitle_raw = self._new_char_array(subtitle_text)
        footer_raw = self._new_char_array(footer)
        self._raise_if_error(
            self.lib.yoyopod_lvgl_ask_sync(
                icon_raw,
                title_raw,
                subtitle_raw,
                footer_raw,
                voip_state,
                battery_percent,
                1 if charging else 0,
                1 if power_available else 0,
                self._pack_rgb(accent),
            )
        )

    def ask_destroy(self: _LvglBindingHost) -> None:
        self.lib.yoyopod_lvgl_ask_destroy()
