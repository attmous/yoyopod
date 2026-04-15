"""Icon asset loading helpers for YoyoPod themes."""

from __future__ import annotations

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
ICON_CACHE: dict[str, Image.Image] = {}


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
