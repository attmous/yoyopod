"""PlaylistScreen - Browse and select playlists."""

from yoyopy.ui.screens.base import Screen
from yoyopy.ui.display import Display
from typing import Optional, TYPE_CHECKING
from datetime import datetime
from loguru import logger

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class PlaylistScreen(Screen):
    """
    Playlist browser screen for Mopidy playlists.

    Displays a scrollable list of playlists with track counts.
    Allows loading and playing selected playlist.

    Button mapping:
    - Button A: Load and play selected playlist
    - Button B: Go back to menu
    - Button X: Move selection up
    - Button Y: Move selection down
    """

    def __init__(
        self,
        display: Display,
        context: Optional['AppContext'] = None,
        mopidy_client=None
    ) -> None:
        """
        Initialize playlist browser screen.

        Args:
            display: Display controller
            context: Application context
            mopidy_client: MopidyClient for fetching playlists
        """
        super().__init__(display, context, "PlaylistBrowser")
        self.mopidy_client = mopidy_client
        self.playlists = []
        self.selected_index = 0
        self.scroll_offset = 0
        # Adjust visible items based on display orientation
        # Portrait (240×280): 6 items, Landscape (320×240): 5 items
        self.max_visible_items = 6 if display.is_portrait() else 5
        self.loading = False
        self.error_message = None

    def enter(self) -> None:
        """Called when screen becomes active - fetch playlists."""
        super().enter()
        self.fetch_playlists()

    def fetch_playlists(self) -> None:
        """Fetch playlists from Mopidy."""
        if not self.mopidy_client:
            self.error_message = "No Mopidy client"
            logger.error("Cannot fetch playlists: No Mopidy client")
            return

        if not self.mopidy_client.is_connected:
            self.error_message = "Mopidy offline"
            logger.error("Cannot fetch playlists: Mopidy is offline")
            return

        self.loading = True
        self.render()  # Show loading indicator

        try:
            logger.info("Fetching playlists from Mopidy...")
            self.playlists = self.mopidy_client.get_playlists(fetch_track_counts=True)
            self.error_message = None
            logger.info(f"Fetched {len(self.playlists)} playlists")
        except Exception as e:
            self.error_message = f"Error: {str(e)[:30]}"
            logger.error(f"Failed to fetch playlists: {e}")
        finally:
            self.loading = False
            self.render()

    def render(self) -> None:
        """Render the playlist browser screen."""
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
        title = "Playlists"
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

        if self.is_one_button_mode() and self.playlists:
            position_text = f"{self.selected_index + 1}/{len(self.playlists)}"
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

        # Show loading indicator
        if self.loading:
            loading_text = "Loading playlists..."
            loading_size = 14
            loading_width, _ = self.display.get_text_size(loading_text, loading_size)
            loading_x = (self.display.WIDTH - loading_width) // 2
            loading_y = self.display.HEIGHT // 2

            self.display.text(
                loading_text,
                loading_x,
                loading_y,
                color=self.display.COLOR_CYAN,
                font_size=loading_size
            )

            # Update display and return
            self.display.update()
            return

        # Show error message
        if self.error_message:
            error_size = 14
            error_width, _ = self.display.get_text_size(self.error_message, error_size)
            error_x = (self.display.WIDTH - error_width) // 2
            error_y = self.display.HEIGHT // 2

            self.display.text(
                self.error_message,
                error_x,
                error_y,
                color=self.display.COLOR_RED,
                font_size=error_size
            )

            # Update display and return
            self.display.update()
            return

        # Show empty message
        if not self.playlists:
            empty_text = "No playlists found"
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

        # Draw playlist items
        item_height = 30
        item_font_size = 14
        count_font_size = 12

        for i in range(self.max_visible_items):
            playlist_index = self.scroll_offset + i
            if playlist_index >= len(self.playlists):
                break

            playlist = self.playlists[playlist_index]
            y_pos = content_y + (i * item_height)

            # Draw selection indicator
            if playlist_index == self.selected_index:
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

            # Draw playlist name (truncate if too long)
            max_name_length = 22
            display_name = playlist.name[:max_name_length]
            if len(playlist.name) > max_name_length:
                display_name = display_name[:-3] + "..."

            text_x = 35 if playlist_index == self.selected_index else 20
            text_color = self.display.COLOR_WHITE if playlist_index == self.selected_index else self.display.COLOR_GRAY

            self.display.text(
                display_name,
                text_x,
                y_pos,
                color=text_color,
                font_size=item_font_size
            )

            # Draw track count if available
            if playlist.track_count > 0:
                count_text = f"{playlist.track_count} tracks"
                count_width, _ = self.display.get_text_size(count_text, count_font_size)
                count_x = self.display.WIDTH - count_width - 15

                self.display.text(
                    count_text,
                    count_x,
                    y_pos + 2,
                    color=self.display.COLOR_GRAY,
                    font_size=count_font_size
                )

        # Draw scroll indicator if needed
        if len(self.playlists) > self.max_visible_items:
            indicator_x = self.display.WIDTH - 8
            indicator_height = self.max_visible_items * item_height
            indicator_y_start = content_y

            # Calculate scrollbar size and position
            scrollbar_height = max(10, int(indicator_height * self.max_visible_items / len(self.playlists)))
            scrollbar_y_offset = int((indicator_height - scrollbar_height) * self.scroll_offset / (len(self.playlists) - self.max_visible_items))

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
            instructions = "Tap next | Double load | Hold back"
        else:
            instructions = "A: Load | B: Back | X/Y: Navigate"
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
        """Move selection to next playlist."""
        if self.playlists and self.selected_index < len(self.playlists) - 1:
            self.selected_index += 1
            logger.debug(f"Selected: {self.playlists[self.selected_index].name}")

    def select_next_wrapped(self) -> None:
        """Move selection to next playlist with wraparound."""
        if not self.playlists:
            return
        self.selected_index = (self.selected_index + 1) % len(self.playlists)
        logger.debug(f"Selected: {self.playlists[self.selected_index].name}")

    def select_previous(self) -> None:
        """Move selection to previous playlist."""
        if self.playlists and self.selected_index > 0:
            self.selected_index -= 1
            logger.debug(f"Selected: {self.playlists[self.selected_index].name}")

    def load_selected_playlist(self) -> None:
        """Load and play the selected playlist."""
        if not self.playlists or self.selected_index >= len(self.playlists):
            logger.warning("No playlist selected")
            return

        if not self.mopidy_client:
            logger.error("Cannot load playlist: No Mopidy client")
            return

        playlist = self.playlists[self.selected_index]
        logger.info(f"Loading playlist: {playlist.name}")

        # Show loading message
        self.display.clear(self.display.COLOR_BLACK)
        loading_text = f"Loading {playlist.name[:15]}..."
        loading_size = 14
        loading_width, _ = self.display.get_text_size(loading_text, loading_size)
        loading_x = (self.display.WIDTH - loading_width) // 2
        loading_y = self.display.HEIGHT // 2

        self.display.text(
            loading_text,
            loading_x,
            loading_y,
            color=self.display.COLOR_CYAN,
            font_size=loading_size
        )
        self.display.update()

        # Load playlist
        try:
            if self.mopidy_client.load_playlist(playlist.uri):
                logger.info(f"Successfully loaded playlist: {playlist.name}")
                self.request_route("playlist_loaded")
            else:
                logger.error(f"Failed to load playlist: {playlist.name}")
                self.error_message = "Failed to load"
                self.render()
        except Exception as e:
            logger.error(f"Error loading playlist: {e}")
            self.error_message = f"Error: {str(e)[:20]}"
            self.render()

    def on_select(self, data=None) -> None:
        """Load and play the selected playlist."""
        self.load_selected_playlist()

    def on_back(self, data=None) -> None:
        """Go back to the previous screen."""
        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Move to the next playlist for one-button navigation."""
        self.select_next_wrapped()

    def on_up(self, data=None) -> None:
        """Move selection up."""
        self.select_previous()

    def on_down(self, data=None) -> None:
        """Move selection down."""
        self.select_next()
