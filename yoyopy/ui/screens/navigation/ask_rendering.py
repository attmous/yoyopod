"""Presentation helpers for the Ask screen."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yoyopy.ui.screens.navigation.lvgl import LvglAskView
from yoyopy.ui.screens.theme import (
    ASK,
    INK,
    MUTED,
    MUTED_DIM,
    draw_icon,
    render_footer,
    render_header,
    rounded_panel,
    text_fit,
    wrap_text,
)

if TYPE_CHECKING:
    from yoyopy.ui.screens import ScreenView


class AskScreenRenderingMixin:
    """Keep Ask-specific state presentation separate from voice orchestration."""

    def _set_state(self, state: str, headline: str, body: str) -> None:
        """Update the visual state, headline, and body text."""

        self._state = state
        self._headline = headline
        self._body = body

    def _set_response(self, headline: str, body: str) -> None:
        """Transition to the reply state without spoken playback."""

        self._state = "reply"
        self._headline = headline
        self._body = body

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        """Create an LVGL view when the Whisplay renderer is active."""

        if self._lvgl_view is not None:
            return self._lvgl_view

        if getattr(self.display, "backend_kind", "pil") != "lvgl":
            return None

        ui_backend = (
            self.display.get_ui_backend()
            if hasattr(self.display, "get_ui_backend")
            else None
        )
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            return None

        self._lvgl_view = LvglAskView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def current_view_model(self) -> tuple[str, str, str, str]:
        """Return title, subtitle, footer, and icon for the current Ask state."""

        icon_key = "ask"
        if self._headline in {"Mic Muted", "Mic Unavailable", "Voice Off"}:
            icon_key = "mic_off"
        return (self._headline, self._body, self._render_hint_bar(), icon_key)

    def render(self) -> None:
        """Render the current Ask state."""

        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        if self._state == "reply":
            self._render_reply()
        else:
            self._render_icon_state()

    def _render_icon_state(self) -> None:
        """Render idle / listening / thinking states with centered icon circle."""

        content_top = render_header(
            self.display,
            self.context,
            mode="ask",
            title="Ask",
            show_time=False,
            show_mode_chip=False,
        )

        circle_size = 112
        circle_radius = circle_size // 2
        cx = (self.display.WIDTH - circle_size) // 2
        cy = content_top + 12
        circle_fill = self._icon_circle_fill()

        rounded_panel(
            self.display,
            cx,
            cy,
            cx + circle_size,
            cy + circle_size,
            fill=circle_fill,
            outline=None,
            radius=circle_radius,
        )

        icon_size = 56
        icon_x = cx + (circle_size - icon_size) // 2
        icon_y = cy + (circle_size - icon_size) // 2
        draw_icon(self.display, "ask", icon_x, icon_y, icon_size, ASK.accent)

        heading = text_fit(self.display, self._headline, self.display.WIDTH - 40, 20)
        heading_w, _ = self.display.get_text_size(heading, 20)
        heading_y = cy + circle_size + 10
        self.display.text(
            heading,
            (self.display.WIDTH - heading_w) // 2,
            heading_y,
            color=INK,
            font_size=20,
        )

        subtitle_color = MUTED_DIM if self._state == "thinking" else ASK.accent
        subtitle = text_fit(self.display, self._body, self.display.WIDTH - 40, 14)
        subtitle_w, _ = self.display.get_text_size(subtitle, 14)
        subtitle_y = heading_y + 24
        self.display.text(
            subtitle,
            (self.display.WIDTH - subtitle_w) // 2,
            subtitle_y,
            color=subtitle_color,
            font_size=14,
        )

        render_footer(self.display, self._render_hint_bar(), mode="ask")
        self.display.update()

    def _render_reply(self) -> None:
        """Render the reply state with left-aligned wrapped text."""

        content_top = render_header(
            self.display,
            self.context,
            mode="ask",
            title=self._headline,
            show_time=False,
            show_mode_chip=False,
        )

        text_x = 24
        text_y = content_top + 16
        line_height = 23
        max_lines = 8
        text_max_width = self.display.WIDTH - (text_x * 2)
        lines = wrap_text(self.display, self._body, text_max_width, 14, max_lines=max_lines)
        for line in lines:
            self.display.text(
                line,
                text_x,
                text_y,
                color=MUTED,
                font_size=14,
            )
            text_y += line_height

        render_footer(self.display, self._render_hint_bar(), mode="ask")
        self.display.update()

    def _render_hint_bar(self) -> str:
        """Return state-specific hint text for the footer."""

        if self._state == "idle":
            if self.is_one_button_mode():
                return "Double listen / Hold back"
            return "A listen | B back"
        if self._state == "listening":
            if self._quick_command and self.is_one_button_mode():
                return "Speaking..."
            return "Listening..."
        if self._state == "thinking":
            return "Processing..."
        if self._quick_command:
            return "Returning soon"
        if self.is_one_button_mode():
            return "Double ask again / Hold back"
        return "A ask again | B back"

    def _refresh_after_state_change(self) -> None:
        """Refresh the screen after updating the voice UI state."""

        if self.screen_manager is None:
            return
        get_current_screen = getattr(self.screen_manager, "get_current_screen", None)
        refresh_current_screen = getattr(self.screen_manager, "refresh_current_screen", None)
        if callable(get_current_screen) and callable(refresh_current_screen):
            if get_current_screen() is self:
                refresh_current_screen()

    def _icon_circle_fill(self) -> tuple[int, int, int]:
        """Return the blended icon halo color for the current state."""

        if self._state == "listening":
            return (95, 86, 48)
        return (74, 69, 45)
