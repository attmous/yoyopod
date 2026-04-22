"""Theme rendering primitives for YoyoPod screens.

Kept as a package to preserve the legacy import path while splitting internal
concerns into focused submodules.
"""

from __future__ import annotations

from yoyopod.ui.screens.theme_text import mix, text_fit, wrap_text
from yoyopod.ui.screens.theme_tokens import (
    ASK,
    BACKGROUND,
    ERROR,
    FOOTER_BAR,
    FOOTER_SAFE_HEIGHT_LANDSCAPE,
    FOOTER_SAFE_HEIGHT_PORTRAIT,
    HEADER_SIDE_INSET_LANDSCAPE,
    HEADER_SIDE_INSET_PORTRAIT,
    INK,
    LISTEN,
    ModeTheme,
    MUTED,
    MUTED_DIM,
    NEUTRAL,
    SETUP,
    SUCCESS,
    SURFACE,
    SURFACE_BORDER,
    SURFACE_RAISED,
    TALK,
    WARNING,
    theme_for,
)

from .chrome import draw_empty_state, draw_list_item, render_footer, render_header
from .icons import draw_icon
from .primitives import rounded_panel
from .status_bar import format_battery_compact, render_backdrop, render_status_bar
from .talk import (
    draw_talk_action_button,
    draw_talk_large_card,
    draw_talk_page_dots,
    draw_talk_person_header,
    draw_talk_status_chip,
    talk_monogram,
)

__all__ = [
    "ASK",
    "BACKGROUND",
    "ERROR",
    "FOOTER_BAR",
    "FOOTER_SAFE_HEIGHT_LANDSCAPE",
    "FOOTER_SAFE_HEIGHT_PORTRAIT",
    "HEADER_SIDE_INSET_LANDSCAPE",
    "HEADER_SIDE_INSET_PORTRAIT",
    "INK",
    "LISTEN",
    "ModeTheme",
    "MUTED",
    "MUTED_DIM",
    "NEUTRAL",
    "SETUP",
    "SUCCESS",
    "SURFACE",
    "SURFACE_BORDER",
    "SURFACE_RAISED",
    "TALK",
    "WARNING",
    "draw_empty_state",
    "draw_icon",
    "draw_list_item",
    "draw_talk_action_button",
    "draw_talk_large_card",
    "draw_talk_page_dots",
    "draw_talk_person_header",
    "draw_talk_status_chip",
    "format_battery_compact",
    "mix",
    "render_backdrop",
    "render_footer",
    "render_header",
    "render_status_bar",
    "rounded_panel",
    "talk_monogram",
    "text_fit",
    "theme_for",
    "wrap_text",
]
