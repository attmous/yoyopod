"""LVGL listen scene bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import _LvglBindingHost


class ListenSceneMixin:
    """Bindings for the listen/list scene."""

    def listen_build(self: _LvglBindingHost) -> None:
        self._raise_if_error(self.lib.yoyopod_lvgl_listen_build())

    def listen_sync(
        self: _LvglBindingHost,
        *,
        page_text: str | None,
        footer: str,
        items: list[str],
        subtitles: list[str],
        icon_keys: list[str],
        selected_index: int,
        voip_state: int,
        battery_percent: int,
        charging: bool,
        power_available: bool,
        accent: tuple[int, int, int],
        empty_title: str,
        empty_subtitle: str,
    ) -> None:
        normalized_items = list(items[:4])
        while len(normalized_items) < 4:
            normalized_items.append("")
        normalized_subtitles = list(subtitles[:4])
        while len(normalized_subtitles) < 4:
            normalized_subtitles.append("")
        normalized_icon_keys = list(icon_keys[:4])
        while len(normalized_icon_keys) < 4:
            normalized_icon_keys.append("")

        page_text_raw = (
            self.ffi.new("char[]", page_text.encode("utf-8")) if page_text else self.ffi.NULL
        )
        footer_raw = self.ffi.new("char[]", footer.encode("utf-8"))
        item_0_raw = self.ffi.new("char[]", normalized_items[0].encode("utf-8"))
        item_1_raw = self.ffi.new("char[]", normalized_items[1].encode("utf-8"))
        item_2_raw = self.ffi.new("char[]", normalized_items[2].encode("utf-8"))
        item_3_raw = self.ffi.new("char[]", normalized_items[3].encode("utf-8"))
        subtitle_0_raw = self.ffi.new("char[]", normalized_subtitles[0].encode("utf-8"))
        subtitle_1_raw = self.ffi.new("char[]", normalized_subtitles[1].encode("utf-8"))
        subtitle_2_raw = self.ffi.new("char[]", normalized_subtitles[2].encode("utf-8"))
        subtitle_3_raw = self.ffi.new("char[]", normalized_subtitles[3].encode("utf-8"))
        icon_0_raw = self.ffi.new("char[]", normalized_icon_keys[0].encode("utf-8"))
        icon_1_raw = self.ffi.new("char[]", normalized_icon_keys[1].encode("utf-8"))
        icon_2_raw = self.ffi.new("char[]", normalized_icon_keys[2].encode("utf-8"))
        icon_3_raw = self.ffi.new("char[]", normalized_icon_keys[3].encode("utf-8"))
        empty_title_raw = self.ffi.new("char[]", empty_title.encode("utf-8"))
        empty_subtitle_raw = self.ffi.new("char[]", empty_subtitle.encode("utf-8"))

        self._raise_if_error(
            self.lib.yoyopod_lvgl_listen_sync(
                page_text_raw,
                footer_raw,
                item_0_raw,
                item_1_raw,
                item_2_raw,
                item_3_raw,
                subtitle_0_raw,
                subtitle_1_raw,
                subtitle_2_raw,
                subtitle_3_raw,
                icon_0_raw,
                icon_1_raw,
                icon_2_raw,
                icon_3_raw,
                len(items),
                selected_index,
                voip_state,
                battery_percent,
                1 if charging else 0,
                1 if power_available else 0,
                self._pack_rgb(accent),
                empty_title_raw,
                empty_subtitle_raw,
            )
        )

    def listen_destroy(self: _LvglBindingHost) -> None:
        self.lib.yoyopod_lvgl_listen_destroy()
