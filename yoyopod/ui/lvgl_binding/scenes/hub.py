"""LVGL hub scene bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import _LvglBindingHost


class HubSceneMixin:
    """Bindings for the hub scene."""

    def hub_build(self: _LvglBindingHost) -> None:
        self._raise_if_error(self.lib.yoyopod_lvgl_hub_build())

    def hub_sync(
        self: _LvglBindingHost,
        *,
        icon_key: str,
        title: str,
        subtitle: str,
        footer: str,
        time_text: str | None,
        accent: tuple[int, int, int],
        selected_index: int,
        total_cards: int,
        voip_state: int,
        battery_percent: int,
        charging: bool,
        power_available: bool,
    ) -> None:
        icon_key_raw = self._get_cached_char_array(
            self._hub_sync_string_cache,
            icon_key,
            max_entries=self.HUB_SYNC_STRING_CACHE_LIMIT,
        )
        title_raw = self._get_cached_char_array(
            self._hub_sync_string_cache,
            title,
            max_entries=self.HUB_SYNC_STRING_CACHE_LIMIT,
        )
        subtitle_raw = self._get_cached_char_array(
            self._hub_sync_string_cache,
            subtitle,
            max_entries=self.HUB_SYNC_STRING_CACHE_LIMIT,
        )
        footer_raw = self._get_cached_char_array(
            self._hub_sync_string_cache,
            footer,
            max_entries=self.HUB_SYNC_STRING_CACHE_LIMIT,
        )
        if time_text:
            time_raw = self._new_char_array(time_text)
        else:
            time_raw = self.ffi.NULL

        self._raise_if_error(
            self.lib.yoyopod_lvgl_hub_sync(
                icon_key_raw,
                title_raw,
                subtitle_raw,
                footer_raw,
                time_raw,
                self._pack_rgb(accent),
                selected_index,
                total_cards,
                voip_state,
                battery_percent,
                1 if charging else 0,
                1 if power_available else 0,
            )
        )

    def hub_destroy(self: _LvglBindingHost) -> None:
        self.lib.yoyopod_lvgl_hub_destroy()
