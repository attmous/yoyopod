"""LVGL-backed view for the incoming-call screen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yoyopy.ui.lvgl_binding import LvglDisplayBackend
from yoyopy.ui.screens.theme import TALK

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens.voip.incoming_call import IncomingCallScreen


@dataclass(slots=True)
class LvglIncomingCallView:
    """Own the LVGL object lifecycle for IncomingCallScreen."""

    screen: "IncomingCallScreen"
    backend: LvglDisplayBackend
    _built: bool = False

    def build(self) -> None:
        """Create the native incoming-call scene once."""

        if self._built or self.backend.binding is None:
            return
        self.backend.binding.incoming_call_build()
        self._built = True

    def sync(self) -> None:
        """Push the current caller state into the native scene."""

        if not self._built or self.backend.binding is None:
            return

        footer = "Open answer / Hold reject" if self.screen.is_one_button_mode() else "A answer | B reject"
        context = self.screen.context

        self.backend.binding.incoming_call_sync(
            caller_name=self.screen.caller_name or "Unknown",
            caller_address=self.screen.caller_address or "Unknown",
            footer=footer,
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=bool(getattr(context, "battery_charging", False)) if context is not None else False,
            power_available=bool(getattr(context, "power_available", True)) if context is not None else True,
            accent=TALK.accent,
        )

    def destroy(self) -> None:
        """Tear down the native incoming-call scene."""

        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.incoming_call_destroy()
        self._built = False

    @staticmethod
    def _battery_percent(context: "AppContext | None") -> int:
        if context is None:
            return 100
        return max(0, min(100, int(getattr(context, "battery_percent", 100))))

    @staticmethod
    def _voip_state(context: "AppContext | None") -> int:
        if context is None or not getattr(context, "voip_configured", False):
            return 0
        return 1 if getattr(context, "voip_ready", False) else 2
