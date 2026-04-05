"""Talk hub screen for YoyoPod VoIP functionality."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Optional

from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import INK, MUTED, SURFACE, TALK, draw_empty_state, draw_list_item, render_footer, render_header, rounded_panel, text_fit

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.config import ConfigManager, Contact
    from yoyopy.voip import VoIPManager


@dataclass(slots=True)
class QuickCallTarget:
    """Represents one selectable quick action on the Talk screen."""

    kind: Literal["contact", "browse_contacts"]
    title: str
    subtitle: str
    sip_address: str = ""
    favorite: bool = False


class CallScreen(Screen):
    """Talk screen showing call readiness and favorite contacts."""

    _MAX_QUICK_CONTACTS = 6

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        voip_manager: Optional["VoIPManager"] = None,
        config_manager: Optional["ConfigManager"] = None,
    ) -> None:
        super().__init__(display, context, "Call")
        self.voip_manager = voip_manager
        self.config_manager = config_manager
        self.quick_targets: list[QuickCallTarget] = []
        self.selected_index = 0
        self.scroll_offset = 0
        self.max_visible_items = 3 if display.is_portrait() else 4

    def enter(self) -> None:
        """Refresh quick-call shortcuts whenever the screen becomes active."""
        super().enter()
        self._load_quick_targets()

    def _load_quick_targets(self) -> None:
        """Load favorite or regular contacts for quick calling."""
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
                    subtitle="See the full list",
                )
            )

        if not self.quick_targets:
            self.selected_index = 0
            self.scroll_offset = 0
            return

        self.selected_index = min(self.selected_index, len(self.quick_targets) - 1)
        self._ensure_selection_visible()

    def render(self) -> None:
        """Render the Talk hub with status and quick-call cards."""
        status = self._get_status_snapshot()
        status_text, _status_color, _detail_text = self._status_lines(status)
        call_state_text, caller_text = self._call_context_lines(status)
        position_text = None
        if self.quick_targets:
            position_text = f"{self.selected_index + 1}/{len(self.quick_targets)}"

        content_top = render_header(
            self.display,
            self.context,
            mode="talk",
            title="Talk",
            page_text=position_text,
            show_time=False,
            show_mode_chip=False,
        )

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

        header_text = call_state_text or status_text or "Quick calls"
        self.display.text(header_text, 22, panel_top + 10, color=TALK.accent, font_size=13)
        if caller_text:
            caller_text = text_fit(self.display, caller_text, self.display.WIDTH - 120, 10)
            self.display.text(caller_text, 22, panel_top + 28, color=INK, font_size=10)
        else:
            self.display.text("Favorites", 22, panel_top + 28, color=MUTED, font_size=10)

        if not self.quick_targets:
            draw_empty_state(
                self.display,
                mode="talk",
                title="No contacts",
                subtitle="Add favorite people to make Talk feel instant.",
                icon="talk",
                top=content_top + 12,
            )
            render_footer(self.display, "Hold back", mode="talk")
            self.display.update()
            return

        visible_items = max(1, min(self.max_visible_items, len(self.quick_targets)))
        self._ensure_selection_visible(visible_items)

        item_height = 50
        list_top = panel_top + 48
        for row in range(visible_items):
            target_index = self.scroll_offset + row
            if target_index >= len(self.quick_targets):
                break

            target = self.quick_targets[target_index]
            y1 = list_top + (row * item_height)
            y2 = y1 + 42
            badge = "ALL" if target.kind == "browse_contacts" else "FAV" if target.favorite else None
            draw_list_item(
                self.display,
                x1=20,
                y1=y1,
                x2=self.display.WIDTH - 20,
                y2=y2,
                title=target.title,
                subtitle="",
                mode="talk",
                selected=target_index == self.selected_index,
                badge=badge,
            )

        render_footer(self.display, self._instruction_text(), mode="talk")
        self.display.update()

    def _get_status_snapshot(self) -> dict:
        """Return a stable VoIP status dict for rendering and actions."""
        if self.voip_manager is None:
            return {}
        return self.voip_manager.get_status()

    def _status_lines(self, status: dict) -> tuple[str, tuple[int, int, int], str]:
        """Return the primary Talk availability copy."""
        if not self.voip_manager:
            return ("Talk offline", self.display.COLOR_RED, "Manager not initialized")

        running = status.get("running", False)
        registered = status.get("registered", False)
        registration_state = status.get("registration_state", "none")

        if not status.get("sip_identity"):
            return ("Not set up", self.display.COLOR_GRAY, "")
        if not running:
            return ("Recovering", self.display.COLOR_YELLOW, "")
        if registered:
            return ("Calls ready", self.display.COLOR_GREEN, "")
        if registration_state == "progress":
            return ("Connecting", self.display.COLOR_YELLOW, "")
        if registration_state == "failed":
            return ("Offline", self.display.COLOR_RED, "")
        return ("Offline", self.display.COLOR_GRAY, "")

    def _call_context_lines(self, status: dict) -> tuple[str, str]:
        """Return the current call-state summary if the backend is mid-call."""
        if not self.voip_manager:
            return ("", "")

        call_state = status.get("call_state", "idle")
        if call_state in {"idle", "released"}:
            return ("", "")

        state_labels = {
            "incoming": "Incoming call",
            "outgoing": "Calling...",
            "outgoing_progress": "Calling...",
            "outgoing_ringing": "Ringing...",
            "outgoing_early_media": "Connecting audio",
            "connected": "Call connected",
            "streams_running": "Call connected",
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
        """Return footer hints for the current selection and state."""
        if self.is_one_button_mode():
            if not self.quick_targets:
                return "Hold back"

            selected_target = self._selected_target()
            if selected_target is None:
                return "Hold back"

            if selected_target.kind == "browse_contacts" or not self._is_ready_to_call():
                return "Tap next / Open / Hold back"
            return "Tap next / Call / Hold back"

        if not self.quick_targets:
            return "B back"

        selected_target = self._selected_target()
        if selected_target is None:
            return "B back"

        primary_text = "A open" if selected_target.kind == "browse_contacts" or not self._is_ready_to_call() else "A call"
        return f"{primary_text} | B back | X/Y move"

    def _ensure_selection_visible(self, visible_items: Optional[int] = None) -> None:
        """Adjust scroll offset to keep the selected target on screen."""
        if not self.quick_targets:
            self.scroll_offset = 0
            return

        visible = visible_items or self.max_visible_items
        if self.selected_index < self.scroll_offset:
            self.scroll_offset = self.selected_index
        elif self.selected_index >= self.scroll_offset + visible:
            self.scroll_offset = self.selected_index - visible + 1

    def _browse_contacts(self) -> None:
        """Open the full contact list."""
        logger.info("Opening full contact list from Talk")
        self.request_route("browse_contacts")

    def _call_selected_target(self) -> None:
        """Place a call to the currently selected contact."""
        selected_target = self._selected_target()
        if selected_target is None:
            logger.debug("No Talk target selected")
            return

        if selected_target.kind == "browse_contacts" or not self._is_ready_to_call():
            self._browse_contacts()
            return

        if self.voip_manager is None:
            logger.error("Cannot place call: VoIP manager unavailable")
            return

        logger.info(f"Calling quick contact: {selected_target.title} ({selected_target.sip_address})")
        if self.voip_manager.make_call(selected_target.sip_address, contact_name=selected_target.title):
            self.request_route("call_started")
            return

        logger.error(f"Failed to initiate quick call to {selected_target.title}")

    def on_select(self, data=None) -> None:
        """Call the selected person or open contacts."""
        self._call_selected_target()

    def on_back(self, data=None) -> None:
        """Return to the previous screen."""
        self.request_route("back")

    def on_up(self, data=None) -> None:
        """Move selection upward."""
        if self.selected_index > 0:
            self.selected_index -= 1
            self._ensure_selection_visible()

    def on_down(self, data=None) -> None:
        """Move selection downward."""
        if self.selected_index < len(self.quick_targets) - 1:
            self.selected_index += 1
            self._ensure_selection_visible()

    def on_advance(self, data=None) -> None:
        """Move through quick-call targets with wraparound."""
        if not self.quick_targets:
            return
        self.selected_index = (self.selected_index + 1) % len(self.quick_targets)
        self._ensure_selection_visible()
