"""Outgoing_call screen for YoyoPod VoIP functionality."""

from yoyopy.ui.screens.base import Screen
from yoyopy.ui.display import Display
from typing import Optional, TYPE_CHECKING
from datetime import datetime
from loguru import logger

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class OutgoingCallScreen(Screen):
    """
    Outgoing call screen showing callee information.

    Displays outgoing call with callee name/address and cancel option.

    Button mapping:
    - Button B: Cancel call
    """

    def __init__(
        self,
        display: Display,
        context: Optional['AppContext'] = None,
        voip_manager=None,
        callee_address: str = "",
        callee_name: str = "Unknown"
    ) -> None:
        """
        Initialize outgoing call screen.

        Args:
            display: Display controller
            context: Application context
            voip_manager: VoIPManager instance
            callee_address: SIP address of callee
            callee_name: Display name of callee
        """
        super().__init__(display, context, "OutgoingCall")
        self.voip_manager = voip_manager
        self.callee_address = callee_address
        self.callee_name = callee_name
        self.ring_animation_frame = 0

    def render(self) -> None:
        """Render the outgoing call screen."""
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

        # Draw "Calling..." title
        title = "Calling..."
        title_size = 20
        title_width, title_height = self.display.get_text_size(title, title_size)
        title_x = (self.display.WIDTH - title_width) // 2
        title_y = self.display.STATUS_BAR_HEIGHT + 15

        self.display.text(
            title,
            title_x,
            title_y,
            color=self.display.COLOR_YELLOW,
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

        content_y = separator_y + 30

        # Draw calling icon (phone with outgoing animation)
        icon_x = self.display.WIDTH // 2
        icon_y = content_y + 20
        icon_radius = 25

        # Animate outgoing call (pulsing circle)
        ring_color = self.display.COLOR_YELLOW if self.ring_animation_frame % 2 == 0 else self.display.COLOR_CYAN
        self.display.circle(
            icon_x,
            icon_y,
            icon_radius,
            outline=ring_color,
            width=3
        )

        # Inner phone icon with arrow
        self.display.text(
            "☎",
            icon_x - 10,
            icon_y - 10,
            color=self.display.COLOR_WHITE,
            font_size=20
        )

        # Outgoing arrow
        self.display.text(
            "→",
            icon_x + 15,
            icon_y - 5,
            color=self.display.COLOR_YELLOW,
            font_size=16
        )

        # Update animation frame for next render
        self.ring_animation_frame += 1

        # Get caller info dynamically from VoIPManager
        callee_name = self.callee_name
        callee_address = self.callee_address

        if self.voip_manager:
            caller_info = self.voip_manager.get_caller_info()
            # Use caller info from VoIPManager if available
            if caller_info.get("display_name") != "Unknown":
                callee_name = caller_info.get("display_name", "Unknown")
            if caller_info.get("address"):
                callee_address = caller_info.get("address", "")

        # Draw callee name
        name_y = icon_y + icon_radius + 30
        name_size = 18

        # Truncate if too long
        max_name_length = 20
        display_name = callee_name[:max_name_length]
        if len(callee_name) > max_name_length:
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

        # Draw callee address (smaller, below name)
        if callee_address:
            address_y = name_y + 25
            address_size = 12

            # Truncate long address
            max_addr_length = 30
            display_addr = callee_address[:max_addr_length]
            if len(callee_address) > max_addr_length:
                display_addr = display_addr[:-3] + "..."

            addr_width, _ = self.display.get_text_size(display_addr, address_size)
            addr_x = (self.display.WIDTH - addr_width) // 2

            self.display.text(
                display_addr,
                addr_x,
                address_y,
                color=self.display.COLOR_GRAY,
                font_size=address_size
            )

        # Draw status text
        status_y = self.display.HEIGHT - 40
        status_text = "Connecting..."
        status_size = 14
        status_width, _ = self.display.get_text_size(status_text, status_size)
        status_x = (self.display.WIDTH - status_width) // 2

        self.display.text(
            status_text,
            status_x,
            status_y,
            color=self.display.COLOR_GRAY,
            font_size=status_size
        )

        # Draw button instructions at bottom
        instructions_y = self.display.HEIGHT - 15
        instructions_size = 12

        if self.is_one_button_mode():
            cancel_text = "Hold cancel"
        else:
            cancel_text = "B: Cancel"
        cancel_width, _ = self.display.get_text_size(cancel_text, instructions_size)
        cancel_x = (self.display.WIDTH - cancel_width) // 2

        self.display.text(
            cancel_text,
            cancel_x,
            instructions_y,
            color=self.display.COLOR_RED,
            font_size=instructions_size
        )

        # Update display
        self.display.update()

    def _cancel_call(self) -> None:
        """Cancel the outgoing call."""
        logger.info("Canceling outgoing call")
        if self.voip_manager:
            if self.voip_manager.hangup():
                logger.info("Call canceled, going back")
                self.request_route("call_hangup")
            else:
                logger.error("Failed to cancel call")

    def on_back(self, data=None) -> None:
        """Cancel the outgoing call."""
        self._cancel_call()

    def on_advance(self, data=None) -> None:
        """Outgoing-call single tap is intentionally a no-op."""
        return

    def on_select(self, data=None) -> None:
        """Outgoing-call double tap is intentionally a no-op."""
        return

    def on_call_hangup(self, data=None) -> None:
        """Cancel the outgoing call from a dedicated VoIP action."""
        self._cancel_call()
