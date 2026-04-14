"""Shared LVGL status-bar helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


def network_status_kwargs(context: "AppContext | None") -> dict[str, int]:
    """Return normalized network status-bar values for the native LVGL scenes."""

    if context is None:
        return {
            "network_enabled": 0,
            "network_connected": 0,
            "wifi_connected": 0,
            "signal_strength": 0,
            "gps_has_fix": 0,
        }

    signal_strength = max(0, min(4, int(context.network.signal_strength)))
    connection_type = str(context.network.connection_type).lower()
    is_connected = context.network.connected
    return {
        "network_enabled": 1 if context.network.enabled else 0,
        "network_connected": 1 if is_connected and connection_type == "4g" else 0,
        "wifi_connected": 1 if is_connected and connection_type == "wifi" else 0,
        "signal_strength": signal_strength,
        "gps_has_fix": 1 if context.network.gps_has_fix else 0,
    }


def sync_network_status(binding: object, context: "AppContext | None") -> None:
    """Push the shared network/GPS status-bar state into the native LVGL shim."""

    if not hasattr(binding, "set_status_bar_state"):
        return
    binding.set_status_bar_state(**network_status_kwargs(context))
