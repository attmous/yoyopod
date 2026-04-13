"""In-call screen for the Talk flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import (
    ERROR,
    INK,
    SUCCESS,
    TALK,
    draw_talk_large_card,
    draw_talk_status_chip,
    render_footer,
    render_status_bar,
    talk_monogram,
)
from yoyopy.ui.screens.voip.lvgl import LvglInCallView

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens import ScreenView


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
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Create the LVGL view when the screen becomes active."""

        super().enter()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Tear down any active LVGL view when leaving the live call."""

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

        self._lvgl_view = LvglInCallView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    @staticmethod
    def format_duration(seconds: int) -> str:
        """Format call duration as MM:SS."""

        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:02d}"

    def render(self) -> None:
        """Render the active-call screen."""

        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        caller_info = {"display_name": "Unknown", "address": ""}
        duration = 0
        is_muted = False
        if self.voip_manager:
            caller_info = self.voip_manager.get_caller_info()
            duration = self.voip_manager.get_call_duration()
            is_muted = self.voip_manager.is_muted

        render_status_bar(self.display, self.context, show_time=True)
        caller_name = caller_info.get("display_name", "Unknown")
        card_top = self.display.STATUS_BAR_HEIGHT + 42
        card_left = (self.display.WIDTH - 112) // 2
        draw_talk_large_card(
            self.display,
            left=card_left,
            top=card_top,
            size=112,
            color=TALK.accent,
            label=talk_monogram(caller_name),
        )
        name_width, name_height = self.display.get_text_size(caller_name, 20)
        title_y = card_top + 126
        self.display.text(caller_name, (self.display.WIDTH - name_width) // 2, title_y, color=INK, font_size=20)

        duration_text = self.format_duration(duration)
        chip_bottom = draw_talk_status_chip(
            self.display,
            center_x=self.display.WIDTH // 2,
            top=title_y + name_height + 10,
            text=f"IN CALL | {duration_text}",
            color=SUCCESS,
        )

        if is_muted:
            draw_talk_status_chip(
                self.display,
                center_x=self.display.WIDTH // 2,
                top=chip_bottom + 8,
                text="MUTED",
                color=ERROR,
                icon="mic_off",
            )

        footer = (
            f"Tap = {'Unmute' if is_muted else 'Mute'} | Hold = End"
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

    def on_down(self, data=None) -> None:
        """Toggle microphone mute."""

        self._toggle_mute()

    def on_advance(self, data=None) -> None:
        """Toggle microphone mute in one-button mode."""

        self._toggle_mute()
