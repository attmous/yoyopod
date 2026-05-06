"""Canonical public seam for voice interaction models and services."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yoyopod_cli.pi.support.voice_worker_contract import (
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
    from yoyopod.integrations.voice.activation import (
        VoiceActivationNormalizer,
        VoiceActivationResult,
        normalize_voice_activation,
    )
    from yoyopod.integrations.voice.ask_conversation import AskConversationState
    from yoyopod_cli.pi.support.voice_commands import (
        VOICE_COMMAND_GRAMMAR,
        VoiceCommandIntent,
        VoiceCommandMatch,
        VoiceCommandTemplate,
        match_voice_command,
    )
    from yoyopod_cli.pi.support.voice_dictionary import (
        SAFE_VOICE_ROUTE_ACTIONS,
        VoiceCommandAction,
        VoiceCommandDictionary,
        load_voice_command_dictionary,
    )
    from yoyopod.integrations.voice.executor import VoiceCommandExecutor
    from yoyopod.integrations.voice.manager import VoiceManager, VoiceService
    from yoyopod_cli.pi.support.voice_models import (
        VoiceCaptureRequest,
        VoiceCaptureResult,
        VoiceSettings,
        VoiceTranscript,
    )
    from yoyopod.integrations.voice.runtime import VoiceRuntimeCoordinator
    from yoyopod.integrations.voice.router import (
        VoiceRouteDecision,
        VoiceRouteKind,
        VoiceRouter,
    )
    from yoyopod_cli.pi.support.voice_settings import VoiceCommandOutcome, VoiceSettingsResolver
    from yoyopod.integrations.voice.wake import (
        NoopWakeDetector,
        WakeDetectionResult,
        WakeDetector,
    )
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
    "NoopWakeDetector": ("yoyopod.integrations.voice.wake", "NoopWakeDetector"),
    "SAFE_VOICE_ROUTE_ACTIONS": (
        "yoyopod_cli.pi.support.voice_dictionary",
        "SAFE_VOICE_ROUTE_ACTIONS",
    ),
    "VOICE_COMMAND_GRAMMAR": ("yoyopod_cli.pi.support.voice_commands", "VOICE_COMMAND_GRAMMAR"),
    "VoiceCaptureRequest": ("yoyopod_cli.pi.support.voice_models", "VoiceCaptureRequest"),
    "VoiceCaptureResult": ("yoyopod_cli.pi.support.voice_models", "VoiceCaptureResult"),
    "VoiceActivationNormalizer": (
        "yoyopod.integrations.voice.activation",
        "VoiceActivationNormalizer",
    ),
    "VoiceActivationResult": (
        "yoyopod.integrations.voice.activation",
        "VoiceActivationResult",
    ),
    "VoiceCommandIntent": ("yoyopod_cli.pi.support.voice_commands", "VoiceCommandIntent"),
    "VoiceCommandMatch": ("yoyopod_cli.pi.support.voice_commands", "VoiceCommandMatch"),
    "VoiceCommandOutcome": ("yoyopod_cli.pi.support.voice_settings", "VoiceCommandOutcome"),
    "VoiceCommandTemplate": ("yoyopod_cli.pi.support.voice_commands", "VoiceCommandTemplate"),
    "VoiceCommandAction": ("yoyopod_cli.pi.support.voice_dictionary", "VoiceCommandAction"),
    "VoiceCommandDictionary": (
        "yoyopod_cli.pi.support.voice_dictionary",
        "VoiceCommandDictionary",
    ),
    "VoiceCommandExecutor": ("yoyopod.integrations.voice.executor", "VoiceCommandExecutor"),
    "VoiceManager": ("yoyopod.integrations.voice.manager", "VoiceManager"),
    "VoiceRuntimeCoordinator": ("yoyopod.integrations.voice.runtime", "VoiceRuntimeCoordinator"),
    "VoiceRouteDecision": ("yoyopod.integrations.voice.router", "VoiceRouteDecision"),
    "VoiceRouteKind": ("yoyopod.integrations.voice.router", "VoiceRouteKind"),
    "VoiceRouter": ("yoyopod.integrations.voice.router", "VoiceRouter"),
    "VoiceService": ("yoyopod.integrations.voice.manager", "VoiceService"),
    "VoiceSettings": ("yoyopod_cli.pi.support.voice_models", "VoiceSettings"),
    "VoiceSettingsResolver": ("yoyopod_cli.pi.support.voice_settings", "VoiceSettingsResolver"),
    "VoiceTranscript": ("yoyopod_cli.pi.support.voice_models", "VoiceTranscript"),
    "WakeDetectionResult": ("yoyopod.integrations.voice.wake", "WakeDetectionResult"),
    "WakeDetector": ("yoyopod.integrations.voice.wake", "WakeDetector"),
    "VoiceWorkerAskResult": (
        "yoyopod_cli.pi.support.voice_worker_contract",
        "VoiceWorkerAskResult",
    ),
    "VoiceWorkerAskTurn": (
        "yoyopod_cli.pi.support.voice_worker_contract",
        "VoiceWorkerAskTurn",
    ),
    "VoiceWorkerError": ("yoyopod_cli.pi.support.voice_worker_contract", "VoiceWorkerError"),
    "VoiceWorkerHealthResult": (
        "yoyopod_cli.pi.support.voice_worker_contract",
        "VoiceWorkerHealthResult",
    ),
    "VoiceWorkerClient": ("yoyopod.integrations.voice.worker_client", "VoiceWorkerClient"),
    "VoiceWorkerSpeakResult": (
        "yoyopod_cli.pi.support.voice_worker_contract",
        "VoiceWorkerSpeakResult",
    ),
    "VoiceWorkerTimeout": ("yoyopod.integrations.voice.worker_client", "VoiceWorkerTimeout"),
    "VoiceWorkerTranscribeResult": (
        "yoyopod_cli.pi.support.voice_worker_contract",
        "VoiceWorkerTranscribeResult",
    ),
    "VoiceWorkerUnavailable": (
        "yoyopod.integrations.voice.worker_client",
        "VoiceWorkerUnavailable",
    ),
    "build_ask_payload": ("yoyopod_cli.pi.support.voice_worker_contract", "build_ask_payload"),
    "build_speak_payload": ("yoyopod_cli.pi.support.voice_worker_contract", "build_speak_payload"),
    "build_transcribe_payload": (
        "yoyopod_cli.pi.support.voice_worker_contract",
        "build_transcribe_payload",
    ),
    "load_voice_command_dictionary": (
        "yoyopod_cli.pi.support.voice_dictionary",
        "load_voice_command_dictionary",
    ),
    "match_voice_command": ("yoyopod_cli.pi.support.voice_commands", "match_voice_command"),
    "normalize_voice_activation": (
        "yoyopod.integrations.voice.activation",
        "normalize_voice_activation",
    ),
    "parse_ask_result": ("yoyopod_cli.pi.support.voice_worker_contract", "parse_ask_result"),
    "parse_speak_result": ("yoyopod_cli.pi.support.voice_worker_contract", "parse_speak_result"),
    "parse_health_result": ("yoyopod_cli.pi.support.voice_worker_contract", "parse_health_result"),
    "parse_transcribe_result": (
        "yoyopod_cli.pi.support.voice_worker_contract",
        "parse_transcribe_result",
    ),
    "parse_worker_error": ("yoyopod_cli.pi.support.voice_worker_contract", "parse_worker_error"),
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
    "NoopWakeDetector",
    "SAFE_VOICE_ROUTE_ACTIONS",
    "VOICE_COMMAND_GRAMMAR",
    "VoiceActivationNormalizer",
    "VoiceActivationResult",
    "VoiceCaptureRequest",
    "VoiceCaptureResult",
    "VoiceCommandIntent",
    "VoiceCommandAction",
    "VoiceCommandDictionary",
    "VoiceCommandMatch",
    "VoiceCommandOutcome",
    "VoiceCommandTemplate",
    "VoiceCommandExecutor",
    "VoiceManager",
    "VoiceRuntimeCoordinator",
    "VoiceRouteDecision",
    "VoiceRouteKind",
    "VoiceRouter",
    "VoiceService",
    "VoiceSettings",
    "VoiceSettingsResolver",
    "VoiceTranscript",
    "WakeDetectionResult",
    "WakeDetector",
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
    "load_voice_command_dictionary",
    "match_voice_command",
    "normalize_voice_activation",
    "parse_ask_result",
    "parse_speak_result",
    "parse_health_result",
    "parse_transcribe_result",
    "parse_worker_error",
]
