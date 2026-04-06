"""LVGL-backed view for the local Listen menu."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yoyopy.ui.lvgl_binding import LvglDisplayBackend
from yoyopy.ui.screens.theme import LISTEN

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens.navigation.listen import ListenScreen


@dataclass(slots=True)
class LvglListenView:
    """Own the LVGL object lifecycle for ListenScreen."""

    screen: "ListenScreen"
    backend: LvglDisplayBackend
    _built: bool = False

    def build(self) -> None:
        """Create the native Listen scene once."""

        if self._built or self.backend.binding is None:
            return
        self.backend.binding.listen_build()
        self._built = True

    def sync(self) -> None:
        """Push the current Listen controller state into the native scene."""

        if not self._built or self.backend.binding is None:
            return

        items = [item.title for item in self.screen.items[:4]]

        footer = "Tap next / Open" if self.screen.is_one_button_mode() else "A open | B back | X/Y move"

        context = self.screen.context
        self.backend.binding.listen_sync(
            page_text=None,
            footer=footer,
            items=items,
            selected_index=self.screen.selected_index,
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=bool(getattr(context, "battery_charging", False)) if context is not None else False,
            power_available=bool(getattr(context, "power_available", True)) if context is not None else True,
            accent=LISTEN.accent,
            empty_title="No music items",
            empty_subtitle="Add local music actions to fill this page.",
        )

    def destroy(self) -> None:
        """Tear down the native Listen scene."""

        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.listen_destroy()
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
