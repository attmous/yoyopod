"""LVGL status-bar scene bindings."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import _LvglBindingHost


class StatusBarSceneMixin:
    """Bindings for status-bar state updates."""

    def set_status_bar_state(
        self: _LvglBindingHost,
        *,
        network_enabled: int,
        network_connected: int,
        wifi_connected: int,
        signal_strength: int,
        gps_has_fix: int,
    ) -> None:
        self._raise_if_error(
            self.lib.yoyopod_lvgl_set_status_bar_state(
                int(network_enabled),
                int(network_connected),
                int(wifi_connected),
                max(0, min(4, int(signal_strength))),
                int(gps_has_fix),
            )
        )
