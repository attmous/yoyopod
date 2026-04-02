"""Call screen for YoyoPod VoIP functionality."""

from yoyopy.ui.screens.base import Screen
from yoyopy.ui.display import Display
from typing import Optional, TYPE_CHECKING
from datetime import datetime

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class CallScreen(Screen):
    """
    VoIP call screen showing registration and call status.

    Displays VoIP registration status and allows making/receiving calls.

    Button mapping:
    - Button A: (Reserved for answer/hangup)
    - Button B: Back to menu
    - Button X: (Reserved for dial pad)
    - Button Y: (Reserved for dial pad)
    """

    def __init__(
        self,
        display: Display,
        context: Optional['AppContext'] = None,
        voip_manager=None,
        config_manager=None
    ) -> None:
        """
        Initialize call screen.

        Args:
            display: Display controller
            context: Application context
            voip_manager: VoIPManager instance
            config_manager: ConfigManager instance for contacts
        """
        super().__init__(display, context, "Call")
        self.voip_manager = voip_manager
        self.config_manager = config_manager

    def render(self) -> None:
        """Render the call screen."""
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
        title = "VoIP Call"
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

        content_y = separator_y + 20

        # Get VoIP status
        if self.voip_manager:
            status = self.voip_manager.get_status()
            registered = status.get("registered", False)
            reg_state = status.get("registration_state", "none")
            call_state = status.get("call_state", "idle")
            sip_identity = status.get("sip_identity", "")

            # Draw registration status
            if registered:
                status_text = "VoIP Ready"
                status_color = self.display.COLOR_GREEN
            elif reg_state == "progress":
                status_text = "Connecting..."
                status_color = self.display.COLOR_YELLOW
            elif reg_state == "failed":
                status_text = "Registration Failed"
                status_color = self.display.COLOR_RED
            else:
                status_text = "VoIP Disconnected"
                status_color = self.display.COLOR_GRAY

            # Draw status with icon
            status_size = 18
            status_width, _ = self.display.get_text_size(status_text, status_size)
            status_x = (self.display.WIDTH - status_width) // 2
            status_y = content_y + 30

            self.display.text(
                status_text,
                status_x,
                status_y,
                color=status_color,
                font_size=status_size
            )

            # Draw SIP identity
            if sip_identity:
                identity_size = 12
                # Truncate long identity
                max_len = 30
                display_identity = sip_identity[:max_len]
                if len(sip_identity) > max_len:
                    display_identity = display_identity[:-3] + "..."

                identity_width, _ = self.display.get_text_size(display_identity, identity_size)
                identity_x = (self.display.WIDTH - identity_width) // 2
                identity_y = status_y + 30

                self.display.text(
                    display_identity,
                    identity_x,
                    identity_y,
                    color=self.display.COLOR_GRAY,
                    font_size=identity_size
                )

            # Draw call state if not idle
            if call_state != "idle":
                call_text = f"Call: {call_state}"
                call_size = 14
                call_width, _ = self.display.get_text_size(call_text, call_size)
                call_x = (self.display.WIDTH - call_width) // 2
                call_y = self.display.HEIGHT // 2 + 20

                self.display.text(
                    call_text,
                    call_x,
                    call_y,
                    color=self.display.COLOR_CYAN,
                    font_size=call_size
                )

        else:
            # No VoIP manager
            error_text = "VoIP Not Available"
            error_size = 16
            error_width, _ = self.display.get_text_size(error_text, error_size)
            error_x = (self.display.WIDTH - error_width) // 2
            error_y = self.display.HEIGHT // 2

            self.display.text(
                error_text,
                error_x,
                error_y,
                color=self.display.COLOR_RED,
                font_size=error_size
            )

        # Draw instructions at bottom
        instructions_y = self.display.HEIGHT - 15
        instructions_size = 10
        instructions = "B: Back"
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

    def on_select(self, data=None) -> None:
        """Reserved for answer/hangup."""
        # TODO: Implement call answer/hangup
        pass

    def on_back(self, data=None) -> None:
        """Go back to the previous screen."""
        self.request_route("back")

    def on_up(self, data=None) -> None:
        """Reserved for dial pad."""
        # TODO: Implement dial pad
        pass

    def on_down(self, data=None) -> None:
        """Reserved for dial pad."""
        # TODO: Implement dial pad
        pass
