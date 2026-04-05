"""Incoming call screen for the Talk flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.voip.lvgl import LvglIncomingCallView
from yoyopy.ui.screens.theme import INK, MUTED, TALK, draw_icon, render_footer, render_header, rounded_panel, text_fit, wrap_text

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens import ScreenView


class IncomingCallScreen(Screen):
    """Incoming call surface with answer and reject actions."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        voip_manager=None,
        caller_address: str = "",
        caller_name: str = "Unknown",
    ) -> None:
        super().__init__(display, context, "IncomingCall")
        self.voip_manager = voip_manager
        self.caller_address = caller_address
        self.caller_name = caller_name
        self.ring_animation_frame = 0
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Create the LVGL view when the screen becomes active."""
        super().enter()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Tear down any active LVGL view when leaving incoming call."""
        if self._lvgl_view is not None:
            self._lvgl_view.destroy()
            self._lvgl_view = None
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        """Create an LVGL view when the Whisplay renderer is active."""
        if self._lvgl_view is not None:
            return self._lvgl_view

        if getattr(self.display, "backend_kind", "pil") != "lvgl":
            return None

        ui_backend = self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            return None

        self._lvgl_view = LvglIncomingCallView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def render(self) -> None:
        """Render the incoming call screen."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        content_top = render_header(
            self.display,
            self.context,
            mode="talk",
            title="Incoming",
            show_time=False,
            show_mode_chip=False,
        )

        panel_top = content_top + 8
        panel_bottom = self.display.HEIGHT - 28
        rounded_panel(
            self.display,
            16,
            panel_top,
            self.display.WIDTH - 16,
            panel_bottom,
            fill=(32, 35, 42),
            outline=TALK.accent_dim,
            radius=28,
            shadow=True,
        )

        pulse_color = TALK.accent if self.ring_animation_frame % 2 == 0 else TALK.accent_soft
        self.display.circle(self.display.WIDTH // 2, panel_top + 34, 24, outline=pulse_color, width=3)
        draw_icon(self.display, "incoming", (self.display.WIDTH // 2) - 20, panel_top + 14, 40, TALK.accent)
        self.ring_animation_frame += 1

        display_name = text_fit(self.display, self.caller_name, self.display.WIDTH - 52, 20)
        name_width, name_height = self.display.get_text_size(display_name, 20)
        self.display.text(display_name, (self.display.WIDTH - name_width) // 2, panel_top + 76, color=INK, font_size=20)

        lines = wrap_text(self.display, self.caller_address or "Unknown", self.display.WIDTH - 56, 11, max_lines=1)
        line_y = panel_top + 106
        for line in lines:
            width, _ = self.display.get_text_size(line, 11)
            self.display.text(line, (self.display.WIDTH - width) // 2, line_y, color=MUTED, font_size=11)
            line_y += 13

        footer = "Open answer / Hold reject" if self.is_one_button_mode() else "A answer | B reject"
        render_footer(self.display, footer, mode="talk")
        self.display.update()

    def _answer_call(self) -> None:
        """Answer the incoming call."""
        logger.info("Answering incoming call")
        if self.voip_manager and self.voip_manager.answer_call():
            self.request_route("call_answered")

    def _reject_call(self) -> None:
        """Reject the incoming call."""
        logger.info("Rejecting incoming call")
        if self.voip_manager and self.voip_manager.reject_call():
            self.request_route("call_rejected")

    def on_select(self, data=None) -> None:
        """Answer the incoming call."""
        self._answer_call()

    def on_advance(self, data=None) -> None:
        """Incoming-call single tap is intentionally a no-op."""
        return

    def on_call_answer(self, data=None) -> None:
        """Answer from a dedicated call action."""
        self._answer_call()

    def on_back(self, data=None) -> None:
        """Reject the incoming call."""
        self._reject_call()

    def on_call_reject(self, data=None) -> None:
        """Reject from a dedicated call action."""
        self._reject_call()
