"""Canonical public seam for voice interaction models and services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.integrations.voice.commands import (
        VOICE_COMMAND_GRAMMAR,
        VoiceCommandIntent,
        VoiceCommandMatch,
        VoiceCommandTemplate,
        match_voice_command,
    )
    from yoyopod.integrations.voice.executor import VoiceCommandExecutor
    from yoyopod.integrations.voice.manager import VoiceManager, VoiceService
    from yoyopod.integrations.voice.models import (
        VoiceCaptureRequest,
        VoiceCaptureResult,
        VoiceSettings,
        VoiceTranscript,
    )
    from yoyopod.integrations.voice.runtime import VoiceRuntimeCoordinator
    from yoyopod.integrations.voice.settings import VoiceCommandOutcome, VoiceSettingsResolver


_PUBLIC_EXPORTS = {
    "VOICE_COMMAND_GRAMMAR": ("yoyopod.integrations.voice.commands", "VOICE_COMMAND_GRAMMAR"),
    "VoiceCaptureRequest": ("yoyopod.integrations.voice.models", "VoiceCaptureRequest"),
    "VoiceCaptureResult": ("yoyopod.integrations.voice.models", "VoiceCaptureResult"),
    "VoiceCommandIntent": ("yoyopod.integrations.voice.commands", "VoiceCommandIntent"),
    "VoiceCommandMatch": ("yoyopod.integrations.voice.commands", "VoiceCommandMatch"),
    "VoiceCommandOutcome": ("yoyopod.integrations.voice.settings", "VoiceCommandOutcome"),
    "VoiceCommandTemplate": ("yoyopod.integrations.voice.commands", "VoiceCommandTemplate"),
    "VoiceCommandExecutor": ("yoyopod.integrations.voice.executor", "VoiceCommandExecutor"),
    "VoiceManager": ("yoyopod.integrations.voice.manager", "VoiceManager"),
    "VoiceRuntimeCoordinator": ("yoyopod.integrations.voice.runtime", "VoiceRuntimeCoordinator"),
    "VoiceService": ("yoyopod.integrations.voice.manager", "VoiceService"),
    "VoiceSettings": ("yoyopod.integrations.voice.models", "VoiceSettings"),
    "VoiceSettingsResolver": ("yoyopod.integrations.voice.settings", "VoiceSettingsResolver"),
    "VoiceTranscript": ("yoyopod.integrations.voice.models", "VoiceTranscript"),
    "match_voice_command": ("yoyopod.integrations.voice.commands", "match_voice_command"),
}


def __getattr__(name: str) -> Any:
    """Load public voice exports lazily to avoid compatibility import cycles."""

    try:
        module_name, attribute = _PUBLIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = __import__(module_name, fromlist=[attribute])
    return getattr(module, attribute)


__all__ = [
    "VOICE_COMMAND_GRAMMAR",
    "VoiceCaptureRequest",
    "VoiceCaptureResult",
    "VoiceCommandIntent",
    "VoiceCommandMatch",
    "VoiceCommandOutcome",
    "VoiceCommandTemplate",
    "VoiceCommandExecutor",
    "VoiceManager",
    "VoiceRuntimeCoordinator",
    "VoiceService",
    "VoiceSettings",
    "VoiceSettingsResolver",
    "VoiceTranscript",
    "match_voice_command",
]
