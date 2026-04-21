"""Outgoing call screen for the Talk flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.voip.outgoing_call_pil_view import render_outgoing_call_pil
from yoyopod.ui.screens.voip.lvgl import LvglOutgoingCallView

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.ui.screens.view import ScreenView


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
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Create the LVGL view when the screen becomes active."""
        super().enter()
        self.ring_animation_frame = 0
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Leave the retained LVGL outgoing-call view alive across transitions."""
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

        self._lvgl_view = LvglOutgoingCallView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def render(self) -> None:
        """Render the outgoing-call screen."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return
        render_outgoing_call_pil(self)

    def _cancel_call(self) -> None:
        """Cancel the outgoing call."""
        logger.info("Canceling outgoing call")
        if self.voip_manager:
            self.voip_manager.hangup()

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
