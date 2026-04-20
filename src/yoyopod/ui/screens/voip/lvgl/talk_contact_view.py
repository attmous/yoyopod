"""LVGL-backed view for the Talk contact action screen."""

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
from yoyopod.ui.screens.lvgl_scene_keys import TALK_ACTIONS_SCENE_KEY
from yoyopod.ui.screens.lvgl_status import sync_network_status
from yoyopod.ui.screens.theme import TALK

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext
    from yoyopod.ui.screens.voip.talk_contact import TalkContactScreen


@dataclass(slots=True)
class LvglTalkContactView:
    """Own the LVGL object lifecycle for TalkContactScreen."""

    scene_key: ClassVar[str] = TALK_ACTIONS_SCENE_KEY
    screen: "TalkContactScreen"
    backend: LvglDisplayBackend
    _built: bool = False
    _build_generation: int = -1

    def build(self) -> None:
        if not should_build_retained_view(self):
            return
        self.backend.binding.talk_actions_build()
        mark_retained_view_built(self)

    def sync(self) -> None:
        if not ensure_retained_view_built(self):
            return

        visible_items, _visible_subtitles, selected_visible_index = self.screen.get_visible_actions()
        visible_icon_keys = self.screen.get_visible_action_icons()
        context = self.screen.context
        sync_network_status(self.backend.binding, context)
        self.backend.binding.talk_actions_sync(
            contact_name=self.screen.current_contact_name(),
            title_text=visible_items[selected_visible_index] if visible_items else None,
            status_text=None,
            status_kind=0,
            footer="Tap Next | 2x Select | Hold Back",
            icon_keys=visible_icon_keys,
            color_kinds=[0 for _ in visible_icon_keys],
            action_count=len(visible_items),
            selected_index=selected_visible_index,
            layout_kind=0,
            button_size_kind=0 if self.screen.action_button_size() == "small" else 1,
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=context.power.battery_charging if context is not None else False,
            power_available=context.power.available if context is not None else True,
            accent=TALK.accent,
        )

    def destroy(self) -> None:
        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.talk_actions_destroy()
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
