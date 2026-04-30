"""Recent-call history screen for the Talk flow."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

from yoyopod.integrations.call import DialCommand, MarkHistorySeenCommand
from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.voip.call_actions import CallActions
from yoyopod.ui.screens.voip.lvgl.call_history_view import LvglCallHistoryView

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.integrations.call import CallHistoryEntry, CallHistoryStore
    from yoyopod.ui.screens.view import ScreenView


class CallHistoryScreen(Screen):
    """Show recent and missed calls, with quick redial when possible."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        voip_manager=None,
        call_history_store: Optional["CallHistoryStore"] = None,
        actions: CallActions | None = None,
        *,
        app: Any | None = None,
    ) -> None:
        super().__init__(display, context, "CallHistory", app=app)
        self._explicit_voip_manager = voip_manager
        self._explicit_call_history_store = call_history_store
        self._actions = actions
        self.entries: list["CallHistoryEntry"] = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.max_visible_items = 4 if display.is_portrait() else 5
        self._lvgl_view: "ScreenView | None" = None

    @property
    def voip_manager(self) -> object | None:
        """Resolve the current VoIP manager from the constructor or owning app."""

        if self._explicit_voip_manager is not None:
            return self._explicit_voip_manager
        return getattr(self.app, "voip_manager", None)

    @property
    def call_history_store(self) -> "CallHistoryStore | None":
        """Resolve the call-history store from the constructor or owning app."""

        if self._explicit_call_history_store is not None:
            return self._explicit_call_history_store
        return getattr(self.app, "call_history_store", None)

    def enter(self) -> None:
        """Refresh call history and clear the unseen-missed badge count."""
        super().enter()
        self._load_entries()
        services = getattr(self.app, "services", None)
        if services is not None and hasattr(services, "call"):
            services.call("call", "mark_history_seen", MarkHistorySeenCommand())
        elif self.voip_manager is not None:
            mark_seen = getattr(self.voip_manager, "mark_call_history_seen", None)
            if callable(mark_seen):
                mark_seen("")
        elif self.call_history_store is not None:
            self.call_history_store.mark_all_seen()
        self._sync_context_summary()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Leave the retained LVGL call-history view alive across transitions."""
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        if getattr(self.display, "backend_kind", "unavailable") != "lvgl":
            self._lvgl_view = None
            return None

        ui_backend = (
            self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        )
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            self._lvgl_view = None
            return None

        self._lvgl_view = current_retained_view(self._lvgl_view, ui_backend)
        if self._lvgl_view is not None:
            return self._lvgl_view

        self._lvgl_view = LvglCallHistoryView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def _load_entries(self) -> None:
        """Load the recent calls from persistent storage."""
        list_recent = getattr(self.voip_manager, "call_history_recent_entries", None)
        if callable(list_recent):
            self.entries = list(list_recent())
        elif self.call_history_store is not None:
            self.entries = self.call_history_store.list_recent()
        else:
            self.entries = []
        if self.entries:
            self.selected_index = min(self.selected_index, len(self.entries) - 1)
        else:
            self.selected_index = 0
            self.scroll_offset = 0

    def _sync_context_summary(self) -> None:
        """Refresh the shared Talk summary after opening recents."""
        if self.context is None:
            return

        unread_count = getattr(self.voip_manager, "call_history_unread_count", None)
        recent_preview = getattr(self.voip_manager, "call_history_recent_preview", None)
        if callable(unread_count) and callable(recent_preview):
            self.context.update_call_summary(
                missed_calls=max(0, int(unread_count() or 0)),
                recent_calls=list(recent_preview()),
            )
            return

        if self.call_history_store is not None:
            self.context.update_call_summary(
                missed_calls=self.call_history_store.missed_count(),
                recent_calls=self.call_history_store.recent_preview(),
            )

    def _is_ready_to_call(self) -> bool:
        """Return whether VoIP is ready to redial from recents."""

        states = getattr(self.app, "states", None)
        if states is not None and hasattr(states, "get_value"):
            return states.get_value("call.registration") == "ok"
        if self.voip_manager is None:
            return False
        status = self.voip_manager.get_status()
        return bool(status.get("running")) and bool(status.get("registered"))

    def _selected_entry(self) -> "CallHistoryEntry | None":
        if not self.entries:
            return None
        return self.entries[self.selected_index]

    def instruction_text(self) -> str:
        """Return compact footer hints for recents."""
        if not self.entries:
            return "Hold back" if self.is_one_button_mode() else "B back"
        if self._is_ready_to_call():
            return (
                "Tap next / Double call"
                if self.is_one_button_mode()
                else "A call | B back | X/Y move"
            )
        return "Tap next / Hold back" if self.is_one_button_mode() else "B back | X/Y move"

    def render(self) -> None:
        """Render the recent-calls list."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is None:
            raise RuntimeError("CallHistoryScreen requires an initialized LVGL backend")
        lvgl_view.sync()

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
        if selected is None or not selected.sip_address or not self._is_ready_to_call():
            return

        logger.info(f"Redialing recent contact: {selected.title} ({selected.sip_address})")
        if self._actions is not None and self._actions.make_call is not None:
            if self._actions.make_call(selected.sip_address, selected.display_name):
                return
            logger.error(f"Failed to redial recent contact: {selected.title}")
            return
        services = getattr(self.app, "services", None)
        if services is not None and hasattr(services, "call"):
            if services.call(
                "call",
                "dial",
                DialCommand(
                    sip_address=selected.sip_address,
                    contact_name=selected.display_name,
                ),
            ):
                return
            logger.error(f"Failed to redial recent contact: {selected.title}")
            return

        if self.voip_manager is None:
            return

        if not self.voip_manager.make_call(
            selected.sip_address, contact_name=selected.display_name
        ):
            logger.error(f"Failed to redial recent contact: {selected.title}")

    def on_back(self, data=None) -> None:
        """Return to the previous screen."""
        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Move through recents with wraparound."""
        if not self.entries:
            return
        self.selected_index = (self.selected_index + 1) % len(self.entries)
