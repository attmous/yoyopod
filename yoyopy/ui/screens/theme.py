"""Graffiti Buddy theme primitives for YoyoPod screens."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from yoyopy.ui.display import Display

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext

Color = tuple[int, int, int]

BACKGROUND: Color = (18, 21, 28)
SURFACE: Color = (28, 33, 42)
SURFACE_RAISED: Color = (35, 40, 52)
SURFACE_BORDER: Color = (74, 79, 92)
INK: Color = (243, 247, 250)
MUTED: Color = (153, 160, 173)
MUTED_DIM: Color = (111, 118, 132)
SUCCESS: Color = (61, 221, 83)
ERROR: Color = (255, 103, 93)
FOOTER_SAFE_HEIGHT_PORTRAIT = 20
FOOTER_SAFE_HEIGHT_LANDSCAPE = 18
STATUS_SIDE_INSET_PORTRAIT = 16
STATUS_SIDE_INSET_LANDSCAPE = 10
HEADER_SIDE_INSET_PORTRAIT = 18
HEADER_SIDE_INSET_LANDSCAPE = 16


@dataclass(frozen=True, slots=True)
class ModeTheme:
    """Palette for one product mode."""

    key: str
    label: str
    accent: Color
    accent_soft: Color
    accent_dim: Color


LISTEN = ModeTheme(
    key="listen",
    label="Listen",
    accent=(105, 234, 121),
    accent_soft=(70, 143, 83),
    accent_dim=(52, 89, 60),
)
TALK = ModeTheme(
    key="talk",
    label="Talk",
    accent=(82, 220, 255),
    accent_soft=(58, 136, 159),
    accent_dim=(46, 87, 100),
)
ASK = ModeTheme(
    key="ask",
    label="Ask",
    accent=(255, 213, 73),
    accent_soft=(176, 135, 42),
    accent_dim=(112, 92, 33),
)
SETUP = ModeTheme(
    key="setup",
    label="Setup",
    accent=(183, 190, 200),
    accent_soft=(118, 125, 136),
    accent_dim=(77, 84, 92),
)

THEMES = {
    "listen": LISTEN,
    "music": LISTEN,
    "playlists": LISTEN,
    "now_playing": LISTEN,
    "talk": TALK,
    "call": TALK,
    "contacts": TALK,
    "incoming": TALK,
    "outgoing": TALK,
    "in_call": TALK,
    "ask": ASK,
    "setup": SETUP,
    "power": SETUP,
    "menu": SETUP,
    "home": SETUP,
}

ICON_ASSET_DIR = Path(__file__).resolve().parent / "assets" / "phosphor"
PHOSPHOR_ICON_FILES = {
    "listen": "headphones.png",
    "talk": "phone-call.png",
    "ask": "microphone.png",
    "setup": "gear-six.png",
    "power": "gear-six.png",
}
_ICON_CACHE: dict[str, Image.Image] = {}


def theme_for(mode: str) -> ModeTheme:
    """Return the palette for a mode key."""

    return THEMES.get(mode, SETUP)


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


def _get_draw(display: Display):
    """Return the underlying PIL draw surface when available."""

    adapter = display.get_adapter() if hasattr(display, "get_adapter") else None
    return getattr(adapter, "draw", None)


def _get_buffer(display: Display):
    """Return the underlying PIL image buffer when available."""

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
    draw,
) -> None:
    """Draw a rounded rectangle with a PIL fallback."""

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


def render_backdrop(display: Display, mode: str) -> ModeTheme:
    """Paint the shared Graffiti Buddy backdrop."""

    theme = theme_for(mode)
    display.clear(BACKGROUND)
    return theme


def render_status_bar(
    display: Display,
    context: AppContext | None,
    *,
    show_time: bool,
) -> None:
    """Draw the simplified product status bar."""

    bar_height = display.STATUS_BAR_HEIGHT
    display.rectangle(0, 0, display.WIDTH, bar_height, fill=BACKGROUND)
    side_inset = STATUS_SIDE_INSET_PORTRAIT if display.is_portrait() else STATUS_SIDE_INSET_LANDSCAPE

    voip_state = _voip_state(context)
    dot_x = side_inset
    dot_y = (bar_height // 2) + 1
    if voip_state == "ready":
        display.circle(dot_x, dot_y, 4, fill=SUCCESS)
    elif voip_state == "offline":
        display.circle(dot_x, dot_y, 4, fill=ERROR)

    if show_time:
        time_text = datetime.now().strftime("%H:%M")
        time_x = side_inset + (10 if voip_state != "none" else 0)
        display.text(time_text, time_x, 4, color=INK, font_size=13)

    battery_level = 100 if context is None else context.battery_percent
    charging = False if context is None else context.battery_charging
    power_available = True if context is None else context.power_available

    battery_x = display.WIDTH - side_inset - 22
    battery_y = 6
    display.rectangle(
        battery_x,
        battery_y,
        battery_x + 20,
        battery_y + 10,
        outline=MUTED,
        width=1,
    )
    display.rectangle(
        battery_x + 20,
        battery_y + 3,
        battery_x + 22,
        battery_y + 7,
        fill=MUTED,
    )

    fill_color = MUTED
    if power_available:
        if battery_level <= 20:
            fill_color = ERROR
        elif charging:
            fill_color = SUCCESS
        else:
            fill_color = INK

    fill_width = max(0, min(18, int((max(0, min(100, battery_level)) / 100.0) * 18)))
    if fill_width > 0:
        display.rectangle(
            battery_x + 1,
            battery_y + 1,
            battery_x + 1 + fill_width,
            battery_y + 9,
            fill=fill_color,
        )


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

    theme = render_backdrop(display, mode)
    render_status_bar(display, context, show_time=show_time)
    side_inset = HEADER_SIDE_INSET_PORTRAIT if display.is_portrait() else HEADER_SIDE_INSET_LANDSCAPE

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
            display.text(page_text, display.WIDTH - width - side_inset, chip_y + 4, color=MUTED, font_size=10)
    else:
        title_font_size = 24 if display.is_portrait() else 22
        title_y = chip_y + 6
        if page_text:
            width, _ = display.get_text_size(page_text, 10)
            display.text(page_text, display.WIDTH - width - side_inset, chip_y + 2, color=MUTED, font_size=10)

    max_title_width = display.WIDTH - (side_inset * 2) - 60
    display_title = text_fit(display, title, max_title_width, title_font_size)
    display.text(display_title, side_inset, title_y, color=INK, font_size=title_font_size)

    title_width, title_height = display.get_text_size(display_title, title_font_size)
    display.line(side_inset, title_y + title_height + 6, side_inset + min(title_width + 10, 126), title_y + title_height + 6, color=theme.accent, width=3)

    if subtitle:
        subtitle_y = title_y + title_height + 14
        subtitle_width = display.WIDTH - (side_inset * 2) - (62 if icon else 0)
        lines = wrap_text(display, subtitle, subtitle_width, 12, max_lines=2)
        for line_index, line in enumerate(lines):
            display.text(line, side_inset, subtitle_y + (line_index * 14), color=MUTED, font_size=12)
        bottom_y = subtitle_y + (len(lines) * 14)
    else:
        bottom_y = title_y + title_height + 10

    if icon:
        draw_icon(display, icon, display.WIDTH - side_inset - 44, display.STATUS_BAR_HEIGHT + 18, 44, theme.accent)

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
) -> None:
    """Render one rounded list card."""

    theme = theme_for(mode)
    fill = mix(theme.accent, SURFACE, 0.9) if selected else SURFACE
    outline = theme.accent_soft if selected else SURFACE_BORDER
    rounded_panel(display, x1, y1, x2, y2, fill=fill, outline=outline, radius=16, shadow=False)

    title_color = INK if selected else mix(INK, MUTED, 0.12)
    subtitle_color = mix(theme.accent, MUTED, 0.72) if selected else MUTED
    badge_width = 0
    if badge:
        badge_width = display.get_text_size(badge, 9)[0] + 18

    title_text = text_fit(display, title, x2 - x1 - 26 - badge_width, 15)
    title_height = display.get_text_size(title_text, 15)[1]
    title_y = y1 + 9
    if not subtitle:
        title_y = y1 + max(6, ((y2 - y1) - title_height) // 2)
    display.text(title_text, x1 + 14, title_y, color=title_color, font_size=15)
    if subtitle:
        display.text(text_fit(display, subtitle, x2 - x1 - 26, 10), x1 + 14, y1 + 26, color=subtitle_color, font_size=10)

    if selected:
        display.circle(x1 + 7, y1 + 7, 3, fill=theme.accent)

    if badge:
        _pill(
            display,
            x2 - badge_width - 10,
            y1 + 8,
            badge,
            fill=theme.accent_dim,
            text_color=theme.accent,
            font_size=9,
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
    panel_bottom = min(display.HEIGHT - 28, panel_top + 134)
    rounded_panel(display, panel_left, panel_top, panel_right, panel_bottom, fill=SURFACE, outline=theme.accent_dim, radius=22)
    draw_icon(display, icon, (display.WIDTH // 2) - 22, panel_top + 16, 44, theme.accent)

    title_width, title_height = display.get_text_size(title, 16)
    display.text(title, (display.WIDTH - title_width) // 2, panel_top + 68, color=INK, font_size=16)

    lines = wrap_text(display, subtitle, panel_right - panel_left - 26, 11, max_lines=2)
    line_y = panel_top + 92
    for line in lines:
        line_width, _ = display.get_text_size(line, 11)
        display.text(line, (display.WIDTH - line_width) // 2, line_y, color=MUTED, font_size=11)
        line_y += 13


def render_footer(display: Display, text: str, *, mode: str) -> None:
    """Draw the bottom helper hint."""

    if not text:
        return

    theme = theme_for(mode)
    font_size = 9 if display.is_portrait() else 10
    footer_width, footer_height = display.get_text_size(text, font_size)
    footer_safe_height = FOOTER_SAFE_HEIGHT_PORTRAIT if display.is_portrait() else FOOTER_SAFE_HEIGHT_LANDSCAPE
    footer_top = display.HEIGHT - footer_safe_height

    # Reserve a clean bottom strip so helper text never collides with panels or list rows.
    display.rectangle(0, footer_top, display.WIDTH, display.HEIGHT, fill=BACKGROUND)

    footer_x = (display.WIDTH - footer_width) // 2
    footer_y = footer_top + max(0, (footer_safe_height - footer_height) // 2) - 1
    display.text(text, footer_x, footer_y, color=mix(theme.accent, MUTED, 0.72), font_size=font_size)


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


def draw_icon(display: Display, icon: str, x: int, y: int, size: int, color: Color) -> None:
    """Draw a lightweight doodle icon."""

    if _paste_phosphor_icon(display, icon, x, y, size, color):
        return

    draw = _get_draw(display)
    if icon == "listen":
        _draw_listen_icon(display, draw, x, y, size, color)
    elif icon == "talk":
        _draw_talk_icon(display, draw, x, y, size, color)
    elif icon == "ask":
        _draw_ask_icon(display, draw, x, y, size, color)
    elif icon in {"setup", "power"}:
        _draw_setup_icon(display, draw, x, y, size, color)
    elif icon == "playlist":
        _draw_playlist_icon(display, draw, x, y, size, color)
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
    else:
        display.circle(x + (size // 2), y + (size // 2), size // 3, outline=color, width=3)


def _paste_phosphor_icon(display: Display, icon: str, x: int, y: int, size: int, color: Color) -> bool:
    """Paste a tinted Phosphor PNG icon when a PIL buffer is available."""

    filename = PHOSPHOR_ICON_FILES.get(icon)
    if filename is None:
        return False

    buffer = _get_buffer(display)
    if buffer is None:
        return False

    source = _load_icon_asset(filename)
    if source is None:
        return False

    rendered = source.resize((size, size), Image.Resampling.LANCZOS)
    alpha = rendered.getchannel("A")
    tinted = Image.new("RGBA", rendered.size, color + (0,))
    tinted.putalpha(alpha)
    buffer.paste(tinted, (x, y), tinted)
    return True


def _load_icon_asset(filename: str) -> Image.Image | None:
    """Load and cache one PNG icon asset from disk."""

    cached = _ICON_CACHE.get(filename)
    if cached is not None:
        return cached

    path = ICON_ASSET_DIR / filename
    if not path.exists():
        return None

    with Image.open(path) as icon:
        rgba_icon = icon.convert("RGBA")
    _ICON_CACHE[filename] = rgba_icon
    return rgba_icon


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
    display.rectangle(x + pad, ear_top, x + pad + ear_width, ear_bottom, outline=color, width=stroke)
    display.rectangle(x + size - pad - ear_width, ear_top, x + size - pad, ear_bottom, outline=color, width=stroke)
    note_x = x + size - pad - 4
    note_y = y + pad + 2
    display.circle(note_x - 4, note_y + 4, max(2, size // 14), fill=color)
    display.line(note_x, note_y, note_x, note_y + max(10, size // 3), color=color, width=stroke)
    display.line(note_x, note_y + 2, note_x + max(4, size // 10), note_y + 4, color=color, width=stroke)


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
    rounded_panel(display, small_left, small_top, small_right, small_bottom, fill=None, outline=color, radius=max(7, size // 7), width=stroke)
    display.line(small_left + 8, small_bottom, small_left + 5, small_bottom + max(5, size // 10), color=color, width=stroke)
    rounded_panel(display, large_left, large_top, large_right, large_bottom, fill=None, outline=color, radius=max(7, size // 7), width=stroke)
    display.line(large_right - 10, large_bottom, large_right - 6, large_bottom + max(6, size // 9), color=color, width=stroke)
    display.circle(large_left + max(10, size // 7), large_top + max(10, size // 6), max(1, size // 18), fill=color)
    display.circle(large_left + max(18, size // 3), large_top + max(10, size // 6), max(1, size // 18), fill=color)


def _draw_ask_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(2, size // 14)
    bubble_left = x + max(4, size // 12)
    bubble_top = y + max(4, size // 12)
    bubble_right = x + size - max(4, size // 12)
    bubble_bottom = y + size - max(10, size // 6)
    rounded_panel(display, bubble_left, bubble_top, bubble_right, bubble_bottom, fill=None, outline=color, radius=max(9, size // 6), width=stroke)
    display.line(bubble_left + max(10, size // 5), bubble_bottom, bubble_left + max(6, size // 7), bubble_bottom + max(8, size // 7), color=color, width=stroke)

    center_x = x + (size // 2)
    top_y = y + max(10, size // 5)
    mid_y = y + max(18, size // 2 - 4)
    display.line(center_x - max(4, size // 10), top_y + max(2, size // 10), center_x, top_y - max(2, size // 14), color=color, width=stroke)
    display.line(center_x, top_y - max(2, size // 14), center_x + max(5, size // 9), top_y + max(2, size // 10), color=color, width=stroke)
    display.line(center_x + max(5, size // 9), top_y + max(2, size // 10), center_x + max(2, size // 14), mid_y - max(2, size // 12), color=color, width=stroke)
    display.line(center_x + max(2, size // 14), mid_y - max(2, size // 12), center_x - max(2, size // 14), mid_y + max(2, size // 12), color=color, width=stroke)
    display.circle(center_x, mid_y + max(9, size // 6), max(2, size // 18), fill=color)


def _draw_setup_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    stroke = max(2, size // 14)
    center_x = x + (size // 2)
    center_y = y + (size // 2)
    outer_r = max(10, size // 4)
    inner_r = max(4, size // 10)
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
    display.circle(center_x, center_y, inner_r, outline=color, width=stroke)


def _draw_playlist_icon(display: Display, draw, x: int, y: int, size: int, color: Color) -> None:
    rounded_panel(display, x + 4, y + 6, x + size - 4, y + size - 8, fill=None, outline=color, radius=10, width=3)
    display.line(x + 12, y + 16, x + size - 12, y + 16, color=color, width=3)
    display.line(x + 12, y + 24, x + size - 16, y + 24, color=color, width=3)
    display.line(x + 12, y + 32, x + size - 20, y + 32, color=color, width=3)


def _voip_state(context: AppContext | None) -> str:
    """Return ready/offline/none for the simplified status bar."""

    if context is None or not getattr(context, "voip_configured", False):
        return "none"
    return "ready" if getattr(context, "voip_ready", False) else "offline"


def audio_source_label(source: str | None) -> str:
    """Format a human-readable audio source label."""

    if not source:
        return "Local"
    normalized = source.strip().lower()
    return {
        "spotify": "Spotify",
        "amazon": "Amazon",
        "youtube": "YouTube",
        "local": "Local",
    }.get(normalized, normalized.title())


def audio_source_subtitle(source: str | None) -> str:
    """Return a playful source subtitle."""

    normalized = (source or "local").strip().lower()
    return {
        "spotify": "Mixes and streaming picks",
        "amazon": "Albums and family playlists",
        "youtube": "Videos and saved clips",
        "local": "On-device playlists",
    }.get(normalized, "Configured music source")


def format_battery_compact(context: AppContext | None) -> str:
    """Return a tiny battery summary for cards."""

    if context is None or not getattr(context, "power_available", False):
        return "Power offline"
    level = getattr(context, "battery_percent", 100)
    if getattr(context, "battery_charging", False):
        return f"{level}% charging"
    return f"{level}% battery"
