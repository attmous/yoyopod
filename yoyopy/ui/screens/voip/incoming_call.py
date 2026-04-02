"""Incoming_call screen for YoyoPod VoIP functionality."""

from yoyopy.ui.screens.base import Screen
from yoyopy.ui.display import Display
from typing import Optional, TYPE_CHECKING
from datetime import datetime
from loguru import logger

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext


class IncomingCallScreen(Screen):
    """
    Incoming call screen showing caller information.

    Displays incoming call with caller name/address and answer/reject options.

    Button mapping:
    - Button A: Answer call
    - Button B: Reject call
    """

    def __init__(
        self,
        display: Display,
        context: Optional['AppContext'] = None,
        voip_manager=None,
        caller_address: str = "",
        caller_name: str = "Unknown"
    ) -> None:
        """
        Initialize incoming call screen.

        Args:
            display: Display controller
            context: Application context
            voip_manager: VoIPManager instance
            caller_address: SIP address of caller
            caller_name: Display name of caller
        """
        super().__init__(display, context, "IncomingCall")
        self.voip_manager = voip_manager
        self.caller_address = caller_address
        self.caller_name = caller_name
        self.ring_animation_frame = 0

    def render(self) -> None:
        """Render the incoming call screen."""
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

        # Draw "Incoming Call" title
        title = "Incoming Call"
        title_size = 20
        title_width, title_height = self.display.get_text_size(title, title_size)
        title_x = (self.display.WIDTH - title_width) // 2
        title_y = self.display.STATUS_BAR_HEIGHT + 15

        self.display.text(
            title,
            title_x,
            title_y,
            color=self.display.COLOR_CYAN,
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

        # Draw caller icon (phone with ringing animation)
        icon_x = self.display.WIDTH // 2
        icon_y = content_y + 20
        icon_radius = 25

        # Animate ring (pulsing circle)
        ring_color = self.display.COLOR_GREEN if self.ring_animation_frame % 2 == 0 else self.display.COLOR_CYAN
        self.display.circle(
            icon_x,
            icon_y,
            icon_radius,
            outline=ring_color,
            width=3
        )

        # Inner phone icon
        self.display.text(
            "☎",
            icon_x - 10,
            icon_y - 10,
            color=self.display.COLOR_WHITE,
            font_size=20
        )

        # Update animation frame for next render
        self.ring_animation_frame += 1

        # Draw caller name
        name_y = icon_y + icon_radius + 30
        name_size = 18

        # Truncate if too long
        max_name_length = 20
        display_name = self.caller_name[:max_name_length]
        if len(self.caller_name) > max_name_length:
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

        # Draw caller address (smaller, below name)
        if self.caller_address:
            address_y = name_y + 25
            address_size = 12

            # Truncate long address
            max_addr_length = 30
            display_addr = self.caller_address[:max_addr_length]
            if len(self.caller_address) > max_addr_length:
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

        # Draw button instructions at bottom
        instructions_y = self.display.HEIGHT - 15
        instructions_size = 12

        if self.is_one_button_mode():
            instructions = "Double answer | Hold reject"
            instr_width, _ = self.display.get_text_size(instructions, instructions_size)
            self.display.text(
                instructions,
                (self.display.WIDTH - instr_width) // 2,
                instructions_y,
                color=self.display.COLOR_GRAY,
                font_size=instructions_size
            )
        else:
            # Answer button (A)
            answer_text = "A: Answer"
            answer_x = 20

            self.display.text(
                answer_text,
                answer_x,
                instructions_y,
                color=self.display.COLOR_GREEN,
                font_size=instructions_size
            )

            # Reject button (B)
            reject_text = "B: Reject"
            reject_width, _ = self.display.get_text_size(reject_text, instructions_size)
            reject_x = self.display.WIDTH - reject_width - 20

            self.display.text(
                reject_text,
                reject_x,
                instructions_y,
                color=self.display.COLOR_RED,
                font_size=instructions_size
            )

        # Update display
        self.display.update()

    def _answer_call(self) -> None:
        """Answer the incoming call."""
        logger.info("Answering incoming call")
        if self.voip_manager:
            if self.voip_manager.answer_call():
                logger.info("Call answered, transitioning to InCall screen")
                self.request_route("call_answered")
            else:
                logger.error("Failed to answer call")

    def _reject_call(self) -> None:
        """Reject the incoming call."""
        logger.info("Rejecting incoming call")
        if self.voip_manager:
            if self.voip_manager.reject_call():
                logger.info("Call rejected, going back")
                self.request_route("call_rejected")
            else:
                logger.error("Failed to reject call")

    def on_select(self, data=None) -> None:
        """Answer the incoming call."""
        self._answer_call()

    def on_advance(self, data=None) -> None:
        """Incoming-call single tap is intentionally a no-op."""
        return

    def on_call_answer(self, data=None) -> None:
        """Answer the incoming call from a dedicated VoIP action."""
        self._answer_call()

    def on_back(self, data=None) -> None:
        """Reject the incoming call."""
        self._reject_call()

    def on_call_reject(self, data=None) -> None:
        """Reject the incoming call from a dedicated VoIP action."""
        self._reject_call()
