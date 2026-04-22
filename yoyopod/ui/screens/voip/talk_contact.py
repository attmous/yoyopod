"""Contact action screen for the kids-first Talk flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

from yoyopod.integrations.call import DialCommand, PlayLatestVoiceNoteCommand
from yoyopod.integrations.contacts import MarkVoiceNotesSeenCommand
from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.lvgl_lifecycle import current_retained_view
from yoyopod.ui.screens.theme import talk_monogram
from yoyopod.ui.screens.voip.lvgl.talk_contact_view import LvglTalkContactView

if TYPE_CHECKING:
    from yoyopod.core import AppContext
    from yoyopod.ui.screens.view import ScreenView


@dataclass(frozen=True, slots=True)
class TalkAction:
    """One action shown on a selected contact."""

    kind: str
    title: str
    subtitle: str = ""


class TalkContactScreen(Screen):
    """Action picker for the currently selected Talk contact."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        voip_manager=None,
        *,
        app: Any | None = None,
    ) -> None:
        super().__init__(display, context, "TalkContact", app=app)
        self._explicit_voip_manager = voip_manager
        self.selected_index = 0
        self._lvgl_view: "ScreenView | None" = None

    @property
    def voip_manager(self) -> object | None:
        """Resolve the current VoIP manager from the constructor or owning app."""

        if self._explicit_voip_manager is not None:
            return self._explicit_voip_manager
        return getattr(self.app, "voip_manager", None)

    def enter(self) -> None:
        """Reset the action cursor and create the LVGL view when active."""

        super().enter()
        self.selected_index = 0
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Leave the retained LVGL action view alive across transitions."""
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        """Create an LVGL view when the Whisplay renderer is active."""

        if getattr(self.display, "backend_kind", "unavailable") != "lvgl":
            self._lvgl_view = None
            return None

        ui_backend = (
            self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        )
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            self._lvgl_view = None
            return None

        self._lvgl_view = current_retained_view(self._lvgl_view, ui_backend)
        if self._lvgl_view is not None:
            return self._lvgl_view

        self._lvgl_view = LvglTalkContactView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def current_contact_name(self) -> str:
        """Return the child-facing selected contact name."""

        if self.context is None:
            return "Friend"
        return self.context.talk.selected_contact_name or "Friend"

    def current_contact_address(self) -> str:
        """Return the selected contact SIP address."""

        if self.context is None:
            return ""
        return self.context.talk.selected_contact_address

    def current_contact_monogram(self) -> str:
        """Return a compact label for the current contact."""

        return talk_monogram(self.current_contact_name())

    def actions(self) -> list[TalkAction]:
        """Return the available actions for the selected contact."""

        actions = [
            TalkAction("call", "Call", "Start a voice call"),
            TalkAction("voice_note", "Voice Note", "Record a short message"),
        ]
        latest_note = None
        if self.voip_manager is not None and hasattr(
            self.voip_manager, "latest_voice_note_for_contact"
        ):
            latest_note = self.voip_manager.latest_voice_note_for_contact(
                self.current_contact_address(),
            )
        if latest_note is not None and latest_note.local_file_path:
            actions.append(TalkAction("play_note", "Play Note", "Listen to the latest note"))
        return actions

    def get_visible_actions(self) -> tuple[list[str], list[str], int]:
        """Return visible action rows for the LVGL scene."""

        actions = self.actions()
        titles = [action.title for action in actions]
        subtitles = [action.subtitle for action in actions]
        if not titles:
            return titles, subtitles, 0
        selected_index = self._selected_action_index(actions)
        return titles, subtitles, selected_index

    def get_visible_action_icons(self) -> list[str]:
        """Return the visible icon key for each action row."""

        icons: list[str] = []
        for action in self.actions():
            if action.kind == "call":
                icons.append("call")
            elif action.kind == "voice_note":
                icons.append("voice_note")
            elif action.kind == "play_note":
                icons.append("play")
            else:
                icons.append("music_note")
        return icons

    def action_button_size(self) -> str:
        """Return the best-fitting button size for the current action count."""

        return "small" if len(self.actions()) >= 3 else "medium"

    def footer_text(self) -> str:
        """Return the footer hint for the Talk contact action screen."""

        return "Tap Next | 2x Select | Hold Back"

    def render(self) -> None:
        """Render the contact action picker."""

        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is None:
            raise RuntimeError("TalkContactScreen requires an initialized LVGL backend")
        lvgl_view.sync()

    def _selected_action(self) -> TalkAction:
        """Return the active action row."""

        actions = self.actions()
        return actions[self._selected_action_index(actions)]

    def _selected_action_index(self, actions: list[TalkAction]) -> int:
        """Map the raw cursor to a visible Talk action index."""

        return min(self.selected_index, len(actions) - 1)

    def _start_call(self) -> None:
        """Call the selected contact immediately."""

        contact_name = self.current_contact_name()
        sip_address = self.current_contact_address()
        if not sip_address:
            logger.warning("Cannot place Talk call without a selected address")
            return
        services = getattr(self.app, "services", None)
        if services is not None and hasattr(services, "call"):
            if services.call(
                "call",
                "dial",
                DialCommand(sip_address=sip_address, contact_name=contact_name),
            ):
                return
            logger.error("Failed to place Talk call to {}", contact_name)
            return
        if self.voip_manager is None:
            logger.error("Cannot place Talk call: no VoIP manager")
            return
        if self.voip_manager.make_call(sip_address, contact_name=contact_name):
            return
        logger.error("Failed to place Talk call to {}", contact_name)

    def _open_voice_note(self) -> None:
        """Open the voice-note composer for the selected contact."""

        if self.context is not None:
            self.context.set_voice_note_recipient(
                name=self.current_contact_name(),
                sip_address=self.current_contact_address(),
            )
        self.request_route("voice_note")

    def _play_latest_voice_note(self) -> None:
        """Play the latest available voice note for the selected contact."""

        address = self.current_contact_address()
        services = getattr(self.app, "services", None)
        if services is not None and hasattr(services, "call"):
            if services.call(
                "call",
                "play_latest_voice_note",
                PlayLatestVoiceNoteCommand(sip_address=address),
            ):
                services.call(
                    "contacts",
                    "mark_voice_notes_seen",
                    MarkVoiceNotesSeenCommand(address=address),
                )
            return
        if self.voip_manager is None:
            return
        if self.voip_manager.play_latest_voice_note(address):
            self.voip_manager.mark_voice_notes_seen(address)

    def on_select(self, data=None) -> None:
        """Trigger the selected contact action."""

        selected_action = self._selected_action()
        if selected_action.kind == "call":
            self._start_call()
            return
        if selected_action.kind == "voice_note":
            self._open_voice_note()
            return
        self._play_latest_voice_note()

    def on_back(self, data=None) -> None:
        """Return to the contact deck."""

        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Move to the next action."""

        self.selected_index = (self.selected_index + 1) % len(self.actions())
