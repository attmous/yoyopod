"""Talk contact list screen."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import SURFACE, draw_empty_state, draw_list_item, render_footer, render_header, rounded_panel, text_fit

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class ContactListScreen(Screen):
    """Full contact list for the Talk flow."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        voip_manager=None,
        config_manager=None,
    ) -> None:
        super().__init__(display, context, "ContactList")
        self.voip_manager = voip_manager
        self.config_manager = config_manager
        self.contacts = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.max_visible_items = 4 if display.is_portrait() else 5

    def enter(self) -> None:
        """Load contacts when the screen becomes active."""
        super().enter()
        self.load_contacts()

    def load_contacts(self) -> None:
        """Load contacts from config manager."""
        if self.config_manager:
            self.contacts = self.config_manager.get_contacts()
            self.contacts.sort(key=lambda c: (not c.favorite, c.name.lower()))
            logger.info(f"Loaded {len(self.contacts)} contacts")
        else:
            logger.warning("No config manager available to load contacts")
            self.contacts = []

    def render(self) -> None:
        """Render the contact list."""
        page_text = None
        if self.contacts:
            page_text = f"{self.selected_index + 1}/{len(self.contacts)}"

        content_top = render_header(
            self.display,
            self.context,
            mode="talk",
            title="Contacts",
            page_text=page_text,
            show_time=False,
            show_mode_chip=False,
        )

        if not self.contacts:
            draw_empty_state(
                self.display,
                mode="talk",
                title="No contacts",
                subtitle="Add people in contacts config to call them here.",
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

        panel_top = content_top + 6
        panel_bottom = self.display.HEIGHT - 28
        rounded_panel(
            self.display,
            12,
            panel_top,
            self.display.WIDTH - 12,
            panel_bottom,
            fill=SURFACE,
            outline=None,
            radius=24,
        )

        item_height = 46
        for row in range(self.max_visible_items):
            contact_index = self.scroll_offset + row
            if contact_index >= len(self.contacts):
                break

            contact = self.contacts[contact_index]
            y1 = panel_top + 10 + (row * item_height)
            y2 = y1 + 38
            badge = "FAV" if contact.favorite else None
            draw_list_item(
                self.display,
                x1=20,
                y1=y1,
                x2=self.display.WIDTH - 20,
                y2=y2,
                title=text_fit(self.display, contact.name, self.display.WIDTH - 90, 15),
                subtitle="",
                mode="talk",
                selected=contact_index == self.selected_index,
                badge=badge,
            )

        help_text = "Tap next / Call / Hold back" if self.is_one_button_mode() else "A call | B back | X/Y move"
        render_footer(self.display, help_text, mode="talk")
        self.display.update()

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

    def call_selected_contact(self) -> None:
        """Initiate a call to the selected contact."""
        if not self.contacts or self.selected_index >= len(self.contacts):
            logger.warning("No contact selected")
            return

        if not self.voip_manager:
            logger.error("Cannot make call: no VoIP manager")
            return

        contact = self.contacts[self.selected_index]
        logger.info(f"Calling contact: {contact.name} at {contact.sip_address}")
        if self.voip_manager.make_call(contact.sip_address, contact_name=contact.name):
            self.request_route("call_started")
        else:
            logger.error(f"Failed to initiate call to {contact.name}")

    def on_select(self, data=None) -> None:
        """Call the selected contact."""
        self.call_selected_contact()

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
