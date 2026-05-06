"""Tests for vector-backed theme icons and footer chrome."""

from __future__ import annotations

from yoyopod.ui.screens.theme import FOOTER_BAR, draw_icon, render_footer
from yoyopod.ui.screens.theme_tokens import FOOTER_SAFE_HEIGHT_PORTRAIT


class RecordingDisplay:
    """Minimal display double that records vector drawing calls."""

    WIDTH = 240
    HEIGHT = 280

    def __init__(self) -> None:
        self.lines: list[tuple[int, int, int, int]] = []
        self.circles: list[tuple[int, int, int]] = []
        self.rectangles: list[tuple[int, int, int, int]] = []
        self.text_calls: list[str] = []

    def get_adapter(self):
        return None

    def line(self, x1: int, y1: int, x2: int, y2: int, **_kwargs) -> None:
        self.lines.append((x1, y1, x2, y2))

    def circle(self, x: int, y: int, radius: int, **_kwargs) -> None:
        self.circles.append((x, y, radius))

    def rectangle(self, x1: int, y1: int, x2: int, y2: int, **_kwargs) -> None:
        self.rectangles.append((x1, y1, x2, y2))

    def text(self, text: str, *_args, **_kwargs) -> None:
        self.text_calls.append(text)

    def get_text_size(self, text: str, font_size: int = 16) -> tuple[int, int]:
        return (max(1, len(text)) * max(4, font_size // 2), font_size)

    def is_portrait(self) -> bool:
        return True


def test_draw_icon_uses_vector_primitives_without_asset_fallback() -> None:
    """Theme icons should draw through geometric primitives instead of asset files."""

    display = RecordingDisplay()

    for icon_name in ("listen", "talk", "ask", "setup", "unknown"):
        draw_icon(display, icon_name, 10, 10, 24, (255, 255, 255))

    assert display.lines or display.circles


def test_render_footer_draws_bottom_strip_and_text() -> None:
    """Footer hints should reserve the bottom strip with live vector drawing."""

    display = RecordingDisplay()

    render_footer(display, "Tap next / Open", mode="talk")

    assert display.rectangles[-1] == (
        0,
        display.HEIGHT - FOOTER_SAFE_HEIGHT_PORTRAIT,
        display.WIDTH,
        display.HEIGHT,
    )
    assert display.text_calls
    assert isinstance(FOOTER_BAR, tuple)
    assert len(FOOTER_BAR) == 3
