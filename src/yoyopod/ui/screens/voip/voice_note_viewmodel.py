"""View-model helpers for the voice-note screen."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.ui.screens.theme import (
    ERROR,
    SUCCESS,
    TALK,
    WARNING,
    MUTED,
)
from yoyopod.ui.screens.voip.voice_note_models import VoiceNoteAction, VoiceNoteState


@dataclass(frozen=True, slots=True)
class VoiceNoteViewModel:
    """Pure transformation of voice-note flow state for rendering."""

    state: VoiceNoteState
    flow_state: str
    one_button_mode: bool
    selected_action_index: int = 0

    def actions(self) -> list[VoiceNoteAction]:
        """Return the selectable actions for the current flow state."""

        duration_badge = self._duration_label()
        if self.flow_state == "review":
            return [
                VoiceNoteAction("send", "Send", duration_badge),
                VoiceNoteAction("play", "Play"),
                VoiceNoteAction("again", "Again"),
            ]
        if self.flow_state == "failed":
            return [
                VoiceNoteAction("retry", "Retry"),
                VoiceNoteAction("again", "Again"),
            ]
        return []

    @staticmethod
    def _duration_label_from_ms(duration_ms: int) -> str:
        if duration_ms <= 0:
            return ""
        seconds = max(1, round(duration_ms / 1000))
        return f"{seconds}s"

    def _duration_label(self) -> str:
        """Return a compact duration label for the active draft."""

        return self._duration_label_from_ms(self.state.duration_ms)

    def current_actions_for_view(self) -> tuple[list[str], list[str], int]:
        """Return visible action rows for the current flow state."""

        actions = self.actions()
        return (
            [action.title for action in actions],
            [action.badge for action in actions],
            min(self.selected_action_index, max(0, len(actions) - 1)),
        )

    def current_action_subtitles(self) -> list[str]:
        """Return subtitles for the selectable action list."""

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
        """Return icon keys for the selectable action list."""

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
        """Return the Talk action colors for the action row."""

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
        """Return native LVGL color kinds for the action row."""

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

        if self.flow_state == "sent":
            return "check"
        if self.flow_state == "failed":
            return "close"
        return "voice_note"

    def current_primary_color(self) -> tuple[int, int, int]:
        """Return the large centered action color for non-review states."""

        if self.flow_state == "sent":
            return SUCCESS
        if self.flow_state == "sending":
            return TALK.accent
        return ERROR

    def current_primary_color_kind(self) -> int:
        """Return the native LVGL color kind for the centered action."""

        if self.flow_state == "sent":
            return 1
        if self.flow_state == "sending":
            return 0
        if self.flow_state == "ready":
            return 3
        return 3

    def current_primary_status(self) -> tuple[str, tuple[int, int, int]]:
        """Return the primary status label and color for non-review states."""

        if self.flow_state == "ready":
            return ("Hold to record", MUTED)
        if self.flow_state == "recording":
            return ("Recording", ERROR)
        if self.flow_state == "sending":
            return ("Sending", TALK.accent)
        if self.flow_state == "sent":
            return ("Sent", SUCCESS)
        if self.flow_state == "failed":
            return ("Couldn't send", ERROR)
        return ("Voice Note", MUTED)

    def current_primary_status_kind(self) -> int:
        """Return the native LVGL color kind for the centered status label."""

        if self.flow_state == "sent":
            return 1
        if self.flow_state == "sending":
            return 0
        if self.flow_state == "ready":
            return 4
        return 3

    def current_status_chip(self) -> tuple[str | None, int]:
        """Return the current state-chip label and style kind."""

        duration_badge = self._duration_label()
        if self.flow_state == "recording":
            return (duration_badge or "Recording", 2)
        if self.flow_state == "review":
            return (duration_badge or "Ready", 4)
        if self.flow_state == "sending":
            return ("Sending", 4)
        if self.flow_state == "sent":
            return ("Sent", 1)
        if self.flow_state == "failed":
            return ("Failed", 3)
        return ("Ready", 4)

    def current_view_model(self) -> tuple[str, str, str, str]:
        """Return title, subtitle, footer, and icon for the current flow state."""

        recipient = self.state.recipient_name
        if self.flow_state == "recording":
            return (
                "Recording",
                f"Release to stop your note for {recipient}.",
                "Release to stop" if self.one_button_mode else "Select stop / Back cancel",
                "voice_note",
            )
        if self.flow_state == "review":
            return (
                "Review",
                self.state.status_text or f"Listen, send, or record again for {recipient}.",
                "Tap next / Double choose" if self.one_button_mode else "Select choose / Back",
                "voice_note",
            )
        if self.flow_state == "sending":
            return (
                "Sending",
                self.state.status_text or f"Sending your note to {recipient}.",
                "Please wait",
                "voice_note",
            )
        if self.flow_state == "sent":
            return (
                "Sent",
                self.state.status_text or f"Your note reached {recipient}.",
                "Double done / Hold back" if self.one_button_mode else "Back",
                "voice_note",
            )
        if self.flow_state == "failed":
            return (
                "Couldn't Send",
                self.state.status_text or f"Try {recipient}'s note again.",
                "Tap next / Double choose" if self.one_button_mode else "Select retry / Back",
                "voice_note",
            )
        return (
            "Voice Note",
            f"Hold to record for {recipient}.",
            "Hold record / Double back" if self.one_button_mode else "Select record / Back",
            "voice_note",
        )


__all__ = ["VoiceNoteViewModel"]
