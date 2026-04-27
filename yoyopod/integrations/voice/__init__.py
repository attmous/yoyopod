"""Canonical public seam for voice interaction models and services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yoyopod.integrations.voice.worker_contract import (
    VoiceWorkerAskResult,
    VoiceWorkerAskTurn,
    VoiceWorkerError,
    VoiceWorkerHealthResult,
    VoiceWorkerSpeakResult,
    VoiceWorkerTranscribeResult,
    build_ask_payload,
    build_speak_payload,
    build_transcribe_payload,
    parse_ask_result,
    parse_health_result,
    parse_speak_result,
    parse_transcribe_result,
    parse_worker_error,
)

if TYPE_CHECKING:
    from yoyopod.integrations.voice.ask_conversation import AskConversationState
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
    from yoyopod.integrations.voice.worker_client import (
        VoiceWorkerClient,
        VoiceWorkerTimeout,
        VoiceWorkerUnavailable,
    )


_PUBLIC_EXPORTS = {
    "AskConversationState": (
        "yoyopod.integrations.voice.ask_conversation",
        "AskConversationState",
    ),
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
    "VoiceWorkerAskResult": (
        "yoyopod.integrations.voice.worker_contract",
        "VoiceWorkerAskResult",
    ),
    "VoiceWorkerAskTurn": (
        "yoyopod.integrations.voice.worker_contract",
        "VoiceWorkerAskTurn",
    ),
    "VoiceWorkerError": ("yoyopod.integrations.voice.worker_contract", "VoiceWorkerError"),
    "VoiceWorkerHealthResult": (
        "yoyopod.integrations.voice.worker_contract",
        "VoiceWorkerHealthResult",
    ),
    "VoiceWorkerClient": ("yoyopod.integrations.voice.worker_client", "VoiceWorkerClient"),
    "VoiceWorkerSpeakResult": (
        "yoyopod.integrations.voice.worker_contract",
        "VoiceWorkerSpeakResult",
    ),
    "VoiceWorkerTimeout": ("yoyopod.integrations.voice.worker_client", "VoiceWorkerTimeout"),
    "VoiceWorkerTranscribeResult": (
        "yoyopod.integrations.voice.worker_contract",
        "VoiceWorkerTranscribeResult",
    ),
    "VoiceWorkerUnavailable": (
        "yoyopod.integrations.voice.worker_client",
        "VoiceWorkerUnavailable",
    ),
    "build_ask_payload": ("yoyopod.integrations.voice.worker_contract", "build_ask_payload"),
    "build_speak_payload": ("yoyopod.integrations.voice.worker_contract", "build_speak_payload"),
    "build_transcribe_payload": (
        "yoyopod.integrations.voice.worker_contract",
        "build_transcribe_payload",
    ),
    "match_voice_command": ("yoyopod.integrations.voice.commands", "match_voice_command"),
    "parse_ask_result": ("yoyopod.integrations.voice.worker_contract", "parse_ask_result"),
    "parse_speak_result": ("yoyopod.integrations.voice.worker_contract", "parse_speak_result"),
    "parse_health_result": ("yoyopod.integrations.voice.worker_contract", "parse_health_result"),
    "parse_transcribe_result": (
        "yoyopod.integrations.voice.worker_contract",
        "parse_transcribe_result",
    ),
    "parse_worker_error": ("yoyopod.integrations.voice.worker_contract", "parse_worker_error"),
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
    "AskConversationState",
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
    "VoiceWorkerAskResult",
    "VoiceWorkerAskTurn",
    "VoiceWorkerClient",
    "VoiceWorkerError",
    "VoiceWorkerHealthResult",
    "VoiceWorkerSpeakResult",
    "VoiceWorkerTimeout",
    "VoiceWorkerTranscribeResult",
    "VoiceWorkerUnavailable",
    "build_ask_payload",
    "build_speak_payload",
    "build_transcribe_payload",
    "match_voice_command",
    "parse_ask_result",
    "parse_speak_result",
    "parse_health_result",
    "parse_transcribe_result",
    "parse_worker_error",
]
