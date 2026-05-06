"""Typed commands for the scaffold call integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DialCommand:
    """Request a new outgoing call."""

    sip_address: str
    contact_name: str = ""


@dataclass(frozen=True, slots=True)
class AnswerCommand:
    """Answer the active incoming call."""


@dataclass(frozen=True, slots=True)
class HangupCommand:
    """Hang up the active call."""


@dataclass(frozen=True, slots=True)
class RejectCommand:
    """Reject the active incoming call."""


@dataclass(frozen=True, slots=True)
class MuteCommand:
    """Mute the active call."""


@dataclass(frozen=True, slots=True)
class UnmuteCommand:
    """Unmute the active call."""


@dataclass(frozen=True, slots=True)
class SendTextMessageCommand:
    """Send one text message through the call-domain messaging seam."""

    sip_address: str
    text: str
    display_name: str = ""


@dataclass(frozen=True, slots=True)
class StartVoiceNoteRecordingCommand:
    """Start recording a voice note for one recipient."""

    recipient_address: str
    recipient_name: str = ""


@dataclass(frozen=True, slots=True)
class StopVoiceNoteRecordingCommand:
    """Stop the current voice-note recording."""


@dataclass(frozen=True, slots=True)
class CancelVoiceNoteRecordingCommand:
    """Cancel and discard the active voice-note recording."""


@dataclass(frozen=True, slots=True)
class SendActiveVoiceNoteCommand:
    """Send the current voice-note draft."""


@dataclass(frozen=True, slots=True)
class PlayLatestVoiceNoteCommand:
    """Play the latest stored voice note for one contact."""

    sip_address: str


@dataclass(frozen=True, slots=True)
class MarkHistorySeenCommand:
    """Mark all missed-call history rows as seen."""

