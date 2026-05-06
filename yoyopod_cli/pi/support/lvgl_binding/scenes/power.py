"""LVGL power scene bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import _LvglBindingHost


class PowerSceneMixin:
    """Bindings for the power/settings scene."""

    def power_build(self: _LvglBindingHost) -> None:
        self._raise_if_error(self.lib.yoyopod_lvgl_power_build())

    def power_sync(
        self: _LvglBindingHost,
        *,
        title_text: str,
        page_text: str | None,
        icon_key: str,
        footer: str,
        items: list[str],
        current_page_index: int,
        total_pages: int,
        voip_state: int,
        battery_percent: int,
        charging: bool,
        power_available: bool,
        accent: tuple[int, int, int],
    ) -> None:
        normalized_items = list(items[:5])
        while len(normalized_items) < 5:
            normalized_items.append("")

        title_raw = self.ffi.new("char[]", title_text.encode("utf-8"))
        page_text_raw = (
            self.ffi.new("char[]", page_text.encode("utf-8")) if page_text else self.ffi.NULL
        )
        icon_raw = self.ffi.new("char[]", icon_key.encode("utf-8"))
        footer_raw = self.ffi.new("char[]", footer.encode("utf-8"))
        item_0_raw = self.ffi.new("char[]", normalized_items[0].encode("utf-8"))
        item_1_raw = self.ffi.new("char[]", normalized_items[1].encode("utf-8"))
        item_2_raw = self.ffi.new("char[]", normalized_items[2].encode("utf-8"))
        item_3_raw = self.ffi.new("char[]", normalized_items[3].encode("utf-8"))
        item_4_raw = self.ffi.new("char[]", normalized_items[4].encode("utf-8"))
        self._raise_if_error(
            self.lib.yoyopod_lvgl_power_sync(
                title_raw,
                page_text_raw,
                icon_raw,
                footer_raw,
                item_0_raw,
                item_1_raw,
                item_2_raw,
                item_3_raw,
                item_4_raw,
                len(items),
                current_page_index,
                total_pages,
                voip_state,
                battery_percent,
                1 if charging else 0,
                1 if power_available else 0,
                self._pack_rgb(accent),
            )
        )

    def power_destroy(self: _LvglBindingHost) -> None:
        self.lib.yoyopod_lvgl_power_destroy()
