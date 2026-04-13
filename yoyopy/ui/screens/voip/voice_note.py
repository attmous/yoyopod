"""Voice-note flow screen for the Talk experience."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.theme import (
    ERROR,
    INK,
    MUTED,
    SUCCESS,
    TALK,
    WARNING,
    draw_talk_action_button,
    draw_talk_page_dots,
    draw_talk_person_header,
    draw_talk_status_chip,
    render_footer,
    render_status_bar,
    talk_monogram,
)
from yoyopy.ui.screens.voip.lvgl.voice_note_view import LvglVoiceNoteView

if TYPE_CHECKING:
    from yoyopy.app_context import AppContext
    from yoyopy.ui.screens import ScreenView
    from yoyopy.voip import VoIPManager


@dataclass(frozen=True, slots=True)
class VoiceNoteAction:
    """One selectable action in the voice-note flow."""

    key: str
    title: str
    badge: str = ""


class VoiceNoteScreen(Screen):
    """Kid-facing voice-note flow with real record, review, and send states."""

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        voip_manager: Optional["VoIPManager"] = None,
    ) -> None:
        super().__init__(display, context, "VoiceNote")
        self.voip_manager = voip_manager
        self._state = "ready"
        self._selected_action_index = 0
        self._lvgl_view: "ScreenView | None" = None

    def enter(self) -> None:
        """Reset the voice-note flow when opened."""

        super().enter()
        self._discard_terminal_draft_for_recipient()
        self._sync_state_from_manager(default_state="ready")
        self._selected_action_index = 0
        self._ensure_lvgl_view()

    def exit(self) -> None:
        """Tear down any active LVGL view when leaving voice notes."""

        if self._lvgl_view is not None:
            self._lvgl_view.destroy()
            self._lvgl_view = None
        super().exit()

    def _ensure_lvgl_view(self) -> "ScreenView | None":
        if self._lvgl_view is not None:
            return self._lvgl_view

        if getattr(self.display, "backend_kind", "pil") != "lvgl":
            return None

        ui_backend = self.display.get_ui_backend() if hasattr(self.display, "get_ui_backend") else None
        if ui_backend is None or not getattr(ui_backend, "initialized", False):
            return None

        self._lvgl_view = LvglVoiceNoteView(self, ui_backend)
        self._lvgl_view.build()
        return self._lvgl_view

    def wants_ptt_passthrough(self) -> bool:
        """Return True when the single-button adapter should emit raw PTT hold events."""

        return self.is_one_button_mode() and self._state in {"ready", "recording"}

    def recipient_name(self) -> str:
        """Return the selected recipient."""

        if self.context is None:
            return "Friend"
        return self.context.voice_note_recipient_name or self.context.talk_contact_name or "Friend"

    def recipient_address(self) -> str:
        """Return the selected recipient SIP address."""

        if self.context is None:
            return ""
        return self.context.voice_note_recipient_address or self.context.talk_contact_address

    def recipient_monogram(self) -> str:
        """Return a compact label for the active recipient."""

        return talk_monogram(self.recipient_name())

    def _sync_state_from_manager(self, default_state: str = "ready") -> None:
        """Reflect the active voice-note draft from VoIPManager into the screen/context."""

        if self.voip_manager is None:
            self._state = default_state
            return

        draft = self.voip_manager.get_active_voice_note()
        recipient_address = self.recipient_address()
        if draft is None or (
            recipient_address
            and draft.recipient_address
            and draft.recipient_address != recipient_address
        ):
            self._state = default_state
            if self.context is not None:
                self.context.update_active_voice_note(send_state="idle")
            return

        self._state = draft.send_state or default_state
        if self.context is not None:
            self.context.update_active_voice_note(
                send_state=draft.send_state,
                status_text=draft.status_text,
                file_path=draft.file_path,
                duration_ms=draft.duration_ms,
            )
        if self._state not in {"review", "failed"}:
            self._selected_action_index = 0

    def _discard_terminal_draft_for_recipient(self) -> None:
        """Start fresh when reopening a terminal draft for the same recipient."""

        if self.voip_manager is None:
            return

        draft = self.voip_manager.get_active_voice_note()
        recipient_address = self.recipient_address()
        if draft is None:
            return
        if (
            recipient_address
            and draft.recipient_address
            and draft.recipient_address != recipient_address
        ):
            return
        if draft.send_state in {"sent", "failed"}:
            self.voip_manager.discard_active_voice_note()
            if self.context is not None:
                self.context.update_active_voice_note(send_state="idle")

    def _refresh_input_mode(self) -> None:
        """Rebind active input handlers when the voice-note interaction mode changes."""

        if self.screen_manager is None:
            return
        rebind = getattr(self.screen_manager, "rebind_current_screen_inputs", None)
        if callable(rebind):
            rebind()

    def _duration_label(self) -> str:
        """Return a compact duration label for the active draft."""

        if self.context is None or self.context.voice_note_duration_ms <= 0:
            return ""
        seconds = max(1, round(self.context.voice_note_duration_ms / 1000))
        return f"{seconds}s"

    def actions(self) -> list[VoiceNoteAction]:
        """Return the selectable actions for the current voice-note state."""

        duration_badge = self._duration_label()
        if self._state == "review":
            return [
                VoiceNoteAction("send", "Send", duration_badge),
                VoiceNoteAction("play", "Play"),
                VoiceNoteAction("again", "Again"),
            ]
        if self._state == "failed":
            return [
                VoiceNoteAction("retry", "Retry"),
                VoiceNoteAction("again", "Again"),
            ]
        return []

    def current_actions_for_view(self) -> tuple[list[str], list[str], int]:
        """Return visible action rows for the current state."""

        actions = self.actions()
        return (
            [action.title for action in actions],
            [action.badge for action in actions],
            min(self._selected_action_index, max(0, len(actions) - 1)),
        )

    def current_action_subtitles(self) -> list[str]:
        """Return subtitles for the current action list."""

        subtitles: list[str] = []
        for action in self.actions():
            if action.key == "send":
                subtitles.append("Deliver this voice note")
            elif action.key == "play":
                subtitles.append("Listen before sending")
            elif action.key == "again":
                subtitles.append("Record a new version")
            else:
                subtitles.append("Try that step again")
        return subtitles

    def current_action_icons(self) -> list[str]:
        """Return icon keys for the current action list."""

        icons: list[str] = []
        for action in self.actions():
            if action.key == "send":
                icons.append("check")
            elif action.key == "play":
                icons.append("play")
            elif action.key == "retry":
                icons.append("retry")
            else:
                icons.append("close")
        return icons

    def current_action_colors(self) -> list[tuple[int, int, int]]:
        """Return the Talk action colors for the current button row."""

        colors: list[tuple[int, int, int]] = []
        for action in self.actions():
            if action.key == "send":
                colors.append(SUCCESS)
            elif action.key == "play":
                colors.append(TALK.accent)
            elif action.key == "retry":
                colors.append(WARNING)
            elif action.key == "again":
                colors.append(WARNING)
            else:
                colors.append(ERROR)
        return colors

    def current_action_color_kinds(self) -> list[int]:
        """Return native LVGL color kinds for the current action row."""

        kinds: list[int] = []
        for action in self.actions():
            if action.key == "send":
                kinds.append(1)
            elif action.key == "play":
                kinds.append(0)
            elif action.key in {"retry", "again"}:
                kinds.append(2)
            else:
                kinds.append(3)
        return kinds

    def current_primary_icon(self) -> str:
        """Return the large centered action icon for non-review states."""

        if self._state == "sent":
            return "check"
        if self._state == "failed":
            return "close"
        return "voice_note"

    def current_primary_color(self) -> tuple[int, int, int]:
        """Return the large centered action color for non-review states."""

        if self._state == "sent":
            return SUCCESS
        if self._state == "sending":
            return TALK.accent
        return ERROR

    def current_primary_color_kind(self) -> int:
        """Return the native LVGL color kind for the centered action."""

        if self._state == "sent":
            return 1
        if self._state == "sending":
            return 0
        if self._state == "ready":
            return 3
        return 3

    def current_primary_status(self) -> tuple[str, tuple[int, int, int]]:
        """Return the main status label and color for non-review states."""

        if self._state == "ready":
            return ("Hold to record", MUTED)
        if self._state == "recording":
            return ("Recording", ERROR)
        if self._state == "sending":
            return ("Sending", TALK.accent)
        if self._state == "sent":
            return ("Sent", SUCCESS)
        if self._state == "failed":
            return ("Couldn't send", ERROR)
        return ("Voice Note", MUTED)

    def current_primary_status_kind(self) -> int:
        """Return the native LVGL color kind for the centered status label."""

        if self._state == "sent":
            return 1
        if self._state == "sending":
            return 0
        if self._state == "ready":
            return 4
        return 3

    def current_status_chip(self) -> tuple[str | None, int]:
        """Return the current state-chip label and style kind."""

        duration_badge = self._duration_label()
        if self._state == "recording":
            return (duration_badge or "Recording", 2)
        if self._state == "review":
            return (duration_badge or "Ready", 4)
        if self._state == "sending":
            return ("Sending", 4)
        if self._state == "sent":
            return ("Sent", 1)
        if self._state == "failed":
            return ("Failed", 3)
        return ("Ready", 4)

    def current_view_model(self) -> tuple[str, str, str, str]:
        """Return title, subtitle, footer, and icon for the current voice-note state."""

        recipient = self.recipient_name()
        if self._state == "recording":
            return (
                "Recording",
                f"Release to stop your note for {recipient}.",
                "Release to stop" if self.is_one_button_mode() else "Select stop / Back cancel",
                "voice_note",
            )
        if self._state == "review":
            return (
                "Review",
                self.context.voice_note_status_text or f"Listen, send, or record again for {recipient}.",
                "Tap next / Double choose" if self.is_one_button_mode() else "Select choose / Back",
                "voice_note",
            )
        if self._state == "sending":
            return (
                "Sending",
                self.context.voice_note_status_text or f"Sending your note to {recipient}.",
                "Please wait",
                "voice_note",
            )
        if self._state == "sent":
            return (
                "Sent",
                self.context.voice_note_status_text or f"Your note reached {recipient}.",
                "Double done / Hold back" if self.is_one_button_mode() else "Back",
                "voice_note",
            )
        if self._state == "failed":
            return (
                "Couldn't Send",
                self.context.voice_note_status_text or f"Try {recipient}'s note again.",
                "Tap next / Double choose" if self.is_one_button_mode() else "Select retry / Back",
                "voice_note",
            )
        return (
            "Voice Note",
            f"Hold to record for {recipient}.",
            "Hold record / Double back" if self.is_one_button_mode() else "Select record / Back",
            "voice_note",
        )

    def render(self) -> None:
        """Render the current voice-note flow state."""

        self._sync_state_from_manager(default_state=self._state)
        lvgl_view = self._ensure_lvgl_view()
        if lvgl_view is not None:
            lvgl_view.sync()
            return

        title_text, _subtitle_text, footer_text, _icon_key = self.current_view_model()
        render_status_bar(self.display, self.context, show_time=True)
        bottom = draw_talk_person_header(
            self.display,
            center_x=self.display.WIDTH // 2,
            top=self.display.STATUS_BAR_HEIGHT + 26,
            name=self.recipient_name(),
            label=self.recipient_monogram(),
        )

        items, badges, selected_index = self.current_actions_for_view()
        if items:
            icons = self.current_action_icons()
            colors = self.current_action_colors()
            diameter = 56
            gap = 12
            center_y = bottom + 52
            row_width = (len(items) * diameter) + (max(0, len(items) - 1) * gap)
            start_center = ((self.display.WIDTH - row_width) // 2) + (diameter // 2)
            for row, _item_title in enumerate(items):
                draw_talk_action_button(
                    self.display,
                    center_x=start_center + (row * (diameter + gap)),
                    center_y=center_y,
                    button_size="small",
                    color=colors[row],
                    icon=icons[row],
                    filled=row == selected_index,
                    active=row == selected_index,
                )

            label = items[selected_index]
            label_width, label_height = self.display.get_text_size(label, 16)
            label_y = center_y + (diameter // 2) + 14
            self.display.text(
                label,
                (self.display.WIDTH - label_width) // 2,
                label_y,
                color=INK,
                font_size=16,
            )
            draw_talk_page_dots(
                self.display,
                center_x=self.display.WIDTH // 2,
                top=label_y + label_height + 14,
                total=len(items),
                current=selected_index,
                color=SUCCESS if self._state == "review" else WARNING,
            )
        else:
            center_y = bottom + 64
            draw_talk_action_button(
                self.display,
                center_x=self.display.WIDTH // 2,
                center_y=center_y,
                button_size="large",
                color=self.current_primary_color(),
                icon=self.current_primary_icon(),
                filled=False,
                active=True,
            )
            status_text, status_color = self.current_primary_status()
            draw_talk_status_chip(
                self.display,
                center_x=self.display.WIDTH // 2,
                top=center_y + 54,
                text=status_text,
                color=status_color,
            )

        render_footer(self.display, footer_text, mode="talk")
        self.display.update()

    def _selected_action(self) -> VoiceNoteAction | None:
        """Return the currently highlighted voice-note action."""

        actions = self.actions()
        if not actions:
            return None
        return actions[self._selected_action_index % len(actions)]

    def _close_to_talk_contact(self) -> None:
        """Clear terminal draft state and return to the selected contact."""

        if self.voip_manager is not None:
            self.voip_manager.discard_active_voice_note()
        if self.context is not None:
            self.context.update_active_voice_note(send_state="idle")
        self._state = "ready"
        self._selected_action_index = 0
        self.request_route("back")

    def _preview_active_voice_note(self) -> None:
        """Play the current draft locally before sending it."""

        if self.voip_manager is None or self.context is None:
            return

        file_path = self.context.voice_note_file_path
        if not file_path:
            return

        if self.voip_manager.play_voice_note(file_path):
            draft = self.voip_manager.get_active_voice_note()
            if draft is not None:
                draft.status_text = "Playing preview"
            self.context.update_active_voice_note(
                send_state="review",
                status_text="Playing preview",
                file_path=file_path,
                duration_ms=self.context.voice_note_duration_ms,
            )
            return

        draft = self.voip_manager.get_active_voice_note()
        if draft is not None:
            draft.status_text = "Couldn't play note"
        self.context.update_active_voice_note(
            send_state="review",
            status_text="Couldn't play note",
            file_path=file_path,
            duration_ms=self.context.voice_note_duration_ms,
        )

    def on_select(self, data=None) -> None:
        """Advance the voice-note flow."""

        if self._state == "ready":
            if self.is_one_button_mode():
                self.request_route("back")
                return
            self._start_recording()
            return
        if self._state == "recording":
            self._stop_recording()
            return
        if self._state == "review":
            selected_action = self._selected_action()
            if selected_action is None:
                return
            if selected_action.key == "send":
                self._send_active_voice_note()
                return
            if selected_action.key == "play":
                self._preview_active_voice_note()
                return
            self._discard_and_reset()
            return
        if self._state == "failed":
            selected_action = self._selected_action()
            if selected_action is None or selected_action.key == "retry":
                self._send_active_voice_note()
                return
            self._discard_and_reset()
            return
        if self._state == "sent":
            self._close_to_talk_contact()
            return
        if self._state == "sending":
            return
        self.request_route("back")

    def on_advance(self, data=None) -> None:
        """Cycle selectable actions in one-button mode."""

        actions = self.actions()
        if not actions:
            return
        self._selected_action_index = (self._selected_action_index + 1) % len(actions)

    def on_down(self, data=None) -> None:
        """Move to the next selectable action."""

        actions = self.actions()
        if not actions:
            return
        self._selected_action_index = (self._selected_action_index + 1) % len(actions)

    def on_up(self, data=None) -> None:
        """Move to the previous selectable action."""

        actions = self.actions()
        if not actions:
            return
        self._selected_action_index = (self._selected_action_index - 1) % len(actions)

    def on_back(self, data=None) -> None:
        """Return to the previous Talk screen."""

        if self._state == "recording":
            self._cancel_recording()
            return
        if self._state == "sending":
            return
        if self._state in {"review", "failed", "sent"}:
            self._close_to_talk_contact()
            return
        self.request_route("back")

    def on_ptt_press(self, data=None) -> None:
        """Start recording once the raw hold threshold is crossed."""

        if not isinstance(data, dict) or data.get("stage") != "hold_started":
            return
        if self._state != "ready":
            return
        self._start_recording()

    def on_ptt_release(self, data=None) -> None:
        """Stop an active recording when the button is released."""

        if self._state != "recording":
            return
        if not isinstance(data, dict) or not data.get("hold_started", False):
            self._cancel_recording()
            return
        self._stop_recording()

    def _start_recording(self) -> None:
        """Start a new voice-note recording for the active recipient."""

        if self.voip_manager is None:
            return
        if not self.voip_manager.start_voice_note_recording(
            self.recipient_address(),
            recipient_name=self.recipient_name(),
        ):
            self._state = "failed"
            if self.context is not None:
                self.context.update_active_voice_note(
                    send_state="failed",
                    status_text="Couldn't start recorder",
                )
            return
        self._selected_action_index = 0
        self._sync_state_from_manager(default_state="recording")
        self._refresh_input_mode()

    def _stop_recording(self) -> None:
        """Stop the active recording and move to review."""

        if self.voip_manager is None:
            return
        draft = self.voip_manager.stop_voice_note_recording()
        if draft is None:
            self._state = "failed"
            if self.context is not None:
                self.context.update_active_voice_note(
                    send_state="failed",
                    status_text="Couldn't save note",
                )
        else:
            self._state = "review"
            self._selected_action_index = 0
            self._sync_state_from_manager(default_state="review")
        self._refresh_input_mode()

    def _cancel_recording(self) -> None:
        """Cancel the active recording and return to the ready state."""

        if self.voip_manager is not None:
            self.voip_manager.cancel_voice_note_recording()
        self._state = "ready"
        self._selected_action_index = 0
        if self.context is not None:
            self.context.update_active_voice_note(send_state="idle")
        self._refresh_input_mode()

    def _discard_and_reset(self) -> None:
        """Discard the current draft and return to the ready state."""

        if self.voip_manager is not None:
            self.voip_manager.discard_active_voice_note()
        self._state = "ready"
        self._selected_action_index = 0
        if self.context is not None:
            self.context.update_active_voice_note(send_state="idle")
        self._refresh_input_mode()

    def _send_active_voice_note(self) -> None:
        """Send the recorded voice note through the VoIP manager."""

        if self.voip_manager is None:
            return
        if self.voip_manager.send_active_voice_note():
            self._sync_state_from_manager(default_state="sending")
            self._state = "sending"
            return
        self._sync_state_from_manager(default_state="failed")
        self._state = "failed"
