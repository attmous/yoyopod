"""Shared text and color helpers for YoyoPod themes."""

from __future__ import annotations

from yoyopod.ui.display import Display
from yoyopod.ui.screens.theme_tokens import Color


def mix(color_a: Color, color_b: Color, ratio: float) -> Color:
    """Return a simple RGB mix."""

    ratio = max(0.0, min(1.0, ratio))
    return (
        int(color_a[0] * (1.0 - ratio) + color_b[0] * ratio),
        int(color_a[1] * (1.0 - ratio) + color_b[1] * ratio),
        int(color_a[2] * (1.0 - ratio) + color_b[2] * ratio),
    )


def text_fit(display: Display, text: str, max_width: int, font_size: int) -> str:
    """Trim text to fit a target width."""

    if display.get_text_size(text, font_size)[0] <= max_width:
        return text

    trimmed = text
    while trimmed and display.get_text_size(f"{trimmed}...", font_size)[0] > max_width:
        trimmed = trimmed[:-1]
    return f"{trimmed}..." if trimmed else "..."


def wrap_text(
    display: Display,
    text: str,
    max_width: int,
    font_size: int,
    max_lines: int = 2,
) -> list[str]:
    """Wrap text into compact lines that fit the provided width."""

    words = text.split()
    if not words:
        return []

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if display.get_text_size(candidate, font_size)[0] <= max_width:
            current = candidate
            continue

        lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break

    if len(lines) < max_lines:
        lines.append(current)

    if len(words) > 1 and len(lines) == max_lines:
        consumed_words = sum(len(line.split()) for line in lines)
        if consumed_words < len(words):
            lines[-1] = text_fit(display, f"{lines[-1]}...", max_width, font_size)

    return lines[:max_lines]
