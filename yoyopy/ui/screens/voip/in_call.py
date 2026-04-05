"""In-call screen for the Talk flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import INK, MUTED, TALK, draw_icon, render_footer, render_header, rounded_panel

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class InCallScreen(Screen):
    """Active call screen showing duration and mute state."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        voip_manager=None,
    ) -> None:
        super().__init__(display, context, "InCall")
        self.voip_manager = voip_manager

    @staticmethod
    def format_duration(seconds: int) -> str:
        """Format call duration as MM:SS."""
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:02d}"

    def render(self) -> None:
        """Render the active-call screen."""
        caller_info = {"display_name": "Unknown", "address": ""}
        duration = 0
        is_muted = False
        if self.voip_manager:
            caller_info = self.voip_manager.get_caller_info()
            duration = self.voip_manager.get_call_duration()
            is_muted = self.voip_manager.is_muted

        content_top = render_header(
            self.display,
            self.context,
            mode="talk",
            title="On call",
            subtitle="Stay connected without the phone chaos.",
            icon="live",
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
            fill=(32, 35, 42),
            outline=TALK.accent_dim,
            radius=28,
            shadow=True,
        )

        draw_icon(self.display, "live", (self.display.WIDTH // 2) - 20, panel_top + 12, 40, TALK.accent)

        caller_name = caller_info.get("display_name", "Unknown")
        name_width, name_height = self.display.get_text_size(caller_name, 20)
        self.display.text(caller_name, (self.display.WIDTH - name_width) // 2, panel_top + 70, color=INK, font_size=20)

        duration_text = self.format_duration(duration)
        duration_width, duration_height = self.display.get_text_size(duration_text, 26)
        self.display.text(duration_text, (self.display.WIDTH - duration_width) // 2, panel_top + 106, color=TALK.accent, font_size=26)

        mute_label = "Muted" if is_muted else "Mic on"
        mute_width, _ = self.display.get_text_size(mute_label, 12)
        rounded_panel(
            self.display,
            (self.display.WIDTH - mute_width - 24) // 2,
            panel_top + 148,
            (self.display.WIDTH + mute_width + 24) // 2,
            panel_top + 172,
            fill=TALK.accent_dim,
            outline=None,
            radius=12,
        )
        self.display.text(mute_label, (self.display.WIDTH - mute_width) // 2, panel_top + 154, color=INK if is_muted else TALK.accent, font_size=12)

        footer = (
            f"Tap {'unmute' if is_muted else 'mute'} | Hold hang up"
            if self.is_one_button_mode()
            else f"X {'unmute' if is_muted else 'mute'} | B end call"
        )
        render_footer(self.display, footer, mode="talk")
        self.display.update()

    def _hangup_call(self) -> None:
        """End the current call."""
        logger.info("Ending call")
        if self.voip_manager and self.voip_manager.hangup():
            self.request_route("call_hangup")

    def _toggle_mute(self) -> None:
        """Toggle microphone mute."""
        logger.info("Toggling mute")
        if self.voip_manager:
            self.voip_manager.toggle_mute()

    def on_back(self, data=None) -> None:
        """End the current call."""
        self._hangup_call()

    def on_call_hangup(self, data=None) -> None:
        """End the current call from a dedicated action."""
        self._hangup_call()

    def on_up(self, data=None) -> None:
        """Toggle microphone mute."""
        self._toggle_mute()

    def on_advance(self, data=None) -> None:
        """Toggle microphone mute in one-button mode."""
        self._toggle_mute()
