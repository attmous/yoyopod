"""Icon asset loading helpers for YoyoPod themes."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PIL import Image

ICON_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "phosphor"
PHOSPHOR_ICON_FILES = {
    "listen": "hub-listen.png",
    "talk": "hub-talk.png",
    "ask": "hub-ask.png",
    "voice_note": "microphone.png",
    "call": "phone-call.png",
    "setup": "hub-setup.png",
    "power": "gear-six.png",
}
ICON_VARIANT_CACHE_MAXSIZE = 64
ICON_CACHE: dict[str, Image.Image] = {}
ICON_VARIANT_CACHE: OrderedDict[tuple[str, int, tuple[int, int, int]], Image.Image] = OrderedDict()


def load_icon_asset(filename: str) -> Image.Image | None:
    """Load and cache one icon asset from disk."""

    cached = ICON_CACHE.get(filename)
    if cached is not None:
        return cached

    path = ICON_ASSET_DIR / filename
    if not path.exists():
        return None

    with Image.open(path) as icon:
        rgba_icon = icon.convert("RGBA")
    ICON_CACHE[filename] = rgba_icon
    return rgba_icon


def load_icon_variant(
    filename: str,
    size: int,
    color: tuple[int, int, int],
) -> Image.Image | None:
    """Load, resize, tint, and cache a reusable icon variant."""

    cache_key = (filename, size, color)
    cached = ICON_VARIANT_CACHE.get(cache_key)
    if cached is not None:
        ICON_VARIANT_CACHE.move_to_end(cache_key)
        return cached

    source = load_icon_asset(filename)
    if source is None:
        return None

    rendered = source.resize((size, size), Image.Resampling.LANCZOS)
    alpha = rendered.getchannel("A")
    tinted = Image.new("RGBA", rendered.size, color + (0,))
    tinted.putalpha(alpha)
    ICON_VARIANT_CACHE[cache_key] = tinted
    if len(ICON_VARIANT_CACHE) > ICON_VARIANT_CACHE_MAXSIZE:
        ICON_VARIANT_CACHE.popitem(last=False)
    return tinted
