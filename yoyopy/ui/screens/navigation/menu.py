"""MenuScreen - Main navigation menu for YoyoPod."""

from yoyopy.ui.screens.base import Screen
from yoyopy.ui.display import Display
from typing import Optional, List, TYPE_CHECKING
from datetime import datetime
from loguru import logger

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class MenuScreen(Screen):
    """
    Menu screen for navigation.

    Displays a list of menu options with selection indicator.

    Button mapping:
    - Button A: Select current item
    - Button B: Go back to home screen
    - Button X: Move selection up
    - Button Y: Move selection down
    """

    def __init__(
        self,
        display: Display,
        context: Optional['AppContext'] = None,
        items: Optional[List[str]] = None,
        selected_index: int = 0
    ) -> None:
        """
        Initialize menu screen.

        Args:
            display: Display controller
            context: Application context
            items: List of menu items
            selected_index: Currently selected item index
        """
        super().__init__(display, context, "Menu")

        if items is None:
            items = ["Music", "Podcasts", "Audiobooks", "Settings"]

        self.items = items
        self.selected_index = selected_index

    def render(self) -> None:
        """Render the menu screen."""
        # Clear display
        self.display.clear(self.display.COLOR_BLACK)

        # Draw status bar
        current_time = datetime.now().strftime("%H:%M")
        self.display.status_bar(
            time_str=current_time,
            battery_percent=85,
            signal_strength=3
        )

        # Draw menu title
        title = "Main Menu"
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

        # Draw separator line
        separator_y = title_y + title_height + 10
        self.display.line(
            20, separator_y,
            self.display.WIDTH - 20, separator_y,
            color=self.display.COLOR_GRAY,
            width=2
        )

        # Draw menu items
        item_y_start = separator_y + 20
        item_height = 35
        item_font_size = 16

        for i, item in enumerate(self.items):
            y_pos = item_y_start + (i * item_height)

            # Draw selection indicator
            if i == self.selected_index:
                # Highlight selected item
                self.display.rectangle(
                    10, y_pos - 5,
                    self.display.WIDTH - 10, y_pos + item_height - 10,
                    fill=self.display.COLOR_DARK_GRAY,
                    outline=self.display.COLOR_CYAN,
                    width=2
                )

                # Draw arrow
                self.display.text(
                    ">",
                    20,
                    y_pos,
                    color=self.display.COLOR_CYAN,
                    font_size=item_font_size
                )

            # Draw item text
            text_x = 45 if i == self.selected_index else 30
            text_color = self.display.COLOR_WHITE if i == self.selected_index else self.display.COLOR_GRAY

            self.display.text(
                item,
                text_x,
                y_pos,
                color=text_color,
                font_size=item_font_size
            )

        # Update display
        self.display.update()

    def select_next(self) -> None:
        """Move selection to next item."""
        self.selected_index = (self.selected_index + 1) % len(self.items)
        logger.debug(f"Selected: {self.items[self.selected_index]}")

    def select_previous(self) -> None:
        """Move selection to previous item."""
        self.selected_index = (self.selected_index - 1) % len(self.items)
        logger.debug(f"Selected: {self.items[self.selected_index]}")

    def get_selected(self) -> str:
        """Get currently selected item."""
        return self.items[self.selected_index]

    def on_select(self, data=None) -> None:
        """Select the current item."""
        selected_item = self.get_selected()
        logger.info(f"Menu item selected: {selected_item}")
        if selected_item == "Settings":
            logger.info("Settings not implemented yet")
            return
        self.request_route("select", payload=selected_item)

    def on_back(self, data=None) -> None:
        """Go back to the previous screen."""
        self.request_route("back")

    def on_up(self, data=None) -> None:
        """Move selection up."""
        self.select_previous()

    def on_down(self, data=None) -> None:
        """Move selection down."""
        self.select_next()
