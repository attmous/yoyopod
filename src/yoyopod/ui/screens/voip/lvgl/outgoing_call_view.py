"""LVGL-backed view for the outgoing-call screen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from yoyopod.ui.lvgl_binding import LvglDisplayBackend
from yoyopod.ui.screens.lvgl_lifecycle import (
    ensure_retained_view_built,
    mark_retained_view_built,
    mark_retained_view_destroyed,
    should_build_retained_view,
)
from yoyopod.ui.screens.lvgl_status import sync_network_status
from yoyopod.ui.screens.theme import TALK

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext
    from yoyopod.ui.screens.voip.outgoing_call import OutgoingCallScreen


@dataclass(slots=True)
class LvglOutgoingCallView:
    """Own the LVGL object lifecycle for OutgoingCallScreen."""

    scene_key: ClassVar[str] = "outgoing_call"
    screen: "OutgoingCallScreen"
    backend: LvglDisplayBackend
    _built: bool = False
    _build_generation: int = -1

    def build(self) -> None:
        if not should_build_retained_view(self):
            return
        self.backend.binding.outgoing_call_build()
        mark_retained_view_built(self)

    def sync(self) -> None:
        if not ensure_retained_view_built(self):
            return

        callee_name = self.screen.callee_name or "Unknown"
        callee_address = self.screen.callee_address or "Unknown"
        if self.screen.voip_manager:
            caller_info = self.screen.voip_manager.get_caller_info()
            callee_name = caller_info.get("display_name", callee_name) or "Unknown"
            callee_address = caller_info.get("address", callee_address) or "Unknown"

        footer = "Hold = Cancel" if self.screen.is_one_button_mode() else "B cancel"
        context = self.screen.context
        sync_network_status(self.backend.binding, context)

        self.backend.binding.outgoing_call_sync(
            callee_name=callee_name,
            callee_address=callee_address,
            footer=footer,
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=context.power.battery_charging if context is not None else False,
            power_available=context.power.available if context is not None else True,
            accent=TALK.accent,
        )

    def destroy(self) -> None:
        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.outgoing_call_destroy()
        mark_retained_view_destroyed(self)

    @staticmethod
    def _battery_percent(context: "AppContext | None") -> int:
        if context is None:
            return 100
        return max(0, min(100, int(context.power.battery_percent)))

    @staticmethod
    def _voip_state(context: "AppContext | None") -> int:
        if context is None or not context.voip.configured:
            return 0
        return 1 if context.voip.ready else 2
