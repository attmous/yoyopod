"""In-call screen for the Talk flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

from yoyopod.integrations.call import HangupCommand, MuteCommand, UnmuteCommand
from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
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
        *,
        app: Any | None = None,
    ) -> None:
        super().__init__(display, context, "InCall", app=app)
        self._explicit_voip_manager = voip_manager
        self._lvgl_view: "ScreenView | None" = None

    @property
    def voip_manager(self) -> object | None:
        """Resolve the current VoIP manager from the constructor or owning app."""

        if self._explicit_voip_manager is not None:
            return self._explicit_voip_manager
        return getattr(self.app, "voip_manager", None)

    def enter(self) -> None:
        """Create the LVGL view when the screen becomes active."""

        super().enter()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Leave the retained LVGL in-call view alive across transitions."""
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

        self._lvgl_view = LvglInCallView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    @staticmethod
    def format_duration(seconds: int) -> str:
        """Format call duration as MM:SS."""

        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:02d}"

    def current_caller_info(self) -> dict[str, object]:
        """Return the best available current caller metadata."""

        if self.voip_manager:
            return dict(self.voip_manager.get_caller_info())
        state = getattr(self.app, "states", None)
        if state is not None and hasattr(state, "get"):
            entity = state.get("call.state")
            attrs = {} if entity is None else getattr(entity, "attrs", {})
            return {
                "display_name": str(attrs.get("caller_name") or "Unknown"),
                "address": str(attrs.get("caller_address") or ""),
            }
        return {"display_name": "Unknown", "address": ""}

    def current_call_duration(self) -> int:
        """Return the best available call duration in seconds."""

        get_call_duration = getattr(self.app, "get_call_duration", None)
        if callable(get_call_duration):
            try:
                return int(get_call_duration())
            except Exception:
                return 0
        if self.voip_manager:
            return int(self.voip_manager.get_call_duration())
        return 0

    def is_call_muted(self) -> bool:
        """Return whether the current call is muted."""

        states = getattr(self.app, "states", None)
        if states is not None and hasattr(states, "get_value"):
            return bool(states.get_value("call.muted", False))
        if self.voip_manager is not None:
            return bool(getattr(self.voip_manager, "is_muted", False))
        return False

    def render(self) -> None:
        """Render the active-call screen."""

        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is None:
            raise RuntimeError("InCallScreen requires an initialized LVGL backend")
        lvgl_view.sync()

    @staticmethod
    def wants_visible_tick_refresh() -> bool:
        """Return True while the in-call duration and mute state are visible."""

        return True

    def refresh_for_visible_tick(self) -> None:
        """Keep the in-call view eligible for generic visible-tick refreshes."""

        return None

    def _hangup_call(self) -> None:
        """End the current call."""

        logger.info("Ending call")
        services = getattr(self.app, "services", None)
        if services is not None and hasattr(services, "call"):
            services.call("call", "hangup", HangupCommand())
            return
        if self.voip_manager:
            self.voip_manager.hangup()

    def _toggle_mute(self) -> None:
        """Toggle microphone mute."""

        logger.info("Toggling mute")
        services = getattr(self.app, "services", None)
        if services is not None and hasattr(services, "call"):
            if self.is_call_muted():
                services.call("call", "unmute", UnmuteCommand())
            else:
                services.call("call", "mute", MuteCommand())
            return
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
