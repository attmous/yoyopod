"""Contact action screen for the kids-first Talk flow."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import (
    INK,
    TALK,
    draw_talk_action_button,
    draw_talk_page_dots,
    draw_talk_person_header,
    render_footer,
    render_status_bar,
    talk_monogram,
)
from yoyopy.ui.screens.voip.lvgl.talk_contact_view import LvglTalkContactView

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens import ScreenView


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
    ) -> None:
        super().__init__(display, context, "TalkContact")
        self.voip_manager = voip_manager
        self.selected_index = 0
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Reset the action cursor and create the LVGL view when active."""

        super().enter()
        self.selected_index = 0
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Tear down any active LVGL view when leaving the action screen."""

        if self._lvgl_view is not None:
            self._lvgl_view.destroy()
            self._lvgl_view = None
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        """Create an LVGL view when the Whisplay renderer is active."""

        if self._lvgl_view is not None:
            return self._lvgl_view

        if getattr(self.display, "backend_kind", "pil") != "lvgl":
            return None

        ui_backend = self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            return None

        self._lvgl_view = LvglTalkContactView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def current_contact_name(self) -> str:
        """Return the child-facing selected contact name."""

        if self.context is None:
            return "Friend"
        return self.context.talk_contact_name or "Friend"

    def current_contact_address(self) -> str:
        """Return the selected contact SIP address."""

        if self.context is None:
            return ""
        return self.context.talk_contact_address

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
        if self.voip_manager is not None and hasattr(self.voip_manager, "latest_voice_note_for_contact"):
            latest_note = self.voip_manager.latest_voice_note_for_contact(
                self.current_contact_address(),
            )
        if latest_note is not None and latest_note.local_file_path:
            actions.append(TalkAction("play_note", "Play Note", "Listen to the latest note"))
        return actions

    def get_visible_actions(self) -> tuple[list[str], list[str], int]:
        """Return visible action rows for the LVGL scene."""

        actions = self.actions()
        return [action.title for action in actions], [action.subtitle for action in actions], self.selected_index

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

    def render(self) -> None:
        """Render the contact action picker."""

        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        render_status_bar(self.display, self.context, show_time=True)
        actions = self.actions()
        action_icons = self.get_visible_action_icons()
        button_size = self.action_button_size()
        bottom = draw_talk_person_header(
            self.display,
            center_x=self.display.WIDTH // 2,
            top=self.display.STATUS_BAR_HEIGHT + 28,
            name=self.current_contact_name(),
            label=self.current_contact_monogram(),
        )

        diameter = 64 if button_size == "medium" else 56
        gap = 16 if button_size == "medium" else 12
        center_y = bottom + 54
        row_width = (len(actions) * diameter) + (max(0, len(actions) - 1) * gap)
        start_center = ((self.display.WIDTH - row_width) // 2) + (diameter // 2)

        for row, _action in enumerate(actions):
            draw_talk_action_button(
                self.display,
                center_x=start_center + (row * (diameter + gap)),
                center_y=center_y,
                button_size=button_size,
                color=TALK.accent,
                icon=action_icons[row],
                filled=row == self.selected_index,
                active=row == self.selected_index,
            )

        selected_title = self._selected_action().title
        title_width, title_height = self.display.get_text_size(selected_title, 18)
        title_y = center_y + (diameter // 2) + 16
        self.display.text(
            selected_title,
            (self.display.WIDTH - title_width) // 2,
            title_y,
            color=INK,
            font_size=18,
        )
        draw_talk_page_dots(
            self.display,
            center_x=self.display.WIDTH // 2,
            top=title_y + title_height + 16,
            total=len(actions),
            current=self.selected_index,
            color=TALK.accent,
        )

        render_footer(self.display, "Tap Next | 2x Select | Hold Back", mode="talk")
        self.display.update()

    def _selected_action(self) -> TalkAction:
        """Return the active action row."""

        actions = self.actions()
        return actions[self.selected_index % len(actions)]

    def _start_call(self) -> None:
        """Call the selected contact immediately."""

        contact_name = self.current_contact_name()
        sip_address = self.current_contact_address()
        if not sip_address:
            logger.warning("Cannot place Talk call without a selected address")
            return
        if self.voip_manager is None:
            logger.error("Cannot place Talk call: no VoIP manager")
            return
        if self.voip_manager.make_call(sip_address, contact_name=contact_name):
            self.request_route("call_started")
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

        if self.voip_manager is None:
            return
        address = self.current_contact_address()
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

    def on_down(self, data=None) -> None:
        """Move to the next action."""

        self.selected_index = (self.selected_index + 1) % len(self.actions())

    def on_up(self, data=None) -> None:
        """Move to the previous action."""

        self.selected_index = (self.selected_index - 1) % len(self.actions())
