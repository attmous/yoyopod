"""Graffiti Buddy theme primitives for YoyoPod screens."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from PIL import Image

from yoyopy.ui.display import Display
from yoyopy.ui.screens.theme_assets import ICON_ASSET_DIR, PHOSPHOR_ICON_FILES, load_icon_asset
from yoyopy.ui.screens.theme_text import mix, text_fit, wrap_text
from yoyopy.ui.screens.theme_tokens import (
    ASK,
    BACKGROUND,
    ERROR,
    FOOTER_BAR,
    FOOTER_SAFE_HEIGHT_LANDSCAPE,
    FOOTER_SAFE_HEIGHT_PORTRAIT,
    HEADER_SIDE_INSET_LANDSCAPE,
    HEADER_SIDE_INSET_PORTRAIT,
    INK,
    LISTEN,
    MUTED,
    MUTED_DIM,
    ModeTheme,
    NEUTRAL,
    SETUP,
    STATUS_BATTERY_GAP_LANDSCAPE,
    STATUS_BATTERY_GAP_PORTRAIT,
    STATUS_BATTERY_SIDE_INSET_LANDSCAPE,
    STATUS_BATTERY_SIDE_INSET_PORTRAIT,
    STATUS_BATTERY_TOP_LANDSCAPE,
    STATUS_BATTERY_TOP_PORTRAIT,
    STATUS_CLOCK_TOP_LANDSCAPE,
    STATUS_CLOCK_TOP_PORTRAIT,
    STATUS_CLUSTER_GAP_LANDSCAPE,
    STATUS_CLUSTER_GAP_PORTRAIT,
    STATUS_GPS_CENTER_RADIUS,
    STATUS_GPS_ICON_HEIGHT,
    STATUS_GPS_ICON_WIDTH,
    STATUS_GPS_RING_RADIUS,
    STATUS_ICON_BOTTOM_LANDSCAPE,
    STATUS_ICON_BOTTOM_PORTRAIT,
    STATUS_SIDE_INSET_LANDSCAPE,
    STATUS_SIDE_INSET_PORTRAIT,
    STATUS_SIGNAL_BAR_GAP,
    STATUS_SIGNAL_BAR_HEIGHTS,
    STATUS_SIGNAL_BAR_WIDTH,
    STATUS_TIME_FONT_SIZE,
    STATUS_VOIP_ICON_RADIUS,
    STATUS_WIFI_DOT_RADIUS,
    STATUS_WIFI_ICON_HEIGHT,
    STATUS_WIFI_ICON_WIDTH,
    SUCCESS,
    SURFACE,
    SURFACE_BORDER,
    SURFACE_RAISED,
    TALK,
    WARNING,
    Color,
    theme_for,
)

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


def _get_draw(display: Display):
    """Return the underlying PIL draw surface when available."""

    adapter = display.get_adapter() if hasattr(display, "get_adapter") else None
    return getattr(adapter, "draw", None)


def _get_buffer(display: Display):
    """Return the underlying PIL image buffer when available."""

    adapter = display.get_adapter() if hasattr(display, "get_adapter") else None
    return getattr(adapter, "buffer", None)


def rounded_panel(
    display: Display,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    fill: Color,
    outline: Color | None = None,
    radius: int = 18,
    width: int = 2,
    shadow: bool = False,
) -> None:
    """Draw a rounded graffiti-style panel."""

    draw = _get_draw(display)
    if shadow:
        _rounded_shape(
            display,
            x1 + 3,
            y1 + 4,
            x2 + 3,
            y2 + 4,
            fill=(10, 12, 17),
            outline=None,
            radius=radius,
            width=1,
            draw=draw,
        )

    _rounded_shape(
        display,
        x1,
        y1,
        x2,
        y2,
        fill=fill,
        outline=outline,
        radius=radius,
        width=width,
        draw=draw,
    )


def _rounded_shape(
    display: Display,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    *,
    fill: Color | None,
    outline: Color | None,
    radius: int,
    width: int,
    draw,
) -> None:
    """Draw a rounded rectangle with a PIL fallback."""

    if draw is not None and hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(
            [(x1, y1), (x2, y2)],
            radius=radius,
            fill=fill,
            outline=outline,
            width=width,
        )
        return

    display.rectangle(x1 + radius, y1, x2 - radius, y2, fill=fill, outline=outline, width=width)
    display.rectangle(x1, y1 + radius, x2, y2 - radius, fill=fill, outline=outline, width=width)
    for corner_x, corner_y in (
        (x1 + radius, y1 + radius),
        (x2 - radius, y1 + radius),
        (x1 + radius, y2 - radius),
        (x2 - radius, y2 - radius),
    ):
        display.circle(corner_x, corner_y, radius, fill=fill, outline=outline, width=width)


def render_backdrop(display: Display, mode: str) -> ModeTheme:
    """Paint the shared Graffiti Buddy backdrop."""

    theme = theme_for(mode)
    display.clear(BACKGROUND)
    return theme


def render_status_bar(
    display: Display,
    context: AppContext | None,
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


def _draw_status_wifi_icon(display: Display, left: int, bottom: int, color: Color) -> None:
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


def render_header(
    display: Display,
    context: AppContext | None,
    *,
    mode: str,
    title: str,
    subtitle: str = "",
    icon: str | None = None,
    page_text: str | None = None,
    show_time: bool = False,
    show_mode_chip: bool = True,
) -> int:
    """Render the shared status bar plus title block and return content start."""

    theme = render_backdrop(display, mode)
    render_status_bar(display, context, show_time=show_time)
    side_inset = (
        HEADER_SIDE_INSET_PORTRAIT if display.is_portrait() else HEADER_SIDE_INSET_LANDSCAPE
    )

    chip_y = display.STATUS_BAR_HEIGHT + 10
    title_font_size = 28 if display.is_portrait() else 24
    title_y = chip_y + 26

    if show_mode_chip:
        _pill(
            display,
            side_inset,
            chip_y,
            theme.label.upper(),
            fill=theme.accent_dim,
            text_color=theme.accent,
        )
        if page_text:
            width, _ = display.get_text_size(page_text, 10)
            display.text(
                page_text, display.WIDTH - width - side_inset, chip_y + 4, color=MUTED, font_size=10
            )
    else:
        title_font_size = 24 if display.is_portrait() else 22
        title_y = chip_y + 6
        if page_text:
            width, _ = display.get_text_size(page_text, 10)
            display.text(
                page_text, display.WIDTH - width - side_inset, chip_y + 2, color=MUTED, font_size=10
            )

    max_title_width = display.WIDTH - (side_inset * 2) - 60
    display_title = text_fit(display, title, max_title_width, title_font_size)
    display.text(display_title, side_inset, title_y, color=INK, font_size=title_font_size)

    title_width, title_height = display.get_text_size(display_title, title_font_size)
    display.line(
        side_inset,
        title_y + title_height + 6,
        side_inset + min(title_width + 10, 126),
        title_y + title_height + 6,
        color=theme.accent,
        width=3,
    )

    if subtitle:
        subtitle_y = title_y + title_height + 14
        subtitle_width = display.WIDTH - (side_inset * 2) - (62 if icon else 0)
        lines = wrap_text(display, subtitle, subtitle_width, 12, max_lines=2)
        for line_index, line in enumerate(lines):
            display.text(
                line, side_inset, subtitle_y + (line_index * 14), color=MUTED, font_size=12
            )
        bottom_y = subtitle_y + (len(lines) * 14)
    else:
        bottom_y = title_y + title_height + 10

    if icon:
        draw_icon(
            display,
            icon,
            display.WIDTH - side_inset - 44,
            display.STATUS_BAR_HEIGHT + 18,
            44,
            theme.accent,
        )

    return bottom_y + 10


def draw_list_item(
    display: Display,
    *,
    x1: int,
    y1: int,
    x2: int,
    y2: int,
    title: str,
    subtitle: str = "",
    mode: str,
    selected: bool,
    badge: str | None = None,
    icon: str | None = None,
) -> None:
    """Render one rounded list card."""

    theme = theme_for(mode)
    fill = (250, 250, 250) if selected else SURFACE_RAISED
    outline = None if selected else SURFACE_BORDER
    rounded_panel(display, x1, y1, x2, y2, fill=fill, outline=outline, radius=14, shadow=False)

    title_color = BACKGROUND if selected else INK
    subtitle_color = mix(BACKGROUND, MUTED, 0.55) if selected else MUTED
    badge_width = 0
    if badge:
        badge_width = display.get_text_size(badge, 10)[0] + 18

    monogram = ""
    if icon and icon.startswith("mono:"):
        monogram = icon.split(":", 1)[1]

    icon_size = 22 if icon else 0
    icon_left = x1 + 18
    text_left = x1 + (54 if icon else 16)
    if icon:
        icon_y = y1 + max(8, ((y2 - y1) - icon_size) // 2)
        if monogram:
            rounded_panel(
                display,
                icon_left - 2,
                icon_y - 2,
                icon_left + 24,
                icon_y + 24,
                fill=mix(theme.accent, BACKGROUND, 0.85),
                outline=None,
                radius=8,
            )
            mono_width, mono_height = display.get_text_size(monogram, 12)
            display.text(
                monogram,
                icon_left + 10 - (mono_width // 2),
                icon_y + 10 - (mono_height // 2),
                color=theme.accent,
                font_size=12,
            )
        else:
            draw_icon(display, icon, icon_left, icon_y, icon_size, theme.accent)

    title_text = text_fit(display, title, x2 - text_left - 14 - badge_width, 16)
    title_height = display.get_text_size(title_text, 16)[1]
    title_y = y1 + 9
    if not subtitle:
        title_y = y1 + max(6, ((y2 - y1) - title_height) // 2)
    display.text(title_text, text_left, title_y, color=title_color, font_size=16)
    if subtitle:
        display.text(
            text_fit(display, subtitle, x2 - text_left - 14, 12),
            text_left,
            y1 + 28,
            color=subtitle_color,
            font_size=12,
        )

    if selected:
        display.circle(x1 + 14, y1 + 14, 3, fill=theme.accent)

    if badge:
        _pill(
            display,
            x2 - badge_width - 10,
            y1 + 8,
            badge,
            fill=theme.accent_dim if not selected else mix(theme.accent, INK, 0.75),
            text_color=theme.accent if not selected else BACKGROUND,
            font_size=10,
            padding=6,
        )


def draw_empty_state(
    display: Display,
    *,
    mode: str,
    title: str,
    subtitle: str,
    icon: str,
    top: int,
) -> None:
    """Render a centered empty-state panel."""

    theme = theme_for(mode)
    panel_left = 18
    panel_top = top + 10
    panel_right = display.WIDTH - 18
    panel_bottom = min(display.HEIGHT - 32, panel_top + 156)
    rounded_panel(
        display,
        panel_left,
        panel_top,
        panel_right,
        panel_bottom,
        fill=SURFACE,
        outline=None,
        radius=22,
    )
    halo_size = 64
    halo_left = (display.WIDTH - halo_size) // 2
    halo_top = panel_top + 18
    rounded_panel(
        display,
        halo_left,
        halo_top,
        halo_left + halo_size,
        halo_top + halo_size,
        fill=mix(theme.accent, BACKGROUND, 0.82),
        outline=None,
        radius=32,
    )
    draw_icon(display, icon, halo_left + 14, halo_top + 14, 36, mix(theme.accent, INK, 0.18))

    title_width, _ = display.get_text_size(title, 18)
    display.text(title, (display.WIDTH - title_width) // 2, panel_top + 96, color=INK, font_size=18)

    lines = wrap_text(display, subtitle, panel_right - panel_left - 28, 12, max_lines=2)
    line_y = panel_top + 126
    for line in lines:
        line_width, _ = display.get_text_size(line, 12)
        display.text(line, (display.WIDTH - line_width) // 2, line_y, color=MUTED, font_size=12)
        line_y += 15


def render_footer(display: Display, text: str, *, mode: str) -> None:
    """Draw the bottom helper hint."""

    if not text:
        return

    font_size = 11 if display.is_portrait() else 10
    footer_safe_height = (
        FOOTER_SAFE_HEIGHT_PORTRAIT if display.is_portrait() else FOOTER_SAFE_HEIGHT_LANDSCAPE
    )
    footer_top = display.HEIGHT - footer_safe_height

    # Reserve a clean bottom strip so helper text never collides with panels or list rows.
    display.rectangle(0, footer_top, display.WIDTH, display.HEIGHT, fill=FOOTER_BAR)
    lines = wrap_text(display, text, display.WIDTH - 24, font_size, max_lines=2) or [text]
    line_height = display.get_text_size("Ag", font_size)[1]
    total_height = len(lines) * line_height
    footer_y = footer_top + max(0, (footer_safe_height - total_height) // 2) - 1
    for line in lines:
        footer_width, _ = display.get_text_size(line, font_size)
        footer_x = (display.WIDTH - footer_width) // 2
        display.text(line, footer_x, footer_y, color=MUTED_DIM, font_size=font_size)
        footer_y += line_height


def _pill(
    display: Display,
    x: int,
    y: int,
    text: str,
    *,
    fill: Color,
    text_color: Color,
    font_size: int = 10,
    padding: int = 8,
) -> None:
    """Draw a small rounded label pill."""

    text_width, text_height = display.get_text_size(text, font_size)
    rounded_panel(
        display,
        x,
        y,
        x + text_width + (padding * 2),
        y + text_height + 8,
        fill=fill,
        outline=None,
        radius=12,
    )
    display.text(text, x + padding, y + 4, color=text_color, font_size=font_size)


def talk_monogram(name: str, fallback: str = "?") -> str:
    """Return a compact 1-2 character monogram for a contact label."""

    parts = [part for part in name.replace("-", " ").split() if part]
    if not parts:
        return fallback
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[1][0]}".upper()


def draw_talk_large_card(
    display: Display,
    *,
    left: int,
    top: int,
    size: int,
    color: Color,
    label: str | None = None,
    icon: str | None = None,
    outlined: bool = False,
) -> tuple[int, int]:
    """Draw the large Talk card used by the person carousel and call states."""

    fill = mix(color, BACKGROUND, 0.78) if outlined else color
    outline = color if outlined else None
    shadow = not outlined
    rounded_panel(
        display,
        left,
        top,
        left + size,
        top + size,
        fill=fill,
        outline=outline,
        radius=16,
        width=2 if outlined else 0,
        shadow=shadow,
    )

    if icon:
        icon_size = 64 if size >= 96 else max(28, size // 2)
        draw_icon(
            display,
            icon,
            left + (size - icon_size) // 2,
            top + (size - icon_size) // 2,
            icon_size,
            color if outlined else INK,
        )
        return left + size, top + size

    if label:
        font_size = 42 if size >= 96 else 22
        label_width, label_height = display.get_text_size(label, font_size)
        display.text(
            label,
            left + (size - label_width) // 2,
            top + (size - label_height) // 2 - 2,
            color=color if outlined else INK,
            font_size=font_size,
        )

    return left + size, top + size


def draw_talk_person_header(
    display: Display,
    *,
    center_x: int,
    top: int,
    name: str,
    label: str | None = None,
    size: str = "small",
    color: Color = TALK.accent,
) -> int:
    """Draw the small Talk person header with monogram/label and name."""

    box_size = 56 if size == "medium" else 48
    left = center_x - (box_size // 2)
    rounded_panel(
        display,
        left,
        top,
        left + box_size,
        top + box_size,
        fill=mix(color, BACKGROUND, 0.85),
        outline=None,
        radius=12,
    )
    avatar = label or talk_monogram(name)
    font_size = 22 if size == "medium" else 18
    avatar_width, avatar_height = display.get_text_size(avatar, font_size)
    display.text(
        avatar,
        center_x - (avatar_width // 2),
        top + ((box_size - avatar_height) // 2) - 1,
        color=color,
        font_size=font_size,
    )
    display_name = text_fit(display, name, 112, 12 if size == "small" else 14)
    name_width, name_height = display.get_text_size(display_name, 12 if size == "small" else 14)
    display.text(
        display_name,
        center_x - (name_width // 2),
        top + box_size + 6,
        color=MUTED,
        font_size=12 if size == "small" else 14,
    )
    return top + box_size + name_height + 6


def draw_talk_action_button(
    display: Display,
    *,
    center_x: int,
    center_y: int,
    button_size: str,
    color: Color,
    icon: str,
    filled: bool = False,
    active: bool = True,
) -> tuple[int, int, int, int]:
    """Draw a circular Talk action button."""

    diameter = {
        "large": 88,
        "medium": 64,
        "small": 56,
    }.get(button_size, 64)
    left = center_x - (diameter // 2)
    top = center_y - (diameter // 2)

    base_color = color if active else mix(color, BACKGROUND, 0.45)
    fill = color if filled else SURFACE_RAISED
    if filled and not active:
        fill = mix(color, BACKGROUND, 0.45)
    outline = None if filled else base_color
    rounded_panel(
        display,
        left,
        top,
        left + diameter,
        top + diameter,
        fill=fill,
        outline=outline,
        radius=diameter // 2,
        width=2 if not filled else 0,
        shadow=filled and active,
    )

    icon_size = {
        "large": 48,
        "medium": 40,
        "small": 28,
    }.get(button_size, 40)
    icon_color = INK if filled else base_color
    if filled and not active:
        icon_color = mix(INK, BACKGROUND, 0.45)
    draw_icon(
        display,
        icon,
        center_x - (icon_size // 2),
        center_y - (icon_size // 2),
        icon_size,
        icon_color,
    )
    return left, top, left + diameter, top + diameter


def draw_talk_page_dots(
    display: Display,
    *,
    center_x: int,
    top: int,
    total: int,
    current: int,
    color: Color = TALK.accent,
) -> None:
    """Draw centered Talk pagination dots."""

    if total <= 0:
        return
    gap = 14
    total_width = ((total - 1) * gap) + 8
    start_x = center_x - (total_width // 2)
    for index in range(total):
        radius = 4 if index == current else 3
        fill = color if index == current else mix(color, BACKGROUND, 0.72)
        display.circle(start_x + (index * gap), top, radius, fill=fill)


def draw_talk_status_chip(
    display: Display,
    *,
    center_x: int,
    top: int,
    text: str,
    color: Color,
    icon: str | None = None,
) -> int:
    """Draw a centered pill chip used across Talk call and voice-note states."""

    font_size = 12
    text_width, text_height = display.get_text_size(text, font_size)
    icon_width = 0
    if icon:
        icon_width = 16
    chip_width = text_width + icon_width + 24
    left = center_x - (chip_width // 2)
    rounded_panel(
        display,
        left,
        top,
        left + chip_width,
        top + text_height + 10,
        fill=mix(color, BACKGROUND, 0.85),
        outline=None,
        radius=14,
    )
    text_x = left + 12
    if icon:
        draw_icon(display, icon, left + 9, top + 5, 12, color)
        text_x += 14
    display.text(text, text_x, top + 4, color=color, font_size=font_size)
    return top + text_height + 10


def draw_icon(display: Display, icon: str, x: int, y: int, size: int, color: Color) -> None:
    """Draw a lightweight doodle icon."""

    if _paste_phosphor_icon(display, icon, x, y, size, color):
        return

    draw = _get_draw(display)
    if icon == "listen":
        _draw_listen_icon(display, draw, x, y, size, color)
    elif icon == "music_note":
        _draw_music_note_icon(display, draw, x, y, size, color)
    elif icon == "talk":
        _draw_talk_icon(display, draw, x, y, size, color)
    elif icon == "ask":
        _draw_ask_icon(display, draw, x, y, size, color)
    elif icon == "care":
        _draw_care_icon(display, draw, x, y, size, color)
    elif icon == "clock":
        _draw_clock_icon(display, draw, x, y, size, color)
    elif icon == "battery":
        _draw_battery_icon(display, draw, x, y, size, color)
    elif icon == "signal":
        _draw_signal_icon(display, draw, x, y, size, color)
    elif icon in {"setup", "power"}:
        _draw_setup_icon(display, draw, x, y, size, color)
    elif icon == "playlist":
        _draw_playlist_icon(display, draw, x, y, size, color)
    elif icon == "call":
        _draw_call_icon(display, draw, x, y, size, color)
    elif icon == "people":
        _draw_people_icon(display, draw, x, y, size, color)
    elif icon == "incoming":
        _draw_talk_icon(display, draw, x, y, size, color)
        display.line(x + size - 10, y + 8, x + size - 22, y + 20, color=color, width=3)
        display.line(x + size - 22, y + 20, x + size - 22, y + 10, color=color, width=3)
    elif icon == "outgoing":
        _draw_talk_icon(display, draw, x, y, size, color)
        display.line(x + size - 22, y + 20, x + size - 10, y + 8, color=color, width=3)
        display.line(x + size - 10, y + 8, x + size - 12, y + 20, color=color, width=3)
    elif icon == "live":
        _draw_talk_icon(display, draw, x, y, size, color)
        display.circle(x + size - 10, y + 12, 4, fill=color)
    elif icon == "play":
        _draw_play_icon(display, draw, x, y, size, color)
    elif icon == "retry":
        _draw_retry_icon(display, draw, x, y, size, color)
    elif icon == "close":
        _draw_close_icon(display, draw, x, y, size, color)
    elif icon == "check":
        _draw_check_icon(display, draw, x, y, size, color)
    elif icon == "mic_off":
        _draw_mic_off_icon(display, draw, x, y, size, color)
    else:
        display.circle(x + (size // 2), y + (size // 2), size // 3, outline=color, width=3)


def _paste_phosphor_icon(
    display: Display, icon: str, x: int, y: int, size: int, color: Color
) -> bool:
    """Paste a tinted Phosphor PNG icon when a PIL buffer is available."""

    filename = PHOSPHOR_ICON_FILES.get(icon)
    if filename is None:
        return False

    buffer = _get_buffer(display)
    if buffer is None:
        return False

    source = load_icon_asset(filename)
    if source is None:
        return False

    rendered = source.resize((size, size), Image.Resampling.LANCZOS)
    alpha = rendered.getchannel("A")
    tinted = Image.new("RGBA", rendered.size, color + (0,))
    tinted.putalpha(alpha)
    buffer.paste(tinted, (x, y), tinted)
    return True
def _draw_listen_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(2, size // 14)
    pad = max(4, size // 6)
    ear_width = max(5, size // 7)
    ear_top = y + max(6, size // 3)
    ear_bottom = y + size - pad
    left = x + pad
    top = y + pad
    right = x + size - pad
    bottom = y + size - pad
    if draw is not None:
        draw.arc([(left, top), (right, bottom)], start=200, end=340, fill=color, width=stroke)
    display.rectangle(
        x + pad, ear_top, x + pad + ear_width, ear_bottom, outline=color, width=stroke
    )
    display.rectangle(
        x + size - pad - ear_width, ear_top, x + size - pad, ear_bottom, outline=color, width=stroke
    )
    note_x = x + size - pad - 4
    note_y = y + pad + 2
    display.circle(note_x - 4, note_y + 4, max(2, size // 14), fill=color)
    display.line(note_x, note_y, note_x, note_y + max(10, size // 3), color=color, width=stroke)
    display.line(
        note_x, note_y + 2, note_x + max(4, size // 10), note_y + 4, color=color, width=stroke
    )


def _draw_music_note_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(2, size // 10)
    stem_x = x + max(8, size // 2)
    stem_top = y + max(3, size // 8)
    stem_bottom = y + size - max(8, size // 4)
    left_note_x = x + max(6, size // 4)
    right_note_x = x + size - max(6, size // 4)
    note_y = y + size - max(8, size // 4)
    display.line(stem_x, stem_top, stem_x, stem_bottom, color=color, width=stroke)
    display.line(
        stem_x,
        stem_top + max(1, size // 12),
        right_note_x,
        stem_top + max(5, size // 6),
        color=color,
        width=stroke,
    )
    display.circle(left_note_x, note_y, max(3, size // 7), fill=color)
    display.circle(right_note_x, note_y - max(4, size // 8), max(3, size // 7), fill=color)


def _draw_call_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(2, size // 14)
    handle_left = x + max(4, size // 8)
    handle_top = y + max(10, size // 4)
    handle_right = x + size - max(4, size // 8)
    handle_bottom = y + size - max(10, size // 4)
    rounded_panel(
        display,
        handle_left,
        handle_top,
        handle_right,
        handle_bottom,
        fill=None,
        outline=color,
        radius=max(9, size // 4),
        width=stroke,
    )
    display.line(
        handle_left + max(5, size // 6),
        handle_bottom - max(2, size // 10),
        handle_left + max(1, size // 10),
        handle_bottom + max(5, size // 8),
        color=color,
        width=stroke,
    )
    display.line(
        handle_right - max(5, size // 6),
        handle_top + max(2, size // 10),
        handle_right - max(1, size // 10),
        handle_top - max(5, size // 8),
        color=color,
        width=stroke,
    )


def _draw_talk_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(2, size // 14)
    small_left = x + max(2, size // 20)
    small_top = y + max(9, size // 5)
    small_right = x + max(22, size // 2)
    small_bottom = y + max(30, size // 2 + 6)
    large_left = x + max(16, size // 3)
    large_top = y + max(3, size // 14)
    large_right = x + size - max(4, size // 18)
    large_bottom = y + max(24, size // 2 - 2)
    rounded_panel(
        display,
        small_left,
        small_top,
        small_right,
        small_bottom,
        fill=None,
        outline=color,
        radius=max(7, size // 7),
        width=stroke,
    )
    display.line(
        small_left + 8,
        small_bottom,
        small_left + 5,
        small_bottom + max(5, size // 10),
        color=color,
        width=stroke,
    )
    rounded_panel(
        display,
        large_left,
        large_top,
        large_right,
        large_bottom,
        fill=None,
        outline=color,
        radius=max(7, size // 7),
        width=stroke,
    )
    display.line(
        large_right - 10,
        large_bottom,
        large_right - 6,
        large_bottom + max(6, size // 9),
        color=color,
        width=stroke,
    )
    display.circle(
        large_left + max(10, size // 7),
        large_top + max(10, size // 6),
        max(1, size // 18),
        fill=color,
    )
    display.circle(
        large_left + max(18, size // 3),
        large_top + max(10, size // 6),
        max(1, size // 18),
        fill=color,
    )


def _draw_people_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(2, size // 14)
    head_radius = max(4, size // 9)
    back_head_radius = max(3, size // 10)
    center_x = x + (size // 2)
    display.circle(
        center_x - head_radius - 5,
        y + head_radius + 6,
        back_head_radius,
        outline=color,
        width=stroke,
    )
    display.circle(
        center_x + head_radius - 1, y + head_radius + 4, head_radius, outline=color, width=stroke
    )
    rounded_panel(
        display,
        center_x - 20,
        y + size // 2,
        center_x + 18,
        y + size - 6,
        fill=None,
        outline=color,
        radius=max(8, size // 6),
        width=stroke,
    )
    rounded_panel(
        display,
        center_x - 30,
        y + size // 2 + 6,
        center_x - 2,
        y + size - 10,
        fill=None,
        outline=color,
        radius=max(7, size // 7),
        width=stroke,
    )


def _draw_ask_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(2, size // 14)
    bubble_left = x + max(4, size // 12)
    bubble_top = y + max(4, size // 12)
    bubble_right = x + size - max(4, size // 12)
    bubble_bottom = y + size - max(10, size // 6)
    rounded_panel(
        display,
        bubble_left,
        bubble_top,
        bubble_right,
        bubble_bottom,
        fill=None,
        outline=color,
        radius=max(9, size // 6),
        width=stroke,
    )
    display.line(
        bubble_left + max(10, size // 5),
        bubble_bottom,
        bubble_left + max(6, size // 7),
        bubble_bottom + max(8, size // 7),
        color=color,
        width=stroke,
    )

    center_x = x + (size // 2)
    top_y = y + max(10, size // 5)
    mid_y = y + max(18, size // 2 - 4)
    display.line(
        center_x - max(4, size // 10),
        top_y + max(2, size // 10),
        center_x,
        top_y - max(2, size // 14),
        color=color,
        width=stroke,
    )
    display.line(
        center_x,
        top_y - max(2, size // 14),
        center_x + max(5, size // 9),
        top_y + max(2, size // 10),
        color=color,
        width=stroke,
    )
    display.line(
        center_x + max(5, size // 9),
        top_y + max(2, size // 10),
        center_x + max(2, size // 14),
        mid_y - max(2, size // 12),
        color=color,
        width=stroke,
    )
    display.line(
        center_x + max(2, size // 14),
        mid_y - max(2, size // 12),
        center_x - max(2, size // 14),
        mid_y + max(2, size // 12),
        color=color,
        width=stroke,
    )
    display.circle(center_x, mid_y + max(9, size // 6), max(2, size // 18), fill=color)


def _draw_setup_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(2, size // 14)
    center_x = x + (size // 2)
    center_y = y + (size // 2)
    outer_r = max(10, size // 4)
    tooth_r = max(2, size // 16)
    offset = outer_r + tooth_r + 1

    display.circle(center_x, center_y, outer_r, outline=color, width=stroke)
    for offset_x, offset_y in (
        (0, -offset),
        (offset, 0),
        (0, offset),
        (-offset, 0),
        (offset - 3, -(offset - 3)),
        (-(offset - 3), offset - 3),
    ):
        display.circle(center_x + offset_x, center_y + offset_y, tooth_r, fill=color)


def _draw_care_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(2, size // 12)
    center_x = x + (size // 2)
    center_y = y + (size // 2) + max(1, size // 16)
    inner_r = max(1, size // 18)
    left = x + max(3, size // 8)
    top = y + max(4, size // 5)
    right = x + size - max(3, size // 8)
    bottom = y + size - max(3, size // 8)
    mid_x = center_x
    if draw is not None and hasattr(draw, "line"):
        points = [
            (mid_x, bottom),
            (left, y + max(10, size // 3)),
            (x + max(7, size // 4), top),
            (mid_x, y + max(10, size // 3)),
            (right - max(4, size // 7), top),
            (right, y + max(10, size // 3)),
            (mid_x, bottom),
        ]
        draw.line(points, fill=color, width=stroke, joint="curve")
        return

    display.line(mid_x, bottom, left, y + max(10, size // 3), color=color, width=stroke)
    display.line(
        left, y + max(10, size // 3), x + max(7, size // 4), top, color=color, width=stroke
    )
    display.line(
        x + max(7, size // 4), top, mid_x, y + max(10, size // 3), color=color, width=stroke
    )
    display.line(
        mid_x, y + max(10, size // 3), right - max(4, size // 7), top, color=color, width=stroke
    )
    display.line(
        right - max(4, size // 7), top, right, y + max(10, size // 3), color=color, width=stroke
    )
    display.line(right, y + max(10, size // 3), mid_x, bottom, color=color, width=stroke)
    display.circle(center_x, center_y, inner_r, outline=color, width=stroke)


def _draw_playlist_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    rounded_panel(
        display,
        x + 4,
        y + 6,
        x + size - 4,
        y + size - 8,
        fill=None,
        outline=color,
        radius=10,
        width=3,
    )
    display.line(x + 12, y + 16, x + size - 12, y + 16, color=color, width=3)
    display.line(x + 12, y + 24, x + size - 16, y + 24, color=color, width=3)
    display.line(x + 12, y + 32, x + size - 20, y + 32, color=color, width=3)


def _draw_clock_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(2, size // 14)
    center_x = x + (size // 2)
    center_y = y + (size // 2)
    radius = max(8, size // 3)
    display.circle(center_x, center_y, radius, outline=color, width=stroke)
    display.line(
        center_x, center_y, center_x, center_y - max(5, size // 6), color=color, width=stroke
    )
    display.line(
        center_x,
        center_y,
        center_x + max(5, size // 6),
        center_y + max(2, size // 12),
        color=color,
        width=stroke,
    )


def _draw_play_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    left = x + max(5, size // 5)
    top = y + max(4, size // 6)
    bottom = y + size - max(4, size // 6)
    right = x + size - max(5, size // 5)
    display.line(left, top, right, y + size // 2, color=color, width=max(3, size // 7))
    display.line(left, bottom, right, y + size // 2, color=color, width=max(3, size // 7))
    display.line(left, top, left, bottom, color=color, width=max(3, size // 7))


def _draw_retry_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(2, size // 12)
    center_x = x + (size // 2)
    center_y = y + (size // 2)
    radius = max(8, size // 3)
    if draw is not None and hasattr(draw, "arc"):
        draw.arc(
            [(center_x - radius, center_y - radius), (center_x + radius, center_y + radius)],
            start=40,
            end=320,
            fill=color,
            width=stroke,
        )
    display.line(
        center_x + radius - 3,
        center_y - radius + 4,
        center_x + radius + 4,
        center_y - radius + 10,
        color=color,
        width=stroke,
    )
    display.line(
        center_x + radius - 3,
        center_y - radius + 4,
        center_x + radius - 7,
        center_y - radius + 12,
        color=color,
        width=stroke,
    )


def _draw_close_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(3, size // 8)
    inset = max(6, size // 4)
    display.line(
        x + inset, y + inset, x + size - inset, y + size - inset, color=color, width=stroke
    )
    display.line(
        x + size - inset, y + inset, x + inset, y + size - inset, color=color, width=stroke
    )


def _draw_check_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(3, size // 8)
    display.line(
        x + size // 5,
        y + (size * 3) // 5,
        x + size // 2,
        y + size - size // 5,
        color=color,
        width=stroke,
    )
    display.line(
        x + size // 2,
        y + size - size // 5,
        x + size - size // 5,
        y + size // 4,
        color=color,
        width=stroke,
    )


def _draw_mic_off_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    _draw_setup_icon(display, draw, x + size // 4, y + size // 4, size // 2, color)
    _draw_close_icon(display, draw, x, y, size, color)


def _draw_battery_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(2, size // 14)
    body_left = x + max(3, size // 8)
    body_top = y + max(7, size // 4)
    body_right = x + size - max(7, size // 5)
    body_bottom = y + size - max(7, size // 4)
    rounded_panel(
        display,
        body_left,
        body_top,
        body_right,
        body_bottom,
        fill=None,
        outline=color,
        radius=max(5, size // 8),
        width=stroke,
    )
    display.rectangle(
        body_left + max(4, size // 8),
        body_top + max(4, size // 8),
        body_right - max(4, size // 8),
        body_bottom - max(4, size // 8),
        fill=color,
    )
    tip_left = body_right + max(1, size // 16)
    tip_top = y + (size // 2) - max(4, size // 10)
    display.rectangle(
        tip_left,
        tip_top,
        tip_left + max(4, size // 10),
        tip_top + max(8, size // 5),
        fill=color,
    )


def _draw_signal_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    bar_width = max(3, size // 8)
    gap = max(2, size // 12)
    base_y = y + size - max(4, size // 10)
    heights = (
        max(6, size // 5),
        max(10, size // 3),
        max(14, (size * 2) // 5),
        max(18, (size * 3) // 5),
    )

    for index, height in enumerate(heights):
        left = x + (index * (bar_width + gap))
        top = base_y - height
        display.rectangle(left, top, left + bar_width, base_y, fill=color)


def _voip_state(context: AppContext | None) -> str:
    """Return ready/offline/none for the simplified status bar."""

    if context is None or not context.voip.configured:
        return "none"
    return "ready" if context.voip.ready else "offline"


def format_battery_compact(context: AppContext | None) -> str:
    """Return a tiny battery summary for cards."""

    if context is None or not context.power.available:
        return "Power offline"
    level = context.power.battery_percent
    if context.power.battery_charging:
        return f"{level}% charging"
    return f"{level}% battery"
