"""Shared geometric primitives for theme drawing."""

from __future__ import annotations

from typing import Any

from yoyopod.ui.display import Display
from yoyopod.ui.screens.theme_tokens import Color


def _get_draw(display: Display) -> Any | None:
    """Return an optional adapter-native draw surface when available."""

    adapter = display.get_adapter() if hasattr(display, "get_adapter") else None
    return getattr(adapter, "draw", None)


def _get_buffer(display: Display):
    """Return an optional adapter-native image buffer when available."""

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
    draw: Any,
) -> None:
    """Draw a rounded rectangle using native helpers when available."""

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

