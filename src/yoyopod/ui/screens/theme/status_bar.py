"""Status-bar themed rendering helpers."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from yoyopod.ui.display import Display
from yoyopod.ui.screens.theme_tokens import (
    BACKGROUND,
    ERROR,
    INK,
    MUTED,
    SUCCESS,
    STATUS_BATTERY_GAP_LANDSCAPE,
    STATUS_BATTERY_GAP_PORTRAIT,
    STATUS_BATTERY_SIDE_INSET_LANDSCAPE,
    STATUS_BATTERY_SIDE_INSET_PORTRAIT,
    STATUS_BATTERY_TOP_LANDSCAPE,
    STATUS_BATTERY_TOP_PORTRAIT,
    STATUS_CLUSTER_GAP_LANDSCAPE,
    STATUS_CLUSTER_GAP_PORTRAIT,
    STATUS_CLOCK_TOP_LANDSCAPE,
    STATUS_CLOCK_TOP_PORTRAIT,
    STATUS_GPS_CENTER_RADIUS,
    STATUS_GPS_ICON_HEIGHT,
    STATUS_GPS_ICON_WIDTH,
    STATUS_GPS_RING_RADIUS,
    STATUS_ICON_BOTTOM_LANDSCAPE,
    STATUS_ICON_BOTTOM_PORTRAIT,
    STATUS_SIGNAL_BAR_GAP,
    STATUS_SIGNAL_BAR_HEIGHTS,
    STATUS_SIGNAL_BAR_WIDTH,
    STATUS_SIDE_INSET_LANDSCAPE,
    STATUS_SIDE_INSET_PORTRAIT,
    STATUS_TIME_FONT_SIZE,
    STATUS_VOIP_ICON_RADIUS,
    STATUS_WIFI_DOT_RADIUS,
    STATUS_WIFI_ICON_HEIGHT,
    STATUS_WIFI_ICON_WIDTH,
    Color,
    ModeTheme,
    theme_for,
)

if TYPE_CHECKING:
    from yoyopod.core import AppContext


def render_backdrop(display: Display, mode: str) -> ModeTheme:
    """Paint the shared Graffiti Buddy backdrop."""

    theme = theme_for(mode)
    display.clear(BACKGROUND)
    return theme


def render_status_bar(
    display: Display,
    context: "AppContext | None",
    *,
    show_time: bool,
) -> None:
    """Draw the simplified product status bar."""

    bar_height = display.STATUS_BAR_HEIGHT
    display.rectangle(0, 0, display.WIDTH, bar_height, fill=BACKGROUND)
    is_portrait = display.is_portrait()
    side_inset = STATUS_SIDE_INSET_PORTRAIT if is_portrait else STATUS_SIDE_INSET_LANDSCAPE
    clock_top = STATUS_CLOCK_TOP_PORTRAIT if is_portrait else STATUS_CLOCK_TOP_LANDSCAPE
    battery_top = STATUS_BATTERY_TOP_PORTRAIT if is_portrait else STATUS_BATTERY_TOP_LANDSCAPE
    icon_bottom = STATUS_ICON_BOTTOM_PORTRAIT if is_portrait else STATUS_ICON_BOTTOM_LANDSCAPE
    cluster_gap = STATUS_CLUSTER_GAP_PORTRAIT if is_portrait else STATUS_CLUSTER_GAP_LANDSCAPE
    battery_side_inset = (
        STATUS_BATTERY_SIDE_INSET_PORTRAIT if is_portrait else STATUS_BATTERY_SIDE_INSET_LANDSCAPE
    )
    battery_gap = STATUS_BATTERY_GAP_PORTRAIT if is_portrait else STATUS_BATTERY_GAP_LANDSCAPE

    cursor_x = side_inset
    connection_type = "none" if context is None else str(context.network.connection_type).lower()
    is_connected = False if context is None else context.network.connected

    # -- Signal bars (visible when network module is enabled) --
    if context is not None and context.network.enabled:
        signal = context.network.signal_strength
        connected = is_connected and connection_type == "4g"
        for i, h in enumerate(STATUS_SIGNAL_BAR_HEIGHTS):
            bx = cursor_x + i * (STATUS_SIGNAL_BAR_WIDTH + STATUS_SIGNAL_BAR_GAP)
            by = icon_bottom - h + 1
            if i < signal:
                bar_color = SUCCESS if connected else MUTED
            else:
                bar_color = (60, 63, 70)
            display.rectangle(
                bx,
                by,
                bx + STATUS_SIGNAL_BAR_WIDTH - 1,
                icon_bottom,
                fill=bar_color,
            )
        cursor_x += (4 * STATUS_SIGNAL_BAR_WIDTH) + (3 * STATUS_SIGNAL_BAR_GAP) + cluster_gap

    if is_connected and connection_type == "wifi":
        _draw_status_wifi_icon(display, cursor_x, icon_bottom, SUCCESS)
        cursor_x += STATUS_WIFI_ICON_WIDTH + cluster_gap

    # -- GPS indicator (visible when network module is enabled) --
    if context is not None and context.network.enabled:
        gps_fix = context.network.gps_has_fix
        gps_color = SUCCESS if gps_fix else MUTED
        _draw_status_gps_icon(display, cursor_x, icon_bottom, gps_color)
        cursor_x += STATUS_GPS_ICON_WIDTH + cluster_gap

    # -- VoIP indicator --
    voip_state = _voip_state(context)
    if voip_state != "none":
        voip_center_x = cursor_x + STATUS_VOIP_ICON_RADIUS
        voip_center_y = icon_bottom - STATUS_VOIP_ICON_RADIUS + 1
        display.circle(
            voip_center_x,
            voip_center_y,
            STATUS_VOIP_ICON_RADIUS,
            fill=SUCCESS if voip_state == "ready" else ERROR,
        )

    if show_time:
        time_text = datetime.now().strftime("%H:%M")
        time_width, _ = display.get_text_size(time_text, STATUS_TIME_FONT_SIZE)
        time_x = max(0, (display.WIDTH - time_width) // 2)
        display.text(time_text, time_x, clock_top, color=MUTED, font_size=STATUS_TIME_FONT_SIZE)

    battery_level = 100 if context is None else int(round(context.power.battery_percent))
    charging = False if context is None else context.power.battery_charging
    power_available = True if context is None else context.power.available

    battery_text = f"{max(0, min(100, battery_level))}%"
    battery_text_width, _ = display.get_text_size(battery_text, STATUS_TIME_FONT_SIZE)
    battery_text_x = display.WIDTH - battery_side_inset - battery_text_width
    battery_x = battery_text_x - battery_gap
    battery_y = battery_top
    display.rectangle(
        battery_x,
        battery_y,
        battery_x + 14,
        battery_y + 8,
        outline=MUTED,
        width=1,
    )
    display.rectangle(
        battery_x + 14,
        battery_y + 2,
        battery_x + 16,
        battery_y + 6,
        fill=MUTED,
    )

    fill_color = MUTED
    if power_available:
        if battery_level <= 20:
            fill_color = ERROR
        elif charging:
            fill_color = SUCCESS
        else:
            fill_color = INK

    fill_width = max(0, min(12, int((max(0, min(100, battery_level)) / 100.0) * 12)))
    if fill_width > 0:
        display.rectangle(
            battery_x + 1,
            battery_y + 1,
            battery_x + 1 + fill_width,
            battery_y + 7,
            fill=fill_color,
        )
    display.text(
        battery_text,
        battery_text_x,
        clock_top,
        color=MUTED,
        font_size=STATUS_TIME_FONT_SIZE,
    )


def _status_icon_top(bottom: int, height: int) -> int:
    """Return the top Y for an icon whose bounding box should share a bottom edge."""

    return bottom - height + 1


def _draw_status_wifi_icon(
    display: Display, left: int, bottom: int, color: Color
) -> None:
    """Draw a compact Wi-Fi icon with the same visual baseline as other status glyphs."""

    icon_top = _status_icon_top(bottom, STATUS_WIFI_ICON_HEIGHT)
    center_x = left + (STATUS_WIFI_ICON_WIDTH // 2)
    for width, top_offset in ((3, 0), (7, 3), (11, 6)):
        bar_left = center_x - (width // 2)
        bar_top = icon_top + top_offset
        display.rectangle(bar_left, bar_top, bar_left + width - 1, bar_top + 1, fill=color)
    display.circle(
        center_x,
        icon_top + STATUS_WIFI_ICON_HEIGHT - 2,
        STATUS_WIFI_DOT_RADIUS,
        fill=color,
    )


def _draw_status_gps_icon(display: Display, left: int, bottom: int, color: Color) -> None:
    """Draw a clearer pin-style GPS icon for the compact status bar."""

    icon_top = _status_icon_top(bottom, STATUS_GPS_ICON_HEIGHT)
    center_x = left + (STATUS_GPS_ICON_WIDTH // 2)
    ring_center_y = icon_top + STATUS_GPS_RING_RADIUS
    display.circle(center_x, ring_center_y, STATUS_GPS_RING_RADIUS, outline=color, width=1)
    display.circle(center_x, ring_center_y, STATUS_GPS_CENTER_RADIUS, fill=color)
    display.line(
        center_x,
        ring_center_y + STATUS_GPS_RING_RADIUS,
        center_x,
        bottom,
        color=color,
        width=1,
    )


def _voip_state(context: "AppContext | None") -> str:
    """Return ready/offline/none for the simplified status bar."""

    if context is None or not context.voip.configured:
        return "none"
    return "ready" if context.voip.ready else "offline"


def format_battery_compact(context: "AppContext | None") -> str:
    """Return a tiny battery summary for cards."""

    if context is None or not context.power.available:
        return "Power offline"
    level = context.power.battery_percent
    if context.power.battery_charging:
        return f"{level}% charging"
    return f"{level}% battery"
