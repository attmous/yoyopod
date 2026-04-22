"""Graffiti Buddy home splash for standard devices."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.theme import (
    ASK,
    INK,
    LISTEN,
    MUTED,
    SETUP,
    TALK,
    draw_icon,
    render_footer,
    render_status_bar,
    render_backdrop,
    rounded_panel,
)

if TYPE_CHECKING:
    from yoyopod.core import AppContext


class HomeScreen(Screen):
    """A playful splash screen before entering the standard menu."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        app: Any | None = None,
    ) -> None:
        super().__init__(display, context, "Home", app=app)

    def render(self) -> None:
        """Render the YoyoPod splash screen."""
        render_backdrop(self.display, "setup")
        render_status_bar(self.display, self.context, show_time=False)

        title = "YoyoPod"
        subtitle = "Tiny talk. Big adventures."
        title_width, title_height = self.display.get_text_size(title, 30)
        self.display.text(
            title, (self.display.WIDTH - title_width) // 2, 54, color=INK, font_size=30
        )
        subtitle_width, _ = self.display.get_text_size(subtitle, 13)
        self.display.text(
            subtitle, (self.display.WIDTH - subtitle_width) // 2, 88, color=MUTED, font_size=13
        )

        rounded_panel(
            self.display,
            24,
            122,
            self.display.WIDTH - 24,
            206,
            fill=(31, 34, 40),
            outline=SETUP.accent_dim,
            radius=28,
            shadow=True,
        )

        draw_icon(self.display, "listen", 42, 140, 30, LISTEN.accent)
        draw_icon(self.display, "talk", 90, 140, 30, TALK.accent)
        draw_icon(self.display, "ask", 138, 140, 30, ASK.accent)
        draw_icon(self.display, "setup", 186, 140, 30, SETUP.accent)

        mini_text = "Listen · Talk · Ask · Setup"
        mini_width, _ = self.display.get_text_size(mini_text, 12)
        self.display.text(
            mini_text, (self.display.WIDTH - mini_width) // 2, 182, color=INK, font_size=12
        )

        render_footer(self.display, "Press A to open", mode="setup")
        self.display.update()

    def on_select(self, data=None) -> None:
        """Open the standard menu."""
        self.request_route("select")
