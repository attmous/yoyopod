"""LVGL-backed view for the Ask placeholder screen."""

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
from yoyopod.ui.screens.theme import ASK

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext
    from yoyopod.ui.screens.navigation.ask import AskScreen


@dataclass(slots=True)
class LvglAskView:
    """Own the LVGL object lifecycle for AskScreen."""

    scene_key: ClassVar[str] = "ask"
    screen: "AskScreen"
    backend: LvglDisplayBackend
    _built: bool = False
    _build_generation: int = -1

    def build(self) -> None:
        if not should_build_retained_view(self):
            return
        self.backend.binding.ask_build()
        mark_retained_view_built(self)

    def sync(self) -> None:
        if not ensure_retained_view_built(self):
            return

        context = self.screen.context
        sync_network_status(self.backend.binding, context)
        title_text, subtitle_text, footer_text, icon_key = self.screen.current_view_model()
        self.backend.binding.ask_sync(
            icon_key=icon_key,
            title_text=title_text,
            subtitle_text=subtitle_text,
            footer=footer_text,
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=context.power.battery_charging if context is not None else False,
            power_available=context.power.available if context is not None else True,
            accent=ASK.accent,
        )

    def destroy(self) -> None:
        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.ask_destroy()
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
