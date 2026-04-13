"""Recent-call history screen for the Talk flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import (
    draw_empty_state,
    draw_list_item,
    render_footer,
    render_header,
    text_fit,
)
from yoyopy.ui.screens.voip.lvgl.call_history_view import LvglCallHistoryView

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens import ScreenView
    from yoyopy.voip import CallHistoryEntry, CallHistoryStore


class CallHistoryScreen(Screen):
    """Show recent and missed calls, with quick redial when possible."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        voip_manager=None,
        call_history_store: Optional["CallHistoryStore"] = None,
    ) -> None:
        super().__init__(display, context, "CallHistory")
        self.voip_manager = voip_manager
        self.call_history_store = call_history_store
        self.entries: list["CallHistoryEntry"] = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.max_visible_items = 4 if display.is_portrait() else 5
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Refresh call history and clear the unseen-missed badge count."""
        super().enter()
        self._load_entries()
        if self.call_history_store is not None:
            self.call_history_store.mark_all_seen()
            self._sync_context_summary()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Tear down any active LVGL view when leaving recents."""
        if self._lvgl_view is not None:
            self._lvgl_view.destroy()
            self._lvgl_view = None
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        if self._lvgl_view is not None:
            return self._lvgl_view

        if getattr(self.display, "backend_kind", "pil") != "lvgl":
            return None

        ui_backend = self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            return None

        self._lvgl_view = LvglCallHistoryView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def _load_entries(self) -> None:
        """Load the recent calls from persistent storage."""
        if self.call_history_store is None:
            self.entries = []
        else:
            self.entries = self.call_history_store.list_recent()
        if self.entries:
            self.selected_index = min(self.selected_index, len(self.entries) - 1)
        else:
            self.selected_index = 0
            self.scroll_offset = 0

    def _sync_context_summary(self) -> None:
        """Refresh the shared Talk summary after opening recents."""
        if self.context is None or self.call_history_store is None:
            return

        self.context.update_call_summary(
            missed_calls=self.call_history_store.missed_count(),
            recent_calls=self.call_history_store.recent_preview(),
        )

    def _is_ready_to_call(self) -> bool:
        """Return whether VoIP is ready to redial from recents."""
        if self.voip_manager is None:
            return False
        status = self.voip_manager.get_status()
        return bool(status.get("running")) and bool(status.get("registered"))

    def _selected_entry(self) -> "CallHistoryEntry | None":
        if not self.entries:
            return None
        return self.entries[self.selected_index]

    def _instruction_text(self) -> str:
        """Return compact footer hints for recents."""
        if not self.entries:
            return "Hold back" if self.is_one_button_mode() else "B back"
        if self._is_ready_to_call():
            return "Tap next / Double call" if self.is_one_button_mode() else "A call | B back | X/Y move"
        return "Tap next / Hold back" if self.is_one_button_mode() else "B back | X/Y move"

    def render(self) -> None:
        """Render the recent-calls list."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        content_top = render_header(
            self.display,
            self.context,
            mode="talk",
            title="Recents",
            page_text=None,
            show_time=False,
            show_mode_chip=False,
        )

        if not self.entries:
            draw_empty_state(
                self.display,
                mode="talk",
                title="No recent calls",
                subtitle="Calls will show up here after the first one.",
                icon="talk",
                top=content_top,
            )
            render_footer(self.display, "Hold back", mode="talk")
            self.display.update()
            return

        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + self.max_visible_items:
            self.scroll_offset = self.selected_index - self.max_visible_items + 1

        item_height = 52
        list_top = content_top + 8
        for row in range(self.max_visible_items):
            entry_index = self.scroll_offset + row
            if entry_index >= len(self.entries):
                break

            entry = self.entries[entry_index]
            y1 = list_top + (row * item_height)
            y2 = y1 + 44
            draw_list_item(
                self.display,
                x1=18,
                y1=y1,
                x2=self.display.WIDTH - 18,
                y2=y2,
                title=text_fit(self.display, entry.title, self.display.WIDTH - 90, 15),
                subtitle=entry.subtitle,
                mode="talk",
                selected=entry_index == self.selected_index,
                badge=None,
                icon="call" if entry.direction == "outgoing" else "talk",
            )

        render_footer(self.display, self._instruction_text(), mode="talk")
        self.display.update()

    def get_visible_window(self) -> tuple[list[str], list[str], int]:
        """Return the visible recent-call titles for the shared LVGL list scene."""
        if not self.entries:
            return [], [], 0

        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + self.max_visible_items:
            self.scroll_offset = self.selected_index - self.max_visible_items + 1

        visible_titles: list[str] = []
        visible_badges: list[str] = []
        selected_visible_index = 0
        for row in range(self.max_visible_items):
            entry_index = self.scroll_offset + row
            if entry_index >= len(self.entries):
                break

            entry = self.entries[entry_index]
            visible_titles.append(entry.title)
            visible_badges.append("")
            if entry_index == self.selected_index:
                selected_visible_index = row

        return visible_titles, visible_badges, selected_visible_index

    def get_visible_subtitles(self) -> list[str]:
        """Return visible subtitles for the shared LVGL scene."""

        if not self.entries:
            return []

        subtitles: list[str] = []
        for row in range(self.max_visible_items):
            entry_index = self.scroll_offset + row
            if entry_index >= len(self.entries):
                break
            subtitles.append(self.entries[entry_index].subtitle)
        return subtitles

    def get_visible_icon_keys(self) -> list[str]:
        """Return visible icon keys for the shared LVGL scene."""

        if not self.entries:
            return []

        icons: list[str] = []
        for row in range(self.max_visible_items):
            entry_index = self.scroll_offset + row
            if entry_index >= len(self.entries):
                break
            entry = self.entries[entry_index]
            icons.append("call" if entry.direction == "outgoing" else "talk")
        return icons

    def on_select(self, data=None) -> None:
        """Redial the selected recent call when VoIP is ready."""
        selected = self._selected_entry()
        if (
            selected is None
            or not selected.sip_address
            or not self._is_ready_to_call()
            or self.voip_manager is None
        ):
            return

        logger.info(f"Redialing recent contact: {selected.title} ({selected.sip_address})")
        if self.voip_manager.make_call(selected.sip_address, contact_name=selected.display_name):
            self.request_route("call_started")

    def on_back(self, data=None) -> None:
        """Return to the previous screen."""
        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Move through recents with wraparound."""
        if not self.entries:
            return
        self.selected_index = (self.selected_index + 1) % len(self.entries)

    def on_down(self, data=None) -> None:
        """Move to the next recent entry."""
        if not self.entries:
            return
        self.selected_index = (self.selected_index + 1) % len(self.entries)

    def on_up(self, data=None) -> None:
        """Move to the previous recent entry."""
        if not self.entries:
            return
        self.selected_index = (self.selected_index - 1) % len(self.entries)
