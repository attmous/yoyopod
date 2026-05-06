"""App-facing active voice-note draft model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class VoiceNoteDraft:
    """Locally selected voice-note draft state mirrored from the Rust VoIP runtime."""

    recipient_address: str
    recipient_name: str
    file_path: str
    duration_ms: int = 0
    mime_type: str = "audio/wav"
    message_id: str = ""
    send_state: str = "idle"
    status_text: str = ""
    send_started_at: float = 0.0


__all__ = ["VoiceNoteDraft"]
