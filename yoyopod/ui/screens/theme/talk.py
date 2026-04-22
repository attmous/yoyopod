"""Talk/VoIP themed drawing helpers."""

from __future__ import annotations

from yoyopod.ui.display import Display
from yoyopod.ui.screens.theme_text import mix, text_fit
from yoyopod.ui.screens.theme_tokens import BACKGROUND, INK, MUTED, SURFACE_RAISED, TALK, Color

from .icons import draw_icon
from .primitives import rounded_panel


def talk_monogram(name: str, fallback: str = "?") -> str:
    """Return a compact 1-2 character monogram for a contact label."""

    parts = [part for part in name.replace("-", " ").split() if part]
    if not parts:
        return fallback
    if len(parts) == 1:
        return parts[0][:2].upper()
    return f"{parts[0][0]}{parts[1][0]}".upper()


def draw_talk_large_card(
    display: Display,
    *,
    left: int,
    top: int,
    size: int,
    color: Color,
    label: str | None = None,
    icon: str | None = None,
    outlined: bool = False,
) -> tuple[int, int]:
    """Draw the large Talk card used by the person carousel and call states."""

    fill = mix(color, BACKGROUND, 0.78) if outlined else color
    outline = color if outlined else None
    shadow = not outlined
    rounded_panel(
        display,
        left,
        top,
        left + size,
        top + size,
        fill=fill,
        outline=outline,
        radius=16,
        width=2 if outlined else 0,
        shadow=shadow,
    )

    if icon:
        icon_size = 64 if size >= 96 else max(28, size // 2)
        draw_icon(
            display,
            icon,
            left + (size - icon_size) // 2,
            top + (size - icon_size) // 2,
            icon_size,
            color if outlined else INK,
        )
        return left + size, top + size

    if label:
        font_size = 42 if size >= 96 else 22
        label_width, label_height = display.get_text_size(label, font_size)
        display.text(
            label,
            left + (size - label_width) // 2,
            top + (size - label_height) // 2 - 2,
            color=color if outlined else INK,
            font_size=font_size,
        )

    return left + size, top + size


def draw_talk_person_header(
    display: Display,
    *,
    center_x: int,
    top: int,
    name: str,
    label: str | None = None,
    size: str = "small",
    color: Color = TALK.accent,
) -> int:
    """Draw the small Talk person header with monogram/label and name."""

    box_size = 56 if size == "medium" else 48
    left = center_x - (box_size // 2)
    rounded_panel(
        display,
        left,
        top,
        left + box_size,
        top + box_size,
        fill=mix(color, BACKGROUND, 0.85),
        outline=None,
        radius=12,
    )
    avatar = label or talk_monogram(name)
    font_size = 22 if size == "medium" else 18
    avatar_width, avatar_height = display.get_text_size(avatar, font_size)
    display.text(
        avatar,
        center_x - (avatar_width // 2),
        top + ((box_size - avatar_height) // 2) - 1,
        color=color,
        font_size=font_size,
    )
    display_name = text_fit(display, name, 112, 12 if size == "small" else 14)
    name_width, name_height = display.get_text_size(display_name, 12 if size == "small" else 14)
    display.text(
        display_name,
        center_x - (name_width // 2),
        top + box_size + 6,
        color=MUTED,
        font_size=12 if size == "small" else 14,
    )
    return top + box_size + name_height + 6


def draw_talk_action_button(
    display: Display,
    *,
    center_x: int,
    center_y: int,
    button_size: str,
    color: Color,
    icon: str,
    filled: bool = False,
    active: bool = True,
) -> tuple[int, int, int, int]:
    """Draw a circular Talk action button."""

    diameter = {
        "large": 88,
        "medium": 64,
        "small": 56,
    }.get(button_size, 64)
    left = center_x - (diameter // 2)
    top = center_y - (diameter // 2)

    base_color = color if active else mix(color, BACKGROUND, 0.45)
    fill = color if filled else SURFACE_RAISED
    if filled and not active:
        fill = mix(color, BACKGROUND, 0.45)
    outline = None if filled else base_color
    rounded_panel(
        display,
        left,
        top,
        left + diameter,
        top + diameter,
        fill=fill,
        outline=outline,
        radius=diameter // 2,
        width=2 if not filled else 0,
        shadow=filled and active,
    )

    icon_size = {
        "large": 48,
        "medium": 40,
        "small": 28,
    }.get(button_size, 40)
    icon_color = INK if filled else base_color
    if filled and not active:
        icon_color = mix(INK, BACKGROUND, 0.45)
    draw_icon(
        display,
        icon,
        center_x - (icon_size // 2),
        center_y - (icon_size // 2),
        icon_size,
        icon_color,
    )
    return left, top, left + diameter, top + diameter


def draw_talk_page_dots(
    display: Display,
    *,
    center_x: int,
    top: int,
    total: int,
    current: int,
    color: Color = TALK.accent,
) -> None:
    """Draw centered Talk pagination dots."""

    if total <= 0:
        return
    gap = 14
    total_width = ((total - 1) * gap) + 8
    start_x = center_x - (total_width // 2)
    for index in range(total):
        radius = 4 if index == current else 3
        fill = color if index == current else mix(color, BACKGROUND, 0.72)
        display.circle(start_x + (index * gap), top, radius, fill=fill)


def draw_talk_status_chip(
    display: Display,
    *,
    center_x: int,
    top: int,
    text: str,
    color: Color,
    icon: str | None = None,
) -> int:
    """Draw a centered pill chip used across Talk call and voice-note states."""

    from .primitives import _pill

    font_size = 12
    text_width, text_height = display.get_text_size(text, font_size)
    icon_width = 0
    if icon:
        icon_width = 16
    chip_width = text_width + icon_width + 24
    left = center_x - (chip_width // 2)
    rounded_panel(
        display,
        left,
        top,
        left + chip_width,
        top + text_height + 10,
        fill=mix(color, BACKGROUND, 0.85),
        outline=None,
        radius=14,
    )
    text_x = left + 12
    if icon:
        draw_icon(display, icon, left + 9, top + 5, 12, color)
        text_x += 14
    display.text(text, text_x, top + 4, color=color, font_size=font_size)
    return top + text_height + 10
