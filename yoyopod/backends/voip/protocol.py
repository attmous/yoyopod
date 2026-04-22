"""VoIP backend protocol and metric dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from yoyopod.integrations.call.models import VoIPEvent


class VoIPBackend(Protocol):
    """Backend contract for SIP and messaging implementations used by VoIPManager."""

    def start(self) -> bool:
        """Start the backend and begin emitting events."""

    def stop(self) -> None:
        """Stop the backend and release resources."""

    def iterate(self) -> int:
        """Advance the backend once on the coordinator thread and return drained event count."""

    def make_call(self, sip_address: str) -> bool:
        """Initiate an outgoing call."""

    def answer_call(self) -> bool:
        """Answer the current incoming call."""

    def reject_call(self) -> bool:
        """Reject the current incoming call."""

    def hangup(self) -> bool:
        """Terminate the current call."""

    def mute(self) -> bool:
        """Mute the current call microphone."""

    def unmute(self) -> bool:
        """Unmute the current call microphone."""

    def send_text_message(self, sip_address: str, text: str) -> str | None:
        """Send a text message and return its backend identifier when available."""

    def start_voice_note_recording(self, file_path: str) -> bool:
        """Begin recording a voice note to the provided file path."""

    def stop_voice_note_recording(self) -> int | None:
        """Stop the active recording and return its duration in milliseconds."""

    def cancel_voice_note_recording(self) -> bool:
        """Cancel and discard the active recording."""

    def send_voice_note(
        self,
        sip_address: str,
        *,
        file_path: str,
        duration_ms: int,
        mime_type: str,
    ) -> str | None:
        """Send a recorded voice note and return its backend identifier when available."""

    def on_event(self, callback: Callable[[VoIPEvent], None]) -> None:
        """Register a typed backend-event listener."""

    def get_iterate_metrics(self) -> VoIPIterateMetrics | None:
        """Return the latest backend iteration timing sample if available."""


@dataclass(frozen=True, slots=True)
class VoIPIterateMetrics:
    """Most recent keep-alive timing captured around one backend iterate."""

    native_duration_seconds: float = 0.0
    event_drain_duration_seconds: float = 0.0
    total_duration_seconds: float = 0.0
    drained_events: int = 0
