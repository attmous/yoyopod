"""Screen chrome helpers (headers, lists, and empty states)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yoyopod.ui.display import Display
from yoyopod.ui.screens.theme_text import mix, text_fit, wrap_text
from yoyopod.ui.screens.theme_tokens import (
    BACKGROUND,
    FOOTER_BAR,
    FOOTER_SAFE_HEIGHT_LANDSCAPE,
    FOOTER_SAFE_HEIGHT_PORTRAIT,
    HEADER_SIDE_INSET_LANDSCAPE,
    HEADER_SIDE_INSET_PORTRAIT,
    INK,
    MUTED,
    MUTED_DIM,
    SURFACE,
    SURFACE_BORDER,
    SURFACE_RAISED,
    theme_for,
)

from .icons import draw_icon
from .primitives import _pill, rounded_panel

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext


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

    from .status_bar import render_backdrop, render_status_bar

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
                page_text,
                display.WIDTH - width - side_inset,
                chip_y + 4,
                color=MUTED,
                font_size=10,
            )
    else:
        title_font_size = 24 if display.is_portrait() else 22
        title_y = chip_y + 6
        if page_text:
            width, _ = display.get_text_size(page_text, 10)
            display.text(
                page_text,
                display.WIDTH - width - side_inset,
                chip_y + 2,
                color=MUTED,
                font_size=10,
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

    del mode
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
