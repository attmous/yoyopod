"""In-call screen for the Talk flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.voip.in_call_pil_view import render_in_call_pil
from yoyopod.ui.screens.voip.lvgl import LvglInCallView

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.ui.screens.view import ScreenView


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
        """Leave the retained LVGL in-call view alive across transitions."""
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        """Create an LVGL view when the Whisplay renderer is active."""

        if getattr(self.display, "backend_kind", "pil") != "lvgl":
            self._lvgl_view = None
            return None

        ui_backend = (
            self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        )
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            self._lvgl_view = None
            return None

        self._lvgl_view = current_retained_view(self._lvgl_view, ui_backend)
        if self._lvgl_view is not None:
            return self._lvgl_view

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
        render_in_call_pil(self)

    def _hangup_call(self) -> None:
        """End the current call."""

        logger.info("Ending call")
        if self.voip_manager:
            self.voip_manager.hangup()

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
