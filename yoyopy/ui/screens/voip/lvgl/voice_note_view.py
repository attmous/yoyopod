"""LVGL-backed view for the voice-note flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from yoyopy.ui.lvgl_binding import LvglDisplayBackend
from yoyopy.ui.screens.theme import TALK

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens.voip.voice_note import VoiceNoteScreen


@dataclass(slots=True)
class LvglVoiceNoteView:
    """Own the LVGL object lifecycle for VoiceNoteScreen."""

    screen: "VoiceNoteScreen"
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

        context = self.screen.context
        title_text, subtitle_text, footer_text, _icon_key = self.screen.current_view_model()
        items, badges, selected_index = self.screen.current_actions_for_view()
        status_chip_text, status_chip_kind = self.screen.current_status_chip()
        page_text = self.screen._duration_label() or None

        self.backend.binding.playlist_sync(
            title_text=self.screen.recipient_name(),
            page_text=page_text,
            status_chip_text=status_chip_text,
            status_chip_kind=status_chip_kind,
            footer=footer_text,
            items=items,
            badges=badges,
            selected_visible_index=selected_index,
            voip_state=self._voip_state(context),
            battery_percent=self._battery_percent(context),
            charging=bool(getattr(context, "battery_charging", False)) if context is not None else False,
            power_available=bool(getattr(context, "power_available", True)) if context is not None else True,
            accent=TALK.accent,
            empty_title=title_text,
            empty_subtitle=subtitle_text,
            empty_icon_key="voice_note",
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
