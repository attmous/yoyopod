"""LVGL-backed view for the Setup screen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yoyopy.ui.lvgl_binding import LvglDisplayBackend
from yoyopy.ui.screens.theme import SETUP

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens.navigation.power import PowerScreen


@dataclass(slots=True)
class LvglPowerView:
    """Own the LVGL object lifecycle for PowerScreen."""

    screen: "PowerScreen"
    backend: LvglDisplayBackend
    _built: bool = False

    def build(self) -> None:
        if self._built or self.backend.binding is None:
            return
        self.backend.binding.power_build()
        self._built = True

    def sync(self) -> None:
        if not self._built or self.backend.binding is None:
            return

        snapshot = self.screen._get_snapshot()
        status = self.screen._get_status()
        pages = self.screen.build_pages(snapshot=snapshot, status=status)
        if not pages:
            return

        self.screen.page_index %= len(pages)
        active_page = pages[self.screen.page_index]
        items = [f"{label}: {value}" for label, value in active_page.rows[:4]]
        context = self.screen.context

        self.backend.binding.power_sync(
            title_text=active_page.title,
            page_text=None,
            footer="Tap page / Back" if self.screen.is_one_button_mode() else "A page | B back",
            items=items,
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=bool(getattr(context, "battery_charging", False)) if context is not None else False,
            power_available=bool(getattr(context, "power_available", True)) if context is not None else True,
            accent=SETUP.accent,
        )

    def destroy(self) -> None:
        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.power_destroy()
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
