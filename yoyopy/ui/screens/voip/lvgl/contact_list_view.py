"""LVGL-backed view for the contact list screen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yoyopy.ui.lvgl_binding import LvglDisplayBackend
from yoyopy.ui.screens.theme import TALK

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens.voip.contact_list import ContactListScreen


@dataclass(slots=True)
class LvglContactListView:
    """Own the LVGL object lifecycle for ContactListScreen."""

    screen: "ContactListScreen"
    backend: LvglDisplayBackend
    _built: bool = False

    def build(self) -> None:
        if self._built or self.backend.binding is None:
            return
        self.backend.binding.playlist_build()
        self._built = True

    def sync(self) -> None:
        if not self._built or self.backend.binding is None:
            return

        visible_items, visible_badges, selected_visible_index = self.screen.get_visible_window()
        context = self.screen.context

        self.backend.binding.playlist_sync(
            title_text="Contacts",
            page_text=None,
            footer="Tap next / Call" if self.screen.is_one_button_mode() else "A call | B back | X/Y move",
            items=visible_items,
            badges=visible_badges,
            selected_visible_index=selected_visible_index,
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=bool(getattr(context, "battery_charging", False)) if context is not None else False,
            power_available=bool(getattr(context, "power_available", True)) if context is not None else True,
            accent=TALK.accent,
            empty_title="No contacts",
            empty_subtitle="Add contacts to call them here.",
            empty_icon_key="talk",
        )

    def destroy(self) -> None:
        if not self._built or self.backend.binding is None:
            return
        self.backend.binding.playlist_destroy()
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
