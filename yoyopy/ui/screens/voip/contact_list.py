"""Contact_list screen for YoyoPod VoIP functionality."""

from yoyopy.ui.screens.base import Screen
from yoyopy.ui.display import Display
from typing import Optional, TYPE_CHECKING
from datetime import datetime
from loguru import logger

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class ContactListScreen(Screen):
    """
    Contact list screen for selecting a contact to call.

    Displays a scrollable list of contacts with favorite indicators.

    Button mapping:
    - Button A: Call selected contact
    - Button B: Go back
    - Button X: Move selection up
    - Button Y: Move selection down
    """

    def __init__(
        self,
        display: Display,
        context: Optional['AppContext'] = None,
        voip_manager=None,
        config_manager=None
    ) -> None:
        """
        Initialize contact list screen.

        Args:
            display: Display controller
            context: Application context
            voip_manager: VoIPManager instance
            config_manager: ConfigManager instance for loading contacts
        """
        super().__init__(display, context, "ContactList")
        self.voip_manager = voip_manager
        self.config_manager = config_manager
        self.contacts = []
        self.selected_index = 0
        self.scroll_offset = 0
        # Adjust visible items based on display orientation
        # Portrait (240×280): 6 items, Landscape (320×240): 5 items
        self.max_visible_items = 6 if display.is_portrait() else 5

    def enter(self) -> None:
        """Called when screen becomes active - load contacts."""
        super().enter()
        self.load_contacts()

    def load_contacts(self) -> None:
        """Load contacts from config manager."""
        if self.config_manager:
            self.contacts = self.config_manager.get_contacts()
            # Sort by favorites first, then by name
            self.contacts.sort(key=lambda c: (not c.favorite, c.name.lower()))
            logger.info(f"Loaded {len(self.contacts)} contacts")
        else:
            logger.warning("No config manager available to load contacts")
            self.contacts = []

    def render(self) -> None:
        """Render the contact list screen."""
        # Clear display
        self.display.clear(self.display.COLOR_BLACK)

        # Draw status bar
        current_time = datetime.now().strftime("%H:%M")
        battery = self.context.battery_percent if self.context else 100
        signal = self.context.signal_strength if self.context else 4

        self.display.status_bar(
            time_str=current_time,
            battery_percent=battery,
            signal_strength=signal
        )

        # Draw title
        title = "Call Contact"
        title_size = 20
        title_width, title_height = self.display.get_text_size(title, title_size)
        title_x = (self.display.WIDTH - title_width) // 2
        title_y = self.display.STATUS_BAR_HEIGHT + 15

        self.display.text(
            title,
            title_x,
            title_y,
            color=self.display.COLOR_WHITE,
            font_size=title_size
        )

        if self.is_one_button_mode() and self.contacts:
            position_text = f"{self.selected_index + 1}/{len(self.contacts)}"
            position_width, _ = self.display.get_text_size(position_text, 11)
            self.display.text(
                position_text,
                self.display.WIDTH - position_width - 18,
                title_y + 4,
                color=self.display.COLOR_GRAY,
                font_size=11
            )

        # Draw separator line
        separator_y = title_y + title_height + 10
        self.display.line(
            20, separator_y,
            self.display.WIDTH - 20, separator_y,
            color=self.display.COLOR_GRAY,
            width=2
        )

        content_y = separator_y + 15

        # Show empty message if no contacts
        if not self.contacts:
            empty_text = "No contacts found"
            empty_size = 14
            empty_width, _ = self.display.get_text_size(empty_text, empty_size)
            empty_x = (self.display.WIDTH - empty_width) // 2
            empty_y = self.display.HEIGHT // 2

            self.display.text(
                empty_text,
                empty_x,
                empty_y,
                color=self.display.COLOR_GRAY,
                font_size=empty_size
            )

            # Update display and return
            self.display.update()
            return

        # Calculate scroll offset to keep selected item visible
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + self.max_visible_items:
            self.scroll_offset = self.selected_index - self.max_visible_items + 1

        # Draw contact items
        item_height = 30
        item_font_size = 14

        for i in range(self.max_visible_items):
            contact_index = self.scroll_offset + i
            if contact_index >= len(self.contacts):
                break

            contact = self.contacts[contact_index]
            y_pos = content_y + (i * item_height)

            # Draw selection indicator
            if contact_index == self.selected_index:
                # Highlight selected item
                self.display.rectangle(
                    10, y_pos - 3,
                    self.display.WIDTH - 10, y_pos + item_height - 8,
                    fill=self.display.COLOR_DARK_GRAY,
                    outline=self.display.COLOR_CYAN,
                    width=2
                )

                # Draw arrow
                self.display.text(
                    ">",
                    15,
                    y_pos,
                    color=self.display.COLOR_CYAN,
                    font_size=item_font_size
                )

            # Draw favorite indicator
            text_x = 35 if contact_index == self.selected_index else 20
            if contact.favorite:
                self.display.text(
                    "★",
                    text_x,
                    y_pos,
                    color=self.display.COLOR_YELLOW,
                    font_size=item_font_size
                )
                text_x += 20

            # Draw contact name (truncate if too long)
            max_name_length = 18
            display_name = contact.name[:max_name_length]
            if len(contact.name) > max_name_length:
                display_name = display_name[:-3] + "..."

            text_color = self.display.COLOR_WHITE if contact_index == self.selected_index else self.display.COLOR_GRAY

            self.display.text(
                display_name,
                text_x,
                y_pos,
                color=text_color,
                font_size=item_font_size
            )

        # Draw scroll indicator if needed
        if len(self.contacts) > self.max_visible_items:
            indicator_x = self.display.WIDTH - 8
            indicator_height = self.max_visible_items * item_height
            indicator_y_start = content_y

            # Calculate scrollbar size and position
            scrollbar_height = max(10, int(indicator_height * self.max_visible_items / len(self.contacts)))
            scrollbar_y_offset = int((indicator_height - scrollbar_height) * self.scroll_offset / (len(self.contacts) - self.max_visible_items))

            # Draw scrollbar background
            self.display.rectangle(
                indicator_x, indicator_y_start,
                indicator_x + 3, indicator_y_start + indicator_height,
                fill=self.display.COLOR_DARK_GRAY
            )

            # Draw scrollbar
            self.display.rectangle(
                indicator_x, indicator_y_start + scrollbar_y_offset,
                indicator_x + 3, indicator_y_start + scrollbar_y_offset + scrollbar_height,
                fill=self.display.COLOR_CYAN
            )

        # Draw instructions at bottom
        instructions_y = self.display.HEIGHT - 15
        instructions_size = 10
        if self.is_one_button_mode():
            instructions = "Tap next | Double call | Hold back"
        else:
            instructions = "A: Call | B: Back | X/Y: Navigate"
        instr_width, _ = self.display.get_text_size(instructions, instructions_size)
        instr_x = (self.display.WIDTH - instr_width) // 2

        self.display.text(
            instructions,
            instr_x,
            instructions_y,
            color=self.display.COLOR_GRAY,
            font_size=instructions_size
        )

        # Update display
        self.display.update()

    def select_next(self) -> None:
        """Move selection to next contact."""
        if self.contacts and self.selected_index < len(self.contacts) - 1:
            self.selected_index += 1
            logger.debug(f"Selected: {self.contacts[self.selected_index].name}")

    def select_next_wrapped(self) -> None:
        """Move selection to next contact with wraparound."""
        if not self.contacts:
            return
        self.selected_index = (self.selected_index + 1) % len(self.contacts)
        logger.debug(f"Selected: {self.contacts[self.selected_index].name}")

    def select_previous(self) -> None:
        """Move selection to previous contact."""
        if self.contacts and self.selected_index > 0:
            self.selected_index -= 1
            logger.debug(f"Selected: {self.contacts[self.selected_index].name}")

    def call_selected_contact(self) -> None:
        """Initiate call to selected contact."""
        if not self.contacts or self.selected_index >= len(self.contacts):
            logger.warning("No contact selected")
            return

        if not self.voip_manager:
            logger.error("Cannot make call: No VoIP manager")
            return

        contact = self.contacts[self.selected_index]
        logger.info(f"Calling contact: {contact.name} at {contact.sip_address}")

        # Make the call with contact name
        if self.voip_manager.make_call(contact.sip_address, contact_name=contact.name):
            logger.info(f"Call initiated to {contact.name}")
            self.request_route("call_started")
        else:
            logger.error(f"Failed to initiate call to {contact.name}")

    def on_select(self, data=None) -> None:
        """Call the selected contact."""
        self.call_selected_contact()

    def on_back(self, data=None) -> None:
        """Go back to the previous screen."""
        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Move to the next contact for one-button navigation."""
        self.select_next_wrapped()

    def on_up(self, data=None) -> None:
        """Move selection up."""
        self.select_previous()

    def on_down(self, data=None) -> None:
        """Move selection down."""
        self.select_next()
