"""LVGL-backed view for the local Listen menu."""

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
from yoyopod.ui.screens.theme import LISTEN

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.ui.screens.navigation.listen import ListenScreen


@dataclass(slots=True)
class LvglListenView:
    """Own the LVGL object lifecycle for ListenScreen."""

    scene_key: ClassVar[str] = "listen"
    screen: "ListenScreen"
    backend: LvglDisplayBackend
    _built: bool = False
    _build_generation: int = -1

    def build(self) -> None:
        """Create the native Listen scene once."""

        if not should_build_retained_view(self):
            return
        self.backend.binding.listen_build()
        mark_retained_view_built(self)

    def sync(self) -> None:
        """Push the current Listen controller state into the native scene."""

        if not ensure_retained_view_built(self):
            return

        items = [item.title for item in self.screen.items[:4]]
        subtitles = [item.subtitle for item in self.screen.items[:4]]
        icon_keys = [self.screen.item_icon_key(item.key) for item in self.screen.items[:4]]

        footer = (
            "Tap next / 2x open / Hold back"
            if self.screen.is_one_button_mode()
            else "A open | B back | X/Y move"
        )

        context = self.screen.context
        sync_network_status(self.backend.binding, context)
        self.backend.binding.listen_sync(
            page_text=None,
            footer=footer,
            items=items,
            subtitles=subtitles,
            icon_keys=icon_keys,
            selected_index=self.screen.selected_index,
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=context.power.battery_charging if context is not None else False,
            power_available=context.power.available if context is not None else True,
            accent=LISTEN.accent,
            empty_title="No music items",
            empty_subtitle="Add local music actions to fill this page.",
        )

    def destroy(self) -> None:
        """Tear down the native Listen scene."""

        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.listen_destroy()
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
