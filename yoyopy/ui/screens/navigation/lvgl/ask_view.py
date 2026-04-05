"""LVGL-backed view for the Ask placeholder screen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yoyopy.ui.lvgl_binding import LvglDisplayBackend
from yoyopy.ui.screens.theme import ASK

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens.navigation.ask import AskScreen


@dataclass(slots=True)
class LvglAskView:
    """Own the LVGL object lifecycle for AskScreen."""

    screen: "AskScreen"
    backend: LvglDisplayBackend
    _built: bool = False

    def build(self) -> None:
        if self._built or self.backend.binding is None:
            return
        self.backend.binding.ask_build()
        self._built = True

    def sync(self) -> None:
        if not self._built or self.backend.binding is None:
            return

        context = self.screen.context
        self.backend.binding.ask_sync(
            title_text="Coming soon",
            subtitle_text="Safe AI later.",
            footer="Hold back" if self.screen.is_one_button_mode() else "B back",
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=bool(getattr(context, "battery_charging", False)) if context is not None else False,
            power_available=bool(getattr(context, "power_available", True)) if context is not None else True,
            accent=ASK.accent,
        )

    def destroy(self) -> None:
        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.ask_destroy()
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
