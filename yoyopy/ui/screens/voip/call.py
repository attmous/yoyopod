"""Call screen for YoyoPod VoIP functionality."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Optional

from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.config import ConfigManager, Contact
    from yoyopy.connectivity import VoIPManager


@dataclass(slots=True)
class QuickCallTarget:
    """Represents one selectable quick action on the VoIP hub screen."""

    kind: Literal["contact", "browse_contacts"]
    title: str
    subtitle: str
    sip_address: str = ""
    favorite: bool = False


class CallScreen(Screen):
    """
    VoIP hub screen showing registration status and quick-call actions.

    Button mapping:
    - Button A: Call selected quick contact or open contacts
    - Button B: Back to menu
    - Button X: Move selection up
    - Button Y: Move selection down
    """

    _MAX_QUICK_CONTACTS = 6

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        voip_manager: Optional["VoIPManager"] = None,
        config_manager: Optional["ConfigManager"] = None,
    ) -> None:
        """Initialize the VoIP hub screen."""
        super().__init__(display, context, "Call")
        self.voip_manager = voip_manager
        self.config_manager = config_manager
        self.quick_targets: list[QuickCallTarget] = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.max_visible_items = 4 if display.is_portrait() else 3

    def enter(self) -> None:
        """Refresh quick-call shortcuts whenever the screen becomes active."""
        super().enter()
        self._load_quick_targets()

    def _load_quick_targets(self) -> None:
        """Load favorite or recent contacts for quick calling."""
        contacts: list["Contact"] = []
        if self.config_manager is not None:
            contacts = sorted(
                self.config_manager.get_contacts(),
                key=lambda contact: (not contact.favorite, contact.name.lower()),
            )

        favorites = [contact for contact in contacts if contact.favorite]
        quick_contacts = favorites or contacts
        visible_contacts = quick_contacts[: self._MAX_QUICK_CONTACTS]

        self.quick_targets = [
            QuickCallTarget(
                kind="contact",
                title=contact.name,
                subtitle=contact.sip_address,
                sip_address=contact.sip_address,
                favorite=contact.favorite,
            )
            for contact in visible_contacts
        ]

        has_more_contacts = bool(contacts) and (
            len(contacts) > len(visible_contacts)
            or (bool(favorites) and len(favorites) < len(contacts))
        )
        if has_more_contacts:
            self.quick_targets.append(
                QuickCallTarget(
                    kind="browse_contacts",
                    title="All Contacts",
                    subtitle="Open the full contact list",
                )
            )

        if not self.quick_targets:
            self.selected_index = 0
            self.scroll_offset = 0
            return

        self.selected_index = min(self.selected_index, len(self.quick_targets) - 1)
        self._ensure_selection_visible()

    def render(self) -> None:
        """Render the VoIP hub with status details and quick-call shortcuts."""
        self.display.clear(self.display.COLOR_BLACK)

        current_time = datetime.now().strftime("%H:%M")
        battery = self.context.battery_percent if self.context else 100
        signal = self.context.signal_strength if self.context else 4

        self.display.status_bar(
            time_str=current_time,
            battery_percent=battery,
            signal_strength=signal,
        )

        title = "VoIP"
        title_size = 20
        title_width, title_height = self.display.get_text_size(title, title_size)
        title_x = (self.display.WIDTH - title_width) // 2
        title_y = self.display.STATUS_BAR_HEIGHT + 10
        self.display.text(
            title,
            title_x,
            title_y,
            color=self.display.COLOR_WHITE,
            font_size=title_size,
        )

        separator_y = title_y + title_height + 8
        self.display.line(
            20,
            separator_y,
            self.display.WIDTH - 20,
            separator_y,
            color=self.display.COLOR_GRAY,
            width=2,
        )

        status = self._get_status_snapshot()
        status_text, status_color, detail_text = self._status_lines(status)
        detail_y = separator_y + 14

        status_size = 18
        status_width, status_height = self.display.get_text_size(status_text, status_size)
        status_x = (self.display.WIDTH - status_width) // 2
        self.display.text(
            status_text,
            status_x,
            detail_y,
            color=status_color,
            font_size=status_size,
        )

        secondary_y = detail_y + status_height + 8
        if detail_text:
            detail_size = 12
            detail_width, detail_height = self.display.get_text_size(detail_text, detail_size)
            detail_x = (self.display.WIDTH - detail_width) // 2
            self.display.text(
                detail_text,
                detail_x,
                secondary_y,
                color=self.display.COLOR_GRAY,
                font_size=detail_size,
            )
            secondary_y += detail_height + 6

        call_state_text, caller_text = self._call_context_lines(status)
        if call_state_text:
            context_size = 13
            context_width, context_height = self.display.get_text_size(call_state_text, context_size)
            context_x = (self.display.WIDTH - context_width) // 2
            self.display.text(
                call_state_text,
                context_x,
                secondary_y,
                color=self.display.COLOR_CYAN,
                font_size=context_size,
            )
            secondary_y += context_height + 4

        if caller_text:
            caller_size = 11
            display_caller = self._truncate(caller_text, 34)
            caller_width, caller_height = self.display.get_text_size(display_caller, caller_size)
            caller_x = (self.display.WIDTH - caller_width) // 2
            self.display.text(
                display_caller,
                caller_x,
                secondary_y,
                color=self.display.COLOR_GRAY,
                font_size=caller_size,
            )
            secondary_y += caller_height + 8

        hub_title = "Quick Calls"
        hub_size = 14
        _, hub_height = self.display.get_text_size(hub_title, hub_size)
        hub_x = 20
        hub_y = secondary_y + 6
        self.display.text(
            hub_title,
            hub_x,
            hub_y,
            color=self.display.COLOR_WHITE,
            font_size=hub_size,
        )

        footer_y = self.display.HEIGHT - 15
        list_top = hub_y + hub_height + 10
        list_bottom = footer_y - 16

        if not self.quick_targets:
            empty_text = "No contacts configured"
            empty_size = 14
            empty_width, _ = self.display.get_text_size(empty_text, empty_size)
            empty_x = (self.display.WIDTH - empty_width) // 2
            empty_y = list_top + ((list_bottom - list_top) // 2)
            self.display.text(
                empty_text,
                empty_x,
                empty_y,
                color=self.display.COLOR_GRAY,
                font_size=empty_size,
            )
        else:
            item_height = 34
            visible_items = max(1, min(self.max_visible_items, (list_bottom - list_top) // item_height))
            self._ensure_selection_visible(visible_items)

            for row in range(visible_items):
                target_index = self.scroll_offset + row
                if target_index >= len(self.quick_targets):
                    break

                target = self.quick_targets[target_index]
                y_pos = list_top + (row * item_height)
                selected = target_index == self.selected_index

                if selected:
                    self.display.rectangle(
                        10,
                        y_pos - 2,
                        self.display.WIDTH - 10,
                        y_pos + item_height - 4,
                        fill=self.display.COLOR_DARK_GRAY,
                        outline=self.display.COLOR_CYAN,
                        width=2,
                    )

                title_text = target.title
                if target.favorite:
                    title_text = f"{target.title} [Fav]"

                title_color = self.display.COLOR_WHITE
                if target.favorite and not selected:
                    title_color = self.display.COLOR_YELLOW
                if target.kind == "browse_contacts":
                    title_color = self.display.COLOR_CYAN if selected else self.display.COLOR_WHITE

                self.display.text(
                    self._truncate(title_text, 24),
                    18,
                    y_pos,
                    color=title_color,
                    font_size=14,
                )
                self.display.text(
                    self._truncate(target.subtitle, 38),
                    18,
                    y_pos + 16,
                    color=self.display.COLOR_GRAY,
                    font_size=10,
                )

        instructions = self._instruction_text()
        instructions_size = 10
        instructions_width, _ = self.display.get_text_size(instructions, instructions_size)
        instructions_x = (self.display.WIDTH - instructions_width) // 2
        self.display.text(
            instructions,
            instructions_x,
            footer_y,
            color=self.display.COLOR_GRAY,
            font_size=instructions_size,
        )

        self.display.update()

    def _get_status_snapshot(self) -> dict:
        """Return a stable VoIP status dict for rendering and actions."""
        if self.voip_manager is None:
            return {}
        return self.voip_manager.get_status()

    def _status_lines(self, status: dict) -> tuple[str, tuple[int, int, int], str]:
        """Return the primary VoIP availability text for the screen header."""
        if not self.voip_manager:
            return ("VoIP Unavailable", self.display.COLOR_RED, "Manager not initialized")

        running = status.get("running", False)
        registered = status.get("registered", False)
        registration_state = status.get("registration_state", "none")
        identity = status.get("sip_identity", "")

        if not running:
            return ("VoIP Recovering...", self.display.COLOR_YELLOW, "Retrying in background")
        if registered:
            return ("VoIP Ready", self.display.COLOR_GREEN, self._truncate(identity, 32))
        if registration_state == "progress":
            return ("Connecting...", self.display.COLOR_YELLOW, self._truncate(identity, 32))
        if registration_state == "failed":
            return ("Registration Failed", self.display.COLOR_RED, "Check SIP settings or network")
        return ("VoIP Disconnected", self.display.COLOR_GRAY, self._truncate(identity, 32))

    def _call_context_lines(self, status: dict) -> tuple[str, str]:
        """Return the current call state summary if the backend is mid-call."""
        if not self.voip_manager:
            return ("", "")

        call_state = status.get("call_state", "idle")
        if call_state == "idle":
            return ("", "")

        state_labels = {
            "incoming": "Incoming call",
            "outgoing": "Dialing",
            "outgoing_progress": "Dialing",
            "outgoing_ringing": "Ringing",
            "outgoing_early_media": "Connecting media",
            "connected": "Call connected",
            "streams_running": "Call connected",
            "released": "Call ended",
        }
        caller_info = self.voip_manager.get_caller_info()
        caller_text = caller_info.get("display_name") or caller_info.get("address") or ""
        return (state_labels.get(call_state, call_state.replace("_", " ").title()), caller_text)

    def _selected_target(self) -> Optional[QuickCallTarget]:
        """Return the currently selected quick target, if any."""
        if not self.quick_targets:
            return None
        return self.quick_targets[self.selected_index]

    def _is_ready_to_call(self) -> bool:
        """Return whether the VoIP backend is ready to place a call."""
        status = self._get_status_snapshot()
        return bool(status.get("running")) and bool(status.get("registered"))

    def _instruction_text(self) -> str:
        """Return the footer instructions for the current selection and state."""
        if not self.quick_targets:
            return "B: Back"

        selected_target = self._selected_target()
        if selected_target is None:
            return "B: Back"

        if selected_target.kind == "browse_contacts" or not self._is_ready_to_call():
            primary_text = "A: Open"
        else:
            primary_text = "A: Call"

        if len(self.quick_targets) > 1:
            return f"{primary_text} | B: Back | X/Y: Move"
        return f"{primary_text} | B: Back"

    def _ensure_selection_visible(self, visible_items: Optional[int] = None) -> None:
        """Adjust scroll offset to keep the selected quick target on screen."""
        if not self.quick_targets:
            self.scroll_offset = 0
            return

        visible = visible_items or self.max_visible_items
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + visible:
            self.scroll_offset = self.selected_index - visible + 1

    @staticmethod
    def _truncate(text: str, max_length: int) -> str:
        """Truncate a string for compact display."""
        if len(text) <= max_length:
            return text
        return text[: max_length - 3] + "..."

    def _browse_contacts(self) -> None:
        """Open the full contact list."""
        logger.info("Opening full contact list from VoIP hub")
        self.request_route("browse_contacts")

    def _call_selected_target(self) -> None:
        """Place a call to the currently selected quick contact."""
        selected_target = self._selected_target()
        if selected_target is None:
            logger.debug("No quick-call target selected")
            return

        if selected_target.kind == "browse_contacts" or not self._is_ready_to_call():
            self._browse_contacts()
            return

        if self.voip_manager is None:
            logger.error("Cannot place call: VoIP manager unavailable")
            return

        logger.info(f"Calling quick contact: {selected_target.title} ({selected_target.sip_address})")
        if self.voip_manager.make_call(
            selected_target.sip_address,
            contact_name=selected_target.title,
        ):
            self.request_route("call_started")
            return

        logger.error(f"Failed to initiate quick call to {selected_target.title}")

    def on_select(self, data=None) -> None:
        """Call the selected quick contact or open contacts when unavailable."""
        self._call_selected_target()

    def on_back(self, data=None) -> None:
        """Return to the previous screen."""
        self.request_route("back")

    def on_up(self, data=None) -> None:
        """Move the quick-call selection upward."""
        if self.selected_index > 0:
            self.selected_index -= 1
            self._ensure_selection_visible()

    def on_down(self, data=None) -> None:
        """Move the quick-call selection downward."""
        if self.selected_index < len(self.quick_targets) - 1:
            self.selected_index += 1
            self._ensure_selection_visible()
