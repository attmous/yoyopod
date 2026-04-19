"""Recording controller for the voice-note screen."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.ui.screens.voip.voice_note_models import VoiceNoteActions


@dataclass(frozen=True, slots=True)
class VoiceNoteRecordingResult:
    """Result of an attempted recording transition."""

    next_state: str | None
    status_text: str | None = None


class VoiceNoteRecordingController:
    """Pure controller for voice-note recording lifecycle transitions."""

    def __init__(self, actions: VoiceNoteActions | None = None) -> None:
        self._actions = actions or VoiceNoteActions()

    def start_recording(
        self,
        *,
        recipient_address: str,
        recipient_name: str,
    ) -> VoiceNoteRecordingResult:
        """Start a new voice-note recording for the active recipient."""

        if self._actions.start_recording is None:
            return VoiceNoteRecordingResult(next_state=None)
        if not self._actions.start_recording(recipient_address, recipient_name):
            return VoiceNoteRecordingResult(
                next_state="failed",
                status_text="Couldn't start recorder",
            )
        return VoiceNoteRecordingResult(next_state="recording")

    def stop_recording(self) -> VoiceNoteRecordingResult:
        """Stop the active recording and transition to review."""

        if self._actions.stop_recording is None:
            return VoiceNoteRecordingResult(next_state=None)
        draft = self._actions.stop_recording()
        if draft is None:
            return VoiceNoteRecordingResult(next_state="failed", status_text="Couldn't save note")
        return VoiceNoteRecordingResult(
            next_state=getattr(draft, "send_state", "review") or "review",
            status_text=getattr(draft, "status_text", None),
        )

    def cancel_recording(self) -> VoiceNoteRecordingResult:
        """Cancel the active recording and return to ready."""

        if self._actions.cancel_recording is not None:
            self._actions.cancel_recording()
        return VoiceNoteRecordingResult(next_state="ready")


__all__ = [
    "VoiceNoteRecordingController",
    "VoiceNoteRecordingResult",
]
