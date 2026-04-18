"""LVGL-backed view for the Setup screen."""

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
from yoyopod.ui.screens.theme import SETUP

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext
    from yoyopod.ui.screens.system.power import PowerScreen


@dataclass(slots=True)
class LvglPowerView:
    """Own the LVGL object lifecycle for PowerScreen."""

    scene_key: ClassVar[str] = "power"
    screen: "PowerScreen"
    backend: LvglDisplayBackend
    _built: bool = False
    _build_generation: int = -1

    def build(self) -> None:
        if not should_build_retained_view(self):
            return
        self.backend.binding.power_build()
        mark_retained_view_built(self)

    def sync(self) -> None:
        if not ensure_retained_view_built(self):
            return

        payload = self.screen.lvgl_payload()
        context = self.screen.context
        sync_network_status(self.backend.binding, context)

        self.backend.binding.power_sync(
            title_text=payload.title_text,
            page_text=payload.page_text,
            icon_key=payload.icon_key,
            footer=payload.footer,
            items=list(payload.items),
            current_page_index=payload.current_page_index,
            total_pages=payload.total_pages,
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=(
                bool(getattr(context, "battery_charging", False)) if context is not None else False
            ),
            power_available=(
                bool(getattr(context, "power_available", True)) if context is not None else True
            ),
            accent=SETUP.accent,
        )

    def destroy(self) -> None:
        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.power_destroy()
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
