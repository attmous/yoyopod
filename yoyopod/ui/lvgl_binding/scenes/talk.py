"""LVGL talk scene bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import _LvglBindingHost


class TalkSceneMixin:
    """Bindings for Talk scene and actions."""

    def talk_build(self: _LvglBindingHost) -> None:
        self._raise_if_error(self.lib.yoyopod_lvgl_talk_build())

    def talk_sync(
        self: _LvglBindingHost,
        *,
        title_text: str,
        icon_key: str | None,
        outlined: bool,
        footer: str,
        selected_index: int,
        total_cards: int,
        voip_state: int,
        battery_percent: int,
        charging: bool,
        power_available: bool,
        accent: tuple[int, int, int],
    ) -> None:
        title_raw = self.ffi.new("char[]", title_text.encode("utf-8"))
        icon_raw = self.ffi.new("char[]", icon_key.encode("utf-8")) if icon_key else self.ffi.NULL
        footer_raw = self.ffi.new("char[]", footer.encode("utf-8"))
        self._raise_if_error(
            self.lib.yoyopod_lvgl_talk_sync(
                title_raw,
                icon_raw,
                1 if outlined else 0,
                footer_raw,
                selected_index,
                total_cards,
                voip_state,
                battery_percent,
                1 if charging else 0,
                1 if power_available else 0,
                self._pack_rgb(accent),
            )
        )

    def talk_destroy(self: _LvglBindingHost) -> None:
        self.lib.yoyopod_lvgl_talk_destroy()

    def talk_actions_build(self: _LvglBindingHost) -> None:
        self._raise_if_error(self.lib.yoyopod_lvgl_talk_actions_build())

    def talk_actions_sync(
        self: _LvglBindingHost,
        *,
        contact_name: str,
        title_text: str | None,
        status_text: str | None,
        status_kind: int,
        footer: str,
        icon_keys: list[str],
        color_kinds: list[int],
        action_count: int,
        selected_index: int,
        layout_kind: int,
        button_size_kind: int,
        voip_state: int,
        battery_percent: int,
        charging: bool,
        power_available: bool,
        accent: tuple[int, int, int],
    ) -> None:
        normalized_icons = list(icon_keys[:3])
        while len(normalized_icons) < 3:
            normalized_icons.append("")
        normalized_colors = list(color_kinds[:3])
        while len(normalized_colors) < 3:
            normalized_colors.append(0)

        contact_raw = self.ffi.new("char[]", contact_name.encode("utf-8"))
        title_raw = (
            self.ffi.new("char[]", title_text.encode("utf-8")) if title_text else self.ffi.NULL
        )
        status_raw = (
            self.ffi.new("char[]", status_text.encode("utf-8")) if status_text else self.ffi.NULL
        )
        footer_raw = self.ffi.new("char[]", footer.encode("utf-8"))
        icon_0_raw = self.ffi.new("char[]", normalized_icons[0].encode("utf-8"))
        icon_1_raw = self.ffi.new("char[]", normalized_icons[1].encode("utf-8"))
        icon_2_raw = self.ffi.new("char[]", normalized_icons[2].encode("utf-8"))

        self._raise_if_error(
            self.lib.yoyopod_lvgl_talk_actions_sync(
                contact_raw,
                title_raw,
                status_raw,
                int(status_kind),
                footer_raw,
                icon_0_raw,
                int(normalized_colors[0]),
                icon_1_raw,
                int(normalized_colors[1]),
                icon_2_raw,
                int(normalized_colors[2]),
                int(action_count),
                int(selected_index),
                int(layout_kind),
                int(button_size_kind),
                voip_state,
                battery_percent,
                1 if charging else 0,
                1 if power_available else 0,
                self._pack_rgb(accent),
            )
        )

    def talk_actions_destroy(self: _LvglBindingHost) -> None:
        self.lib.yoyopod_lvgl_talk_actions_destroy()
