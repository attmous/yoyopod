"""HomeScreen - Initial landing screen for YoyoPod."""

from yoyopy.ui.screens.base import Screen
from yoyopy.ui.display import Display
from typing import Optional, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class HomeScreen(Screen):
    """
    Home screen displaying YoyoPod logo and status.

    Shows the main branding and current device status including
    battery, time, and signal strength.

    Button mapping:
    - Button A: Open main menu
    """

    def __init__(self, display: Display, context: Optional['AppContext'] = None) -> None:
        super().__init__(display, context, "Home")

    def render(self) -> None:
        """Render the home screen."""
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

        # Draw YoyoPod logo text
        logo_text = "YoyoPod"
        logo_size = 32
        text_width, text_height = self.display.get_text_size(logo_text, logo_size)
        logo_x = (self.display.WIDTH - text_width) // 2
        logo_y = 60

        self.display.text(
            logo_text,
            logo_x,
            logo_y,
            color=self.display.COLOR_CYAN,
            font_size=logo_size
        )

        # Draw subtitle
        subtitle = "Connect"
        subtitle_size = 16
        sub_width, sub_height = self.display.get_text_size(subtitle, subtitle_size)
        sub_x = (self.display.WIDTH - sub_width) // 2
        sub_y = logo_y + text_height + 10

        self.display.text(
            subtitle,
            sub_x,
            sub_y,
            color=self.display.COLOR_WHITE,
            font_size=subtitle_size
        )

        # Draw decorative circle
        circle_y = logo_y + text_height + sub_height + 40
        self.display.circle(
            self.display.WIDTH // 2,
            circle_y,
            30,
            outline=self.display.COLOR_CYAN,
            width=3
        )

        # Draw status text
        status_text = "Ready to Play"
        status_size = 14
        status_width, _ = self.display.get_text_size(status_text, status_size)
        status_x = (self.display.WIDTH - status_width) // 2
        status_y = self.display.HEIGHT - 40

        self.display.text(
            status_text,
            status_x,
            status_y,
            color=self.display.COLOR_GREEN,
            font_size=status_size
        )

        # Update display
        self.display.update()

    def on_select(self, data=None) -> None:
        """Open the main menu."""
        self.request_route("select")

