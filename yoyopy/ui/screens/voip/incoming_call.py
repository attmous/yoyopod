"""Incoming call screen for the Talk flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.voip.lvgl import LvglIncomingCallView
from yoyopy.ui.screens.theme import (
    INK,
    TALK,
    draw_talk_large_card,
    draw_talk_status_chip,
    render_footer,
    render_status_bar,
    talk_monogram,
)

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

        render_status_bar(self.display, self.context, show_time=True)
        card_top = self.display.STATUS_BAR_HEIGHT + 42
        card_left = (self.display.WIDTH - 112) // 2
        draw_talk_large_card(
            self.display,
            left=card_left,
            top=card_top,
            size=112,
            color=TALK.accent,
            label=talk_monogram(self.caller_name or "Unknown"),
        )
        self.ring_animation_frame += 1

        display_name = self.caller_name or "Unknown"
        if len(display_name) > 14:
            display_name = f"{display_name[:13]}..."
        name_width, name_height = self.display.get_text_size(display_name, 20)
        title_y = card_top + 126
        self.display.text(display_name, (self.display.WIDTH - name_width) // 2, title_y, color=INK, font_size=20)
        draw_talk_status_chip(
            self.display,
            center_x=self.display.WIDTH // 2,
            top=title_y + name_height + 10,
            text="INCOMING CALL",
            color=TALK.accent,
        )

        footer = "Tap = Answer | Hold = Decline" if self.is_one_button_mode() else "A answer | B reject"
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

    def on_down(self, data=None) -> None:
        """Incoming-call down is intentionally a no-op."""
        return

    def on_up(self, data=None) -> None:
        """Incoming-call up is intentionally a no-op."""
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
