"""In_call screen for YoyoPod VoIP functionality."""

from yoyopy.ui.screens.base import Screen
from yoyopy.ui.display import Display
from typing import Optional, TYPE_CHECKING
from datetime import datetime
from loguru import logger

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class InCallScreen(Screen):
    """
    In-call screen showing active call information.

    Displays call duration, mute status, and call controls.

    Button mapping:
    - Button B: End call
    - Button X: Toggle mute
    """

    def __init__(
        self,
        display: Display,
        context: Optional['AppContext'] = None,
        voip_manager=None
    ) -> None:
        """
        Initialize in-call screen.

        Args:
            display: Display controller
            context: Application context
            voip_manager: VoIPManager instance
        """
        super().__init__(display, context, "InCall")
        self.voip_manager = voip_manager

    def format_duration(self, seconds: int) -> str:
        """
        Format call duration as MM:SS.

        Args:
            seconds: Duration in seconds

        Returns:
            Formatted duration string
        """
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes:02d}:{secs:02d}"

    def render(self) -> None:
        """Render the in-call screen."""
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

        # Get call info
        caller_info = {"display_name": "Unknown", "address": ""}
        duration = 0
        is_muted = False

        if self.voip_manager:
            caller_info = self.voip_manager.get_caller_info()
            duration = self.voip_manager.get_call_duration()
            is_muted = self.voip_manager.is_muted

        # Draw "Call Active" title
        title = "Call Active"
        title_size = 20
        title_width, title_height = self.display.get_text_size(title, title_size)
        title_x = (self.display.WIDTH - title_width) // 2
        title_y = self.display.STATUS_BAR_HEIGHT + 15

        self.display.text(
            title,
            title_x,
            title_y,
            color=self.display.COLOR_GREEN,
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

        content_y = separator_y + 20

        # Draw call icon
        icon_x = self.display.WIDTH // 2
        icon_y = content_y + 20
        icon_radius = 25

        # Active call indicator (solid circle)
        self.display.circle(
            icon_x,
            icon_y,
            icon_radius,
            fill=self.display.COLOR_GREEN,
            outline=self.display.COLOR_WHITE,
            width=2
        )

        # Phone icon
        self.display.text(
            "☎",
            icon_x - 10,
            icon_y - 10,
            color=self.display.COLOR_WHITE,
            font_size=20
        )

        # Draw caller/callee name
        name_y = icon_y + icon_radius + 25
        name_size = 18

        caller_name = caller_info.get("display_name", "Unknown")

        # Truncate if too long
        max_name_length = 20
        display_name = caller_name[:max_name_length]
        if len(caller_name) > max_name_length:
            display_name = display_name[:-3] + "..."

        name_width, _ = self.display.get_text_size(display_name, name_size)
        name_x = (self.display.WIDTH - name_width) // 2

        self.display.text(
            display_name,
            name_x,
            name_y,
            color=self.display.COLOR_WHITE,
            font_size=name_size
        )

        # Draw call duration
        duration_y = name_y + 30
        duration_text = self.format_duration(duration)
        duration_size = 24
        duration_width, _ = self.display.get_text_size(duration_text, duration_size)
        duration_x = (self.display.WIDTH - duration_width) // 2

        self.display.text(
            duration_text,
            duration_x,
            duration_y,
            color=self.display.COLOR_CYAN,
            font_size=duration_size
        )

        # Draw mute indicator if muted
        if is_muted:
            mute_y = duration_y + 35
            mute_text = "🔇 MUTED"
            mute_size = 14
            mute_width, _ = self.display.get_text_size(mute_text, mute_size)
            mute_x = (self.display.WIDTH - mute_width) // 2

            self.display.text(
                mute_text,
                mute_x,
                mute_y,
                color=self.display.COLOR_YELLOW,
                font_size=mute_size
            )

        # Draw button instructions at bottom
        instructions_y = self.display.HEIGHT - 15
        instructions_size = 12

        if self.is_one_button_mode():
            instructions = f"Tap {'unmute' if is_muted else 'mute'} | Hold hang up"
            instr_width, _ = self.display.get_text_size(instructions, instructions_size)
            self.display.text(
                instructions,
                (self.display.WIDTH - instr_width) // 2,
                instructions_y,
                color=self.display.COLOR_GRAY,
                font_size=instructions_size
            )
        else:
            # Mute button (X)
            mute_text = f"X: {'Unmute' if is_muted else 'Mute'}"
            mute_x = 20

            self.display.text(
                mute_text,
                mute_x,
                instructions_y,
                color=self.display.COLOR_YELLOW,
                font_size=instructions_size
            )

            # End call button (B)
            end_text = "B: End Call"
            end_width, _ = self.display.get_text_size(end_text, instructions_size)
            end_x = self.display.WIDTH - end_width - 20

            self.display.text(
                end_text,
                end_x,
                instructions_y,
                color=self.display.COLOR_RED,
                font_size=instructions_size
            )

        # Update display
        self.display.update()

    def _hangup_call(self) -> None:
        """End the current call."""
        logger.info("Ending call")
        if self.voip_manager:
            if self.voip_manager.hangup():
                logger.info("Call ended, going back")
                self.request_route("call_hangup")
            else:
                logger.error("Failed to end call")

    def _toggle_mute(self) -> None:
        """Toggle microphone mute."""
        logger.info("Toggling mute")
        if self.voip_manager:
            is_muted = self.voip_manager.toggle_mute()
            logger.info(f"Mute toggled: {'muted' if is_muted else 'unmuted'}")

    def on_back(self, data=None) -> None:
        """End the current call."""
        self._hangup_call()

    def on_call_hangup(self, data=None) -> None:
        """End the current call from a dedicated VoIP action."""
        self._hangup_call()

    def on_up(self, data=None) -> None:
        """Toggle microphone mute."""
        self._toggle_mute()

    def on_advance(self, data=None) -> None:
        """Toggle microphone mute for one-button navigation."""
        self._toggle_mute()
