"""LVGL-backed view for the contact list screen."""

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
from yoyopod.ui.screens.lvgl_scene_keys import LIST_SCENE_KEY
from yoyopod.ui.screens.lvgl_status import sync_network_status
from yoyopod.ui.screens.theme import TALK

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.ui.screens.voip.contact_list import ContactListScreen


@dataclass(slots=True)
class LvglContactListView:
    """Own the LVGL object lifecycle for ContactListScreen."""

    scene_key: ClassVar[str] = LIST_SCENE_KEY
    screen: "ContactListScreen"
    backend: LvglDisplayBackend
    _built: bool = False
    _build_generation: int = -1

    def build(self) -> None:
        if not should_build_retained_view(self):
            return
        self.backend.binding.playlist_build()
        mark_retained_view_built(self)

    def sync(self) -> None:
        if not ensure_retained_view_built(self):
            return

        visible_items, visible_badges, selected_visible_index = self.screen.get_visible_window()
        visible_subtitles = self.screen.get_visible_subtitles()
        visible_icon_keys = self.screen.get_visible_icon_keys()
        context = self.screen.context
        sync_network_status(self.backend.binding, context)

        self.backend.binding.playlist_sync(
            title_text=self.screen.title_text,
            page_text=None,
            footer=self.screen.instruction_text(),
            items=visible_items,
            subtitles=visible_subtitles,
            badges=visible_badges,
            icon_keys=visible_icon_keys,
            selected_visible_index=selected_visible_index,
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=context.power.battery_charging if context is not None else False,
            power_available=context.power.available if context is not None else True,
            accent=TALK.accent,
            empty_title=self.screen.empty_title,
            empty_subtitle=self.screen.empty_subtitle,
            empty_icon_key="talk",
        )

    def destroy(self) -> None:
        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.playlist_destroy()
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
