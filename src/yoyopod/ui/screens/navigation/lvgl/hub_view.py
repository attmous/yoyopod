"""LVGL-backed view for the Whisplay root hub."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, ClassVar

from yoyopod.ui.lvgl_binding import LvglDisplayBackend
from yoyopod.ui.screens.lvgl_lifecycle import (
    ensure_retained_view_built,
    mark_retained_view_built,
    mark_retained_view_destroyed,
    should_build_retained_view,
)
from yoyopod.ui.screens.lvgl_status import sync_network_status
from yoyopod.ui.screens.theme import theme_for

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext
    from yoyopod.ui.screens.navigation.hub import HubScreen


@dataclass(slots=True)
class LvglHubView:
    """Own the LVGL object lifecycle for the root Hub screen."""

    scene_key: ClassVar[str] = "hub"
    screen: "HubScreen"
    backend: LvglDisplayBackend
    _built: bool = False
    _build_generation: int = -1

    def build(self) -> None:
        """Create the native LVGL Hub scene once."""

        if not should_build_retained_view(self):
            return
        self.backend.binding.hub_build()
        mark_retained_view_built(self)

    def sync(self) -> None:
        """Push the current Hub controller state into the native scene."""

        if not ensure_retained_view_built(self):
            return

        cards = self.screen._cards()
        selected_card = cards[self.screen.selected_index % len(cards)]
        theme = theme_for(selected_card.mode)
        context = self.screen.context
        sync_network_status(self.backend.binding, context)

        self.backend.binding.hub_sync(
            icon_key=selected_card.icon,
            title=selected_card.title,
            subtitle="",
            footer="Tap = Next | 2x Tap = Open",
            time_text=datetime.now().strftime("%H:%M"),
            accent=theme.accent,
            selected_index=self.screen.selected_index,
            total_cards=len(cards),
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=bool(getattr(context, "battery_charging", False)) if context is not None else False,
            power_available=bool(getattr(context, "power_available", True)) if context is not None else True,
        )

    def destroy(self) -> None:
        """Tear down the native Hub scene and clear the screen."""

        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.hub_destroy()
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
