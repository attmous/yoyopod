"""Models and helpers for the voice-note screen."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from yoyopod.app_context import AppContext
    from yoyopod.communication import VoIPManager


@dataclass(frozen=True, slots=True)
class VoiceNoteAction:
    """One selectable action in the voice-note flow."""

    key: str
    title: str
    badge: str = ""


@dataclass(frozen=True, slots=True)
class VoiceNoteState:
    """Prepared state for the voice-note flow."""

    recipient_name: str = "Friend"
    recipient_address: str = ""
    send_state: str = "idle"
    status_text: str = ""
    file_path: str = ""
    duration_ms: int = 0


@dataclass(frozen=True, slots=True)
class VoiceNoteActions:
    """Focused voice-note actions exposed to the screen."""

    start_recording: Callable[[str, str], bool] | None = None
    stop_recording: Callable[[], object | None] | None = None
    cancel_recording: Callable[[], bool] | None = None
    discard_active_draft: Callable[[], None] | None = None
    send_active_draft: Callable[[], bool] | None = None
    preview_draft: Callable[[str], bool] | None = None
    set_draft_status_text: Callable[[str], None] | None = None


def _resolve_voice_note_recipient(
    context: "AppContext | None",
) -> tuple[str, str]:
    """Return the active voice-note recipient from the current UI context."""

    if context is None:
        return ("Friend", "")

    voice_note = context.talk.active_voice_note
    selected_contact = context.talk
    return (
        voice_note.recipient_name or selected_contact.selected_contact_name or "Friend",
        voice_note.recipient_address or selected_contact.selected_contact_address,
    )


def build_voice_note_state_provider(
    *,
    context: "AppContext | None" = None,
    voip_manager: "VoIPManager | None" = None,
) -> Callable[[], VoiceNoteState]:
    """Build a narrow prepared-state provider for the voice-note screen."""

    def provider() -> VoiceNoteState:
        recipient_name, recipient_address = _resolve_voice_note_recipient(context)
        if voip_manager is None:
            active_voice_note = context.talk.active_voice_note if context is not None else None
            return VoiceNoteState(
                recipient_name=recipient_name,
                recipient_address=recipient_address,
                send_state=(
                    active_voice_note.send_state if active_voice_note is not None else "idle"
                ),
                status_text=active_voice_note.status_text if active_voice_note is not None else "",
                file_path=active_voice_note.file_path if active_voice_note is not None else "",
                duration_ms=active_voice_note.duration_ms if active_voice_note is not None else 0,
            )

        draft = voip_manager.get_active_voice_note()
        if draft is None:
            return VoiceNoteState(
                recipient_name=recipient_name,
                recipient_address=recipient_address,
            )
        if (
            recipient_address
            and draft.recipient_address
            and draft.recipient_address != recipient_address
        ):
            return VoiceNoteState(
                recipient_name=recipient_name,
                recipient_address=recipient_address,
            )

        return VoiceNoteState(
            recipient_name=draft.recipient_name or recipient_name,
            recipient_address=draft.recipient_address or recipient_address,
            send_state=draft.send_state or "idle",
            status_text=draft.status_text,
            file_path=draft.file_path,
            duration_ms=draft.duration_ms,
        )

    return provider


def build_voice_note_actions(
    *,
    voip_manager: "VoIPManager | None" = None,
) -> VoiceNoteActions:
    """Build the focused voice-note actions for the screen."""

    def set_draft_status_text(status_text: str) -> None:
        if voip_manager is None:
            return
        draft = voip_manager.get_active_voice_note()
        if draft is not None:
            draft.status_text = status_text

    if voip_manager is None:
        return VoiceNoteActions(set_draft_status_text=set_draft_status_text)

    start_voice_note_recording = getattr(voip_manager, "start_voice_note_recording", None)
    stop_voice_note_recording = getattr(voip_manager, "stop_voice_note_recording", None)
    cancel_voice_note_recording = getattr(voip_manager, "cancel_voice_note_recording", None)
    discard_active_voice_note = getattr(voip_manager, "discard_active_voice_note", None)
    send_active_voice_note = getattr(voip_manager, "send_active_voice_note", None)
    play_voice_note = getattr(voip_manager, "play_voice_note", None)

    return VoiceNoteActions(
        start_recording=(
            None
            if start_voice_note_recording is None
            else lambda recipient_address, recipient_name: start_voice_note_recording(
                recipient_address,
                recipient_name=recipient_name,
            )
        ),
        stop_recording=stop_voice_note_recording,
        cancel_recording=cancel_voice_note_recording,
        discard_active_draft=discard_active_voice_note,
        send_active_draft=send_active_voice_note,
        preview_draft=play_voice_note,
        set_draft_status_text=set_draft_status_text,
    )


__all__ = [
    "VoiceNoteAction",
    "VoiceNoteState",
    "VoiceNoteActions",
    "build_voice_note_state_provider",
    "build_voice_note_actions",
]
