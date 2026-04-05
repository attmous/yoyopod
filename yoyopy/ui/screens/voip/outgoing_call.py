"""Outgoing call screen for the Talk flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import INK, MUTED, TALK, draw_icon, render_footer, render_header, rounded_panel, text_fit, wrap_text

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class OutgoingCallScreen(Screen):
    """Outgoing call surface while dialing or ringing."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        voip_manager=None,
        callee_address: str = "",
        callee_name: str = "Unknown",
    ) -> None:
        super().__init__(display, context, "OutgoingCall")
        self.voip_manager = voip_manager
        self.callee_address = callee_address
        self.callee_name = callee_name
        self.ring_animation_frame = 0

    def render(self) -> None:
        """Render the outgoing-call screen."""
        callee_name = self.callee_name
        callee_address = self.callee_address
        if self.voip_manager:
            caller_info = self.voip_manager.get_caller_info()
            callee_name = caller_info.get("display_name", callee_name)
            callee_address = caller_info.get("address", callee_address)

        content_top = render_header(
            self.display,
            self.context,
            mode="talk",
            title="Calling",
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
        draw_icon(self.display, "outgoing", (self.display.WIDTH // 2) - 20, panel_top + 14, 40, TALK.accent)
        self.ring_animation_frame += 1

        display_name = text_fit(self.display, callee_name, self.display.WIDTH - 52, 20)
        name_width, name_height = self.display.get_text_size(display_name, 20)
        self.display.text(display_name, (self.display.WIDTH - name_width) // 2, panel_top + 76, color=INK, font_size=20)

        lines = wrap_text(self.display, callee_address or "Unknown address", self.display.WIDTH - 56, 11, max_lines=2)
        line_y = panel_top + 106
        for line in lines:
            width, _ = self.display.get_text_size(line, 11)
            self.display.text(line, (self.display.WIDTH - width) // 2, line_y, color=MUTED, font_size=11)
            line_y += 13

        status_text = "Connecting..."
        status_width, _ = self.display.get_text_size(status_text, 13)
        self.display.text(status_text, (self.display.WIDTH - status_width) // 2, panel_bottom - 58, color=TALK.accent, font_size=13)

        footer = "Hold cancel" if self.is_one_button_mode() else "B cancel"
        render_footer(self.display, footer, mode="talk")
        self.display.update()

    def _cancel_call(self) -> None:
        """Cancel the outgoing call."""
        logger.info("Canceling outgoing call")
        if self.voip_manager and self.voip_manager.hangup():
            self.request_route("call_hangup")

    def on_back(self, data=None) -> None:
        """Cancel the outgoing call."""
        self._cancel_call()

    def on_advance(self, data=None) -> None:
        """Outgoing-call single tap is intentionally a no-op."""
        return

    def on_select(self, data=None) -> None:
        """Outgoing-call double tap is intentionally a no-op."""
        return

    def on_call_hangup(self, data=None) -> None:
        """Cancel the outgoing call from a dedicated action."""
        self._cancel_call()
