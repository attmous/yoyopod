"""LVGL-backed view for the Whisplay root hub."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from yoyopy.ui.lvgl_binding import LvglDisplayBackend
from yoyopy.ui.screens.theme import theme_for

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens.navigation.hub import HubScreen


@dataclass(slots=True)
class LvglHubView:
    """Own the LVGL object lifecycle for the root Hub screen."""

    screen: "HubScreen"
    backend: LvglDisplayBackend
    _built: bool = False

    def build(self) -> None:
        """Create the native LVGL Hub scene once."""

        if self._built or self.backend.binding is None:
            return
        self.backend.binding.hub_build()
        self._built = True

    def sync(self) -> None:
        """Push the current Hub controller state into the native scene."""

        if not self._built or self.backend.binding is None:
            return

        cards = self.screen._cards()
        selected_card = cards[self.screen.selected_index % len(cards)]
        theme = theme_for(selected_card.mode)
        context = self.screen.context

        self.backend.binding.hub_sync(
            icon_key=selected_card.icon,
            title=selected_card.title,
            subtitle=selected_card.subtitle,
            footer="Tap next / Double open",
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
