"""Incoming call screen for the Talk flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.voip.call_actions import CallActions
from yoyopod.ui.screens.voip.incoming_call_pil_view import render_incoming_call_pil
from yoyopod.ui.screens.voip.lvgl import LvglIncomingCallView

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.ui.screens.view import ScreenView


class IncomingCallScreen(Screen):
    """Incoming call surface with answer and reject actions."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        *,
        actions: CallActions | None = None,
        caller_address: str = "",
        caller_name: str = "Unknown",
    ) -> None:
        super().__init__(display, context, "IncomingCall")
        self._actions = actions or CallActions()
        self.caller_address = caller_address
        self.caller_name = caller_name
        self.ring_animation_frame = 0
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Create the LVGL view when the screen becomes active."""
        super().enter()
        self.ring_animation_frame = 0
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Leave the retained LVGL incoming-call view alive across transitions."""
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

        self._lvgl_view = LvglIncomingCallView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def render(self) -> None:
        """Render the incoming call screen."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return
        render_incoming_call_pil(self)

    def _answer_call(self) -> None:
        """Answer the incoming call."""
        logger.info("Answering incoming call")
        if self._actions.answer_call is not None:
            self._actions.answer_call()

    def _reject_call(self) -> None:
        """Reject the incoming call."""
        logger.info("Rejecting incoming call")
        if self._actions.reject_call is not None:
            self._actions.reject_call()

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
