"""LVGL playlist scene bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import _LvglBindingHost


class PlaylistSceneMixin:
    """Bindings for playlist browsing scenes."""

    def playlist_build(self: _LvglBindingHost) -> None:
        self._raise_if_error(self.lib.yoyopod_lvgl_playlist_build())

    def playlist_sync(
        self: _LvglBindingHost,
        *,
        title_text: str,
        page_text: str | None,
        status_chip_text: str | None = None,
        status_chip_kind: int = 0,
        footer: str,
        items: list[str],
        subtitles: list[str],
        badges: list[str],
        icon_keys: list[str],
        selected_visible_index: int,
        voip_state: int,
        battery_percent: int,
        charging: bool,
        power_available: bool,
        accent: tuple[int, int, int],
        empty_title: str,
        empty_subtitle: str,
        empty_icon_key: str,
    ) -> None:
        normalized_items = list(items[:4])
        while len(normalized_items) < 4:
            normalized_items.append("")
        normalized_subtitles = list(subtitles[:4])
        while len(normalized_subtitles) < 4:
            normalized_subtitles.append("")

        normalized_badges = list(badges[:4])
        while len(normalized_badges) < 4:
            normalized_badges.append("")
        normalized_icon_keys = list(icon_keys[:4])
        while len(normalized_icon_keys) < 4:
            normalized_icon_keys.append("")

        title_raw = self.ffi.new("char[]", title_text.encode("utf-8"))
        page_text_raw = (
            self.ffi.new("char[]", page_text.encode("utf-8")) if page_text else self.ffi.NULL
        )
        status_chip_text_raw = (
            self.ffi.new("char[]", status_chip_text.encode("utf-8"))
            if status_chip_text
            else self.ffi.NULL
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
        badge_0_raw = self.ffi.new("char[]", normalized_badges[0].encode("utf-8"))
        badge_1_raw = self.ffi.new("char[]", normalized_badges[1].encode("utf-8"))
        badge_2_raw = self.ffi.new("char[]", normalized_badges[2].encode("utf-8"))
        badge_3_raw = self.ffi.new("char[]", normalized_badges[3].encode("utf-8"))
        icon_0_raw = self.ffi.new("char[]", normalized_icon_keys[0].encode("utf-8"))
        icon_1_raw = self.ffi.new("char[]", normalized_icon_keys[1].encode("utf-8"))
        icon_2_raw = self.ffi.new("char[]", normalized_icon_keys[2].encode("utf-8"))
        icon_3_raw = self.ffi.new("char[]", normalized_icon_keys[3].encode("utf-8"))
        empty_title_raw = self.ffi.new("char[]", empty_title.encode("utf-8"))
        empty_subtitle_raw = self.ffi.new("char[]", empty_subtitle.encode("utf-8"))
        empty_icon_raw = self.ffi.new("char[]", empty_icon_key.encode("utf-8"))

        self._raise_if_error(
            self.lib.yoyopod_lvgl_playlist_sync(
                title_raw,
                page_text_raw,
                status_chip_text_raw,
                int(status_chip_kind),
                footer_raw,
                item_0_raw,
                item_1_raw,
                item_2_raw,
                item_3_raw,
                subtitle_0_raw,
                subtitle_1_raw,
                subtitle_2_raw,
                subtitle_3_raw,
                badge_0_raw,
                badge_1_raw,
                badge_2_raw,
                badge_3_raw,
                icon_0_raw,
                icon_1_raw,
                icon_2_raw,
                icon_3_raw,
                len(items),
                selected_visible_index,
                voip_state,
                battery_percent,
                1 if charging else 0,
                1 if power_available else 0,
                self._pack_rgb(accent),
                empty_title_raw,
                empty_subtitle_raw,
                empty_icon_raw,
            )
        )

    def playlist_destroy(self: _LvglBindingHost) -> None:
        self.lib.yoyopod_lvgl_playlist_destroy()
