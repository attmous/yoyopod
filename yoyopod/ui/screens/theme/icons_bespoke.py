"""Hand-drawn icon renderers for non-PNG theme glyphs."""

from __future__ import annotations

from yoyopod.ui.display import Display
from yoyopod.ui.screens.theme_tokens import Color

from .primitives import rounded_panel


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

