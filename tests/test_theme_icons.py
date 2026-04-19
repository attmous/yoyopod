"""Tests for image-backed theme icons."""

from __future__ import annotations

from PIL import Image, ImageChops

from yoyopod.ui.display import Display
from yoyopod.ui.screens.theme import FOOTER_BAR, ICON_ASSET_DIR, draw_icon, render_footer
from yoyopod.ui.screens.theme_assets import (
    ICON_VARIANT_CACHE,
    ICON_VARIANT_CACHE_MAXSIZE,
    load_icon_variant,
)


def test_hub_icon_assets_exist_and_are_56px() -> None:
    """The checked-in Hub PNG assets should match the Figma icon export size."""
    expected_files = [
        "hub-listen.png",
        "hub-talk.png",
        "hub-ask.png",
        "hub-setup.png",
    ]

    for filename in expected_files:
        path = ICON_ASSET_DIR / filename
        assert path.exists(), f"Missing icon asset: {filename}"
        with Image.open(path) as image:
            assert image.size == (56, 56)


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

        assert buffer.getpixel((4, display.HEIGHT - 4))[:3] == FOOTER_BAR

        footer_strip = buffer.crop((0, display.HEIGHT - 20, display.WIDTH, display.HEIGHT))
        footer_bar_strip = Image.new(footer_strip.mode, footer_strip.size, FOOTER_BAR)
        assert ImageChops.difference(footer_strip, footer_bar_strip).getbbox() is not None
    finally:
        display.cleanup()


def test_icon_variants_are_cached_by_filename_size_and_color() -> None:
    """Repeated icon draws should reuse the same resized+tinted asset variant."""

    ICON_VARIANT_CACHE.clear()

    first = load_icon_variant("hub-listen.png", 24, (255, 255, 255))
    second = load_icon_variant("hub-listen.png", 24, (255, 255, 255))
    third = load_icon_variant("hub-listen.png", 24, (0, 255, 0))

    assert first is not None
    assert first is second
    assert third is not None
    assert third is not first
    assert len(ICON_VARIANT_CACHE) == 2


def test_icon_variant_cache_uses_lru_eviction() -> None:
    """The icon variant cache should stay bounded and keep recently reused entries."""

    ICON_VARIANT_CACHE.clear()

    retained_key = ("hub-listen.png", 24, (255, 255, 255))
    evicted_key = ("hub-listen.png", 25, (255, 255, 255))

    assert load_icon_variant(*retained_key) is not None
    assert load_icon_variant(*evicted_key) is not None

    for size in range(26, 26 + ICON_VARIANT_CACHE_MAXSIZE - 2):
        assert load_icon_variant("hub-listen.png", size, (255, 255, 255)) is not None

    assert len(ICON_VARIANT_CACHE) == ICON_VARIANT_CACHE_MAXSIZE

    # Touch the original entry again so the next insertion evicts the true least-recently-used item.
    assert load_icon_variant(*retained_key) is not None
    assert load_icon_variant("hub-listen.png", 26 + ICON_VARIANT_CACHE_MAXSIZE - 2, (255, 255, 255))

    assert len(ICON_VARIANT_CACHE) == ICON_VARIANT_CACHE_MAXSIZE
    assert retained_key in ICON_VARIANT_CACHE
    assert evicted_key not in ICON_VARIANT_CACHE
