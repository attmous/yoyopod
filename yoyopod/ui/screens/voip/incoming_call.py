"""Incoming call screen for the Talk flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

from yoyopod.integrations.call import AnswerCommand, RejectCommand
from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
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
        voip_manager=None,
        caller_address: str = "",
        caller_name: str = "Unknown",
        *,
        app: Any | None = None,
    ) -> None:
        super().__init__(display, context, "IncomingCall", app=app)
        self._explicit_voip_manager = voip_manager
        self.caller_address = caller_address
        self.caller_name = caller_name
        self.ring_animation_frame = 0
        self._lvgl_view: "ScreenView | None" = None

    @property
    def voip_manager(self) -> object | None:
        """Resolve the current VoIP manager from the constructor or owning app."""

        if self._explicit_voip_manager is not None:
            return self._explicit_voip_manager
        return getattr(self.app, "voip_manager", None)

    def current_caller_name(self) -> str:
        """Return the best available caller name for the incoming call."""

        if self.caller_name.strip():
            return self.caller_name
        state = getattr(self.app, "states", None)
        if state is not None and hasattr(state, "get"):
            entity = state.get("call.state")
            attrs = {} if entity is None else getattr(entity, "attrs", {})
            name = str(attrs.get("caller_name") or "").strip()
            if name:
                return name
        return "Unknown"

    def current_caller_address(self) -> str:
        """Return the best available caller address for the incoming call."""

        if self.caller_address.strip():
            return self.caller_address
        state = getattr(self.app, "states", None)
        if state is not None and hasattr(state, "get"):
            entity = state.get("call.state")
            attrs = {} if entity is None else getattr(entity, "attrs", {})
            address = str(attrs.get("caller_address") or "").strip()
            if address:
                return address
        return "Unknown"

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
        if getattr(self.display, "backend_kind", "unavailable") != "lvgl":
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
        if lvgl_view is None:
            raise RuntimeError("IncomingCallScreen requires an initialized LVGL backend")
        lvgl_view.sync()

    def _answer_call(self) -> None:
        """Answer the incoming call."""
        logger.info("Answering incoming call")
        services = getattr(self.app, "services", None)
        if services is not None and hasattr(services, "call"):
            services.call("call", "answer", AnswerCommand())
            return
        if self.voip_manager:
            self.voip_manager.answer_call()

    def _reject_call(self) -> None:
        """Reject the incoming call."""
        logger.info("Rejecting incoming call")
        services = getattr(self.app, "services", None)
        if services is not None and hasattr(services, "call"):
            services.call("call", "reject", RejectCommand())
            return
        if self.voip_manager:
            self.voip_manager.reject_call()

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
