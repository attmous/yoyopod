"""Tests for image-backed theme icons."""

from __future__ import annotations

from PIL import Image, ImageChops

from yoyopy.ui.display import Display
from yoyopy.ui.screens.theme import BACKGROUND, ICON_ASSET_DIR, draw_icon, render_footer


def test_phosphor_icon_assets_exist_and_are_64px() -> None:
    """The checked-in Phosphor PNG assets should be present at the expected size."""
    expected_files = [
        "headphones.png",
        "phone-call.png",
        "microphone.png",
        "gear-six.png",
    ]

    for filename in expected_files:
        path = ICON_ASSET_DIR / filename
        assert path.exists(), f"Missing icon asset: {filename}"
        with Image.open(path) as image:
            assert image.size == (64, 64)


def test_draw_icon_renders_phosphor_png_into_buffer() -> None:
    """The root-mode icons should render via the PNG asset path on PIL-backed displays."""
    display = Display(simulate=True)
    try:
        buffer = display.get_adapter().buffer
        assert buffer is not None

        icon_names = ["listen", "talk", "ask", "setup"]
        for index, icon_name in enumerate(icon_names):
            draw_icon(display, icon_name, 10 + (index * 40), 10, 24, (255, 255, 255))

        cropped = buffer.crop((0, 0, 200, 50))
        assert cropped.getbbox() is not None
    finally:
        display.cleanup()


def test_render_footer_reserves_a_clean_bottom_strip() -> None:
    """Footer hints should repaint the bottom strip so content cannot collide with them."""
    display = Display(simulate=True)
    try:
        buffer = display.get_adapter().buffer
        assert buffer is not None

        display.rectangle(0, display.HEIGHT - 20, display.WIDTH, display.HEIGHT, fill=(255, 0, 0))
        render_footer(display, "Tap next / Open", mode="talk")

        assert buffer.getpixel((4, display.HEIGHT - 4))[:3] == BACKGROUND

        footer_strip = buffer.crop((0, display.HEIGHT - 20, display.WIDTH, display.HEIGHT))
        background_strip = Image.new(footer_strip.mode, footer_strip.size, BACKGROUND)
        assert ImageChops.difference(footer_strip, background_strip).getbbox() is not None
    finally:
        display.cleanup()
