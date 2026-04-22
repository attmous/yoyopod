"""Outgoing call screen for the Talk flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

from yoyopod.integrations.call import HangupCommand
from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
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
        *,
        app: Any | None = None,
    ) -> None:
        super().__init__(display, context, "OutgoingCall", app=app)
        self._explicit_voip_manager = voip_manager
        self.callee_address = callee_address
        self.callee_name = callee_name
        self.ring_animation_frame = 0
        self._lvgl_view: "ScreenView | None" = None

    @property
    def voip_manager(self) -> object | None:
        """Resolve the current VoIP manager from the constructor or owning app."""

        if self._explicit_voip_manager is not None:
            return self._explicit_voip_manager
        return getattr(self.app, "voip_manager", None)

    def current_callee_info(self) -> tuple[str, str]:
        """Return the best available callee name and address."""

        if self.voip_manager:
            caller_info = self.voip_manager.get_caller_info()
            return (
                str(caller_info.get("display_name", self.callee_name) or "Unknown"),
                str(caller_info.get("address", self.callee_address) or "Unknown"),
            )
        state = getattr(self.app, "states", None)
        if state is not None and hasattr(state, "get"):
            entity = state.get("call.state")
            attrs = {} if entity is None else getattr(entity, "attrs", {})
            return (
                str(attrs.get("caller_name") or self.callee_name or "Unknown"),
                str(attrs.get("caller_address") or self.callee_address or "Unknown"),
            )
        return (self.callee_name or "Unknown", self.callee_address or "Unknown")

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

        self._lvgl_view = LvglOutgoingCallView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def render(self) -> None:
        """Render the outgoing-call screen."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is None:
            raise RuntimeError("OutgoingCallScreen requires an initialized LVGL backend")
        lvgl_view.sync()

    def _cancel_call(self) -> None:
        """Cancel the outgoing call."""
        logger.info("Canceling outgoing call")
        services = getattr(self.app, "services", None)
        if services is not None and hasattr(services, "call"):
            services.call("call", "hangup", HangupCommand())
            return
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
