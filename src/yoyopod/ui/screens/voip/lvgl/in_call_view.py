"""LVGL-backed view for the in-call screen."""

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
    from yoyopod.ui.screens.voip.in_call import InCallScreen


@dataclass(slots=True)
class LvglInCallView:
    """Own the LVGL object lifecycle for InCallScreen."""

    scene_key: ClassVar[str] = "in_call"
    screen: "InCallScreen"
    backend: LvglDisplayBackend
    _built: bool = False
    _build_generation: int = -1

    def build(self) -> None:
        if not should_build_retained_view(self):
            return
        self.backend.binding.in_call_build()
        mark_retained_view_built(self)

    def sync(self) -> None:
        if not ensure_retained_view_built(self):
            return

        caller_name = "Unknown"
        duration_seconds = 0
        is_muted = False
        if self.screen.voip_manager:
            caller_info = self.screen.voip_manager.get_caller_info()
            caller_name = caller_info.get("display_name", caller_name) or "Unknown"
            duration_seconds = self.screen.voip_manager.get_call_duration()
            is_muted = self.screen.voip_manager.is_muted

        footer = (
            f"Tap = {'Unmute' if is_muted else 'Mute'} | Hold = End"
            if self.screen.is_one_button_mode()
            else f"X {'unmute' if is_muted else 'mute'} | B end"
        )
        context = self.screen.context
        sync_network_status(self.backend.binding, context)

        self.backend.binding.in_call_sync(
            caller_name=caller_name,
            duration_text=f"IN CALL | {self.screen.format_duration(duration_seconds)}",
            mute_text="MUTED" if is_muted else "",
            footer=footer,
            muted=is_muted,
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=bool(getattr(context, "battery_charging", False)) if context is not None else False,
            power_available=bool(getattr(context, "power_available", True)) if context is not None else True,
            accent=TALK.accent,
        )

    def destroy(self) -> None:
        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.in_call_destroy()
        mark_retained_view_destroyed(self)

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
