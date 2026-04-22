"""Theme icon dispatch for lightweight vector-style screen icons."""

from __future__ import annotations

from yoyopod.ui.display import Display
from yoyopod.ui.screens.theme_tokens import Color

from .primitives import _get_buffer, _get_draw
from .icons_bespoke import (
    _draw_ask_icon,
    _draw_battery_icon,
    _draw_call_icon,
    _draw_check_icon,
    _draw_clock_icon,
    _draw_close_icon,
    _draw_care_icon,
    _draw_listen_icon,
    _draw_mic_off_icon,
    _draw_music_note_icon,
    _draw_people_icon,
    _draw_play_icon,
    _draw_playlist_icon,
    _draw_retry_icon,
    _draw_setup_icon,
    _draw_signal_icon,
    _draw_talk_icon,
)


def draw_icon(display: Display, icon: str, x: int, y: int, size: int, color: Color) -> None:
    """Draw a lightweight doodle icon."""

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
