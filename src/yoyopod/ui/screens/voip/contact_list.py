"""Talk contact picker screen."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Optional

from loguru import logger

from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.theme import (
    draw_empty_state,
    draw_list_item,
    render_footer,
    render_header,
    talk_monogram,
    text_fit,
)
from yoyopod.ui.screens.voip.lvgl import LvglContactListView

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext
    from yoyopod.ui.screens import ScreenView


class ContactListScreen(Screen):
    """Full contact list for calling or picking a voice-note recipient."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        voip_manager=None,
        people_directory=None,
        action_mode: Literal["call", "voice_note"] = "call",
    ) -> None:
        super().__init__(display, context, "ContactList")
        self.voip_manager = voip_manager
        self.people_directory = people_directory
        self.action_mode = action_mode
        self.contacts = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.max_visible_items = 4 if display.is_portrait() else 5
        self._lvgl_view: "ScreenView | None" = None

    @property
    def title_text(self) -> str:
        """Return the screen title for the current Talk subflow."""

        return "Voice Note" if self.action_mode == "voice_note" else "More People"

    @property
    def empty_title(self) -> str:
        """Return the empty-state title."""

        return "No contacts"

    @property
    def empty_subtitle(self) -> str:
        """Return the empty-state subtitle."""

        if self.action_mode == "voice_note":
            return "Add a contact before sending a note."
        return "Add contacts to call them here."

    def enter(self) -> None:
        """Load contacts when the screen becomes active."""
        super().enter()
        self.load_contacts()
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Leave the retained LVGL contacts view alive across transitions."""
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        """Create an LVGL view when the Whisplay renderer is active."""
        if getattr(self.display, "backend_kind", "pil") != "lvgl":
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

        self._lvgl_view = LvglContactListView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def load_contacts(self) -> None:
        """Load contacts from the people directory."""
        if self.people_directory:
            contacts = self.people_directory.get_callable_contacts(gsm_enabled=False)
            favorites = [contact for contact in contacts if contact.favorite]
            others = [contact for contact in contacts if not contact.favorite]
            self.contacts = favorites + others
            logger.info(f"Loaded {len(self.contacts)} contacts")
        else:
            logger.warning("No people directory available to load contacts")
            self.contacts = []

    def render(self) -> None:
        """Render the contact list."""
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        content_top = render_header(
            self.display,
            self.context,
            mode="talk",
            title=self.title_text,
            page_text=None,
            show_time=False,
            show_mode_chip=False,
        )

        if not self.contacts:
            draw_empty_state(
                self.display,
                mode="talk",
                title=self.empty_title,
                subtitle=self.empty_subtitle,
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
            contact_index = self.scroll_offset + row
            if contact_index >= len(self.contacts):
                break

            contact = self.contacts[contact_index]
            y1 = list_top + (row * item_height)
            y2 = y1 + 44
            draw_list_item(
                self.display,
                x1=18,
                y1=y1,
                x2=self.display.WIDTH - 18,
                y2=y2,
                title=text_fit(self.display, contact.display_name, self.display.WIDTH - 90, 15),
                subtitle="",
                mode="talk",
                selected=contact_index == self.selected_index,
                badge=None,
                icon=f"mono:{talk_monogram(contact.display_name)}",
            )

        render_footer(self.display, self._instruction_text(), mode="talk")
        self.display.update()

    def get_page_text(self) -> str | None:
        """Contact lists now intentionally omit page counters."""
        return None

    def get_visible_window(self) -> tuple[list[str], list[str], int]:
        """Return the visible contact titles, badges, and selected row index."""
        if not self.contacts:
            return [], [], 0

        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + self.max_visible_items:
            self.scroll_offset = self.selected_index - self.max_visible_items + 1

        visible_titles: list[str] = []
        visible_badges: list[str] = []
        selected_visible_index = 0
        for row in range(self.max_visible_items):
            contact_index = self.scroll_offset + row
            if contact_index >= len(self.contacts):
                break

            contact = self.contacts[contact_index]
            visible_titles.append(contact.display_name)
            visible_badges.append("")
            if contact_index == self.selected_index:
                selected_visible_index = row

        return visible_titles, visible_badges, selected_visible_index

    def get_visible_subtitles(self) -> list[str]:
        """Return visible subtitles for the shared LVGL scene."""

        visible_titles, _, _ = self.get_visible_window()
        return ["" for _ in visible_titles]

    def get_visible_icon_keys(self) -> list[str]:
        """Return visible icon keys for the shared LVGL scene."""

        icons: list[str] = []
        for row in range(self.max_visible_items):
            contact_index = self.scroll_offset + row
            if contact_index >= len(self.contacts):
                break
            icons.append(f"mono:{talk_monogram(self.contacts[contact_index].display_name)}")
        return icons

    def _instruction_text(self) -> str:
        """Return footer hints for the current action mode."""

        if self.is_one_button_mode():
            return "Tap Next | 2x Open | Hold Back"
        if self.action_mode == "voice_note":
            return "A open | B back | X/Y move"
        return "A open | B back | X/Y move"

    def select_next(self) -> None:
        """Move selection to next contact."""
        if self.contacts and self.selected_index < len(self.contacts) - 1:
            self.selected_index += 1

    def select_next_wrapped(self) -> None:
        """Move selection to next contact with wraparound."""
        if not self.contacts:
            return
        self.selected_index = (self.selected_index + 1) % len(self.contacts)

    def select_previous(self) -> None:
        """Move selection to previous contact."""
        if self.contacts and self.selected_index > 0:
            self.selected_index -= 1

    def open_selected_contact(self) -> None:
        """Store the chosen contact and open the shared Talk action screen."""

        if not self.contacts or self.selected_index >= len(self.contacts):
            logger.warning("No contact selected")
            return

        contact = self.contacts[self.selected_index]
        if self.context is not None:
            self.context.set_talk_contact(
                name=contact.display_name,
                sip_address=contact.sip_address,
            )
        self.request_route("open_contact")

    def call_selected_contact(self) -> None:
        """Initiate a call to the selected contact."""
        if not self.contacts or self.selected_index >= len(self.contacts):
            logger.warning("No contact selected")
            return

        if not self.voip_manager:
            logger.error("Cannot make call: no VoIP manager")
            return

        contact = self.contacts[self.selected_index]
        logger.info(f"Calling contact: {contact.display_name} at {contact.sip_address}")
        if not self.voip_manager.make_call(contact.sip_address, contact_name=contact.display_name):
            logger.error(f"Failed to initiate call to {contact.display_name}")

    def choose_voice_note_recipient(self) -> None:
        """Store the chosen recipient and move into the voice-note shell."""
        if not self.contacts or self.selected_index >= len(self.contacts):
            logger.warning("No contact selected for voice note")
            return

        contact = self.contacts[self.selected_index]
        if self.context is not None:
            self.context.set_voice_note_recipient(
                name=contact.display_name,
                sip_address=contact.sip_address,
            )
        self.request_route("voice_note_selected")

    def on_select(self, data=None) -> None:
        """Open the selected contact flow depending on the current mode."""
        if self.action_mode == "voice_note":
            self.choose_voice_note_recipient()
            return
        self.open_selected_contact()

    def on_back(self, data=None) -> None:
        """Go back."""
        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Move to the next contact in one-button mode."""
        self.select_next_wrapped()

    def on_up(self, data=None) -> None:
        """Move selection up."""
        self.select_previous()

    def on_down(self, data=None) -> None:
        """Move selection down."""
        self.select_next()
