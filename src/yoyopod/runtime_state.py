"""Compatibility exports for relocated runtime state dataclasses."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from yoyopod.audio.music.models import PlaybackQueue, Track
from yoyopod.core.runtime_state import (
    ActiveVoiceNoteState,
    MediaRuntimeState,
    NetworkRuntimeState,
    PlaybackState,
    PowerRuntimeState,
    ScreenRuntimeState,
    TalkRuntimeState,
    VoiceInteractionState,
    VoiceState,
    VoipRuntimeState,
)

__all__ = [
    "ActiveVoiceNoteState",
    "MediaRuntimeState",
    "NetworkRuntimeState",
    "PlaybackQueue",
    "PlaybackState",
    "PowerRuntimeState",
    "ScreenRuntimeState",
    "TalkRuntimeState",
    "Track",
    "VoiceInteractionState",
    "VoiceState",
    "VoipRuntimeState",
]
