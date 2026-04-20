"""LVGL-backed view for the Talk contact deck."""

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
    from yoyopod.ui.screens.voip.quick_call import CallScreen


@dataclass(slots=True)
class LvglCallView:
    """Own the LVGL object lifecycle for the people-first Talk screen."""

    scene_key: ClassVar[str] = "talk"
    screen: "CallScreen"
    backend: LvglDisplayBackend
    _built: bool = False
    _build_generation: int = -1

    def build(self) -> None:
        if not should_build_retained_view(self):
            return
        self.backend.binding.talk_build()
        mark_retained_view_built(self)

    def sync(self) -> None:
        if not ensure_retained_view_built(self):
            return

        model = self.screen.current_card_model()
        context = self.screen.context
        sync_network_status(self.backend.binding, context)
        self.backend.binding.talk_sync(
            title_text=str(model.get("title") or "Talk"),
            icon_key=str(model.get("icon_key")) if model.get("icon_key") is not None else None,
            outlined=bool(model.get("outlined", False)),
            footer="Tap Next | 2x Open | Hold Back",
            accent=TALK.accent,
            selected_index=int(model.get("selected_index", 0)),
            total_cards=max(1, int(model.get("total_cards", 0))),
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=context.power.battery_charging if context is not None else False,
            power_available=context.power.available if context is not None else True,
        )

    def destroy(self) -> None:
        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.talk_destroy()
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
