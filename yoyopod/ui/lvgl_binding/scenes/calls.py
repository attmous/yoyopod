"""LVGL call scene bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import _LvglBindingHost


class CallsSceneMixin:
    """Bindings for incoming/outgoing/in-call scenes."""

    def incoming_call_build(self: _LvglBindingHost) -> None:
        self._raise_if_error(self.lib.yoyopod_lvgl_incoming_call_build())

    def incoming_call_sync(
        self: _LvglBindingHost,
        *,
        caller_name: str,
        caller_address: str,
        footer: str,
        voip_state: int,
        battery_percent: int,
        charging: bool,
        power_available: bool,
        accent: tuple[int, int, int],
    ) -> None:
        caller_name_raw = self.ffi.new("char[]", caller_name.encode("utf-8"))
        caller_address_raw = self.ffi.new("char[]", caller_address.encode("utf-8"))
        footer_raw = self.ffi.new("char[]", footer.encode("utf-8"))

        self._raise_if_error(
            self.lib.yoyopod_lvgl_incoming_call_sync(
                caller_name_raw,
                caller_address_raw,
                footer_raw,
                voip_state,
                battery_percent,
                1 if charging else 0,
                1 if power_available else 0,
                self._pack_rgb(accent),
            )
        )

    def incoming_call_destroy(self: _LvglBindingHost) -> None:
        self.lib.yoyopod_lvgl_incoming_call_destroy()

    def outgoing_call_build(self: _LvglBindingHost) -> None:
        self._raise_if_error(self.lib.yoyopod_lvgl_outgoing_call_build())

    def outgoing_call_sync(
        self: _LvglBindingHost,
        *,
        callee_name: str,
        callee_address: str,
        footer: str,
        voip_state: int,
        battery_percent: int,
        charging: bool,
        power_available: bool,
        accent: tuple[int, int, int],
    ) -> None:
        callee_name_raw = self.ffi.new("char[]", callee_name.encode("utf-8"))
        callee_address_raw = self.ffi.new("char[]", callee_address.encode("utf-8"))
        footer_raw = self.ffi.new("char[]", footer.encode("utf-8"))
        self._raise_if_error(
            self.lib.yoyopod_lvgl_outgoing_call_sync(
                callee_name_raw,
                callee_address_raw,
                footer_raw,
                voip_state,
                battery_percent,
                1 if charging else 0,
                1 if power_available else 0,
                self._pack_rgb(accent),
            )
        )

    def outgoing_call_destroy(self: _LvglBindingHost) -> None:
        self.lib.yoyopod_lvgl_outgoing_call_destroy()

    def in_call_build(self: _LvglBindingHost) -> None:
        self._raise_if_error(self.lib.yoyopod_lvgl_in_call_build())

    def in_call_sync(
        self: _LvglBindingHost,
        *,
        caller_name: str,
        duration_text: str,
        mute_text: str,
        footer: str,
        muted: bool,
        voip_state: int,
        battery_percent: int,
        charging: bool,
        power_available: bool,
        accent: tuple[int, int, int],
    ) -> None:
        caller_name_raw = self.ffi.new("char[]", caller_name.encode("utf-8"))
        duration_raw = self.ffi.new("char[]", duration_text.encode("utf-8"))
        mute_raw = self.ffi.new("char[]", mute_text.encode("utf-8"))
        footer_raw = self.ffi.new("char[]", footer.encode("utf-8"))
        self._raise_if_error(
            self.lib.yoyopod_lvgl_in_call_sync(
                caller_name_raw,
                duration_raw,
                mute_raw,
                footer_raw,
                1 if muted else 0,
                voip_state,
                battery_percent,
                1 if charging else 0,
                1 if power_available else 0,
                self._pack_rgb(accent),
            )
        )

    def in_call_destroy(self: _LvglBindingHost) -> None:
        self.lib.yoyopod_lvgl_in_call_destroy()
