"""Future-safe Ask screen placeholder for the Graffiti Buddy redesign."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import ASK, INK, MUTED, render_footer, render_header, rounded_panel, wrap_text, draw_icon

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class AskScreen(Screen):
    """Placeholder surface for the future safe-AI ask mode."""

    def __init__(self, display: Display, context: Optional["AppContext"] = None) -> None:
        super().__init__(display, context, "Ask")

    def render(self) -> None:
        """Render the future Ask mode preview."""
        content_top = render_header(
            self.display,
            self.context,
            mode="ask",
            title="Ask",
            subtitle="A safe question mode for curious kids is coming next.",
            icon="ask",
            show_time=False,
        )

        panel_top = content_top + 8
        panel_bottom = self.display.HEIGHT - 28
        rounded_panel(
            self.display,
            16,
            panel_top,
            self.display.WIDTH - 16,
            panel_bottom,
            fill=(31, 34, 40),
            outline=ASK.accent_dim,
            radius=24,
        )

        draw_icon(self.display, "ask", (self.display.WIDTH // 2) - 24, panel_top + 18, 48, ASK.accent)

        headline = "Future mode"
        headline_width, _ = self.display.get_text_size(headline, 18)
        self.display.text(headline, (self.display.WIDTH - headline_width) // 2, panel_top + 78, color=ASK.accent, font_size=18)

        copy_lines = wrap_text(
            self.display,
            "Kids will be able to ask questions and get calm, parent-safe answers here.",
            self.display.WIDTH - 52,
            12,
            max_lines=3,
        )
        line_y = panel_top + 108
        for line in copy_lines:
            line_width, _ = self.display.get_text_size(line, 12)
            self.display.text(line, (self.display.WIDTH - line_width) // 2, line_y, color=INK, font_size=12)
            line_y += 15

        note_lines = wrap_text(
            self.display,
            "Voice commands, guided prompts, and curiosity cards will live here later.",
            self.display.WIDTH - 56,
            10,
            max_lines=3,
        )
        line_y += 12
        for line in note_lines:
            line_width, _ = self.display.get_text_size(line, 10)
            self.display.text(line, (self.display.WIDTH - line_width) // 2, line_y, color=MUTED, font_size=10)
            line_y += 13

        help_text = "Hold back" if self.is_one_button_mode() else "B back"
        render_footer(self.display, help_text, mode="ask")
        self.display.update()

    def on_select(self, data=None) -> None:
        """Ask is intentionally passive until the future feature lands."""
        return

    def on_back(self, data=None) -> None:
        """Return to the previous screen."""
        self.request_route("back")
