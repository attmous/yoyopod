"""Command-first routing for unified YoYo voice interactions."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from yoyopod.integrations.voice.activation import VoiceActivationNormalizer
from yoyopod_cli.pi.support.voice_commands import VoiceCommandMatch, match_voice_command
from yoyopod_cli.pi.support.voice_dictionary import VoiceCommandDictionary


class VoiceRouteKind(StrEnum):
    """Possible post-transcription voice routing decisions."""

    COMMAND = "command"
    ACTION = "action"
    ASK_FALLBACK = "ask_fallback"
    LOCAL_HELP = "local_help"


@dataclass(slots=True, frozen=True)
class VoiceRouteDecision:
    """Decision returned after normalizing and routing one transcript."""

    kind: VoiceRouteKind
    original_text: str
    normalized_text: str
    stripped_prefix: str
    command: VoiceCommandMatch | None = None
    route_name: str | None = None
    confidence: float = 0.0
    reason: str = ""


class VoiceRouter:
    """Route one transcribed phrase to command execution or Ask fallback."""

    def __init__(
        self,
        *,
        dictionary: VoiceCommandDictionary,
        activation_prefixes: tuple[str, ...],
        ask_fallback_enabled: bool,
    ) -> None:
        self._dictionary = dictionary
        self._normalizer = VoiceActivationNormalizer(prefixes=activation_prefixes)
        self._ask_fallback_enabled = ask_fallback_enabled

    def route(self, transcript: str) -> VoiceRouteDecision:
        """Return a command-first routing decision for one transcript."""

        activation = self._normalizer.normalize(transcript)
        command = match_voice_command(
            activation.normalized_text,
            grammar=self._dictionary.to_grammar(),
        )
        if command.is_command:
            return VoiceRouteDecision(
                kind=VoiceRouteKind.COMMAND,
                original_text=transcript,
                normalized_text=activation.normalized_text,
                stripped_prefix=activation.stripped_prefix,
                command=command,
                confidence=1.0,
                reason="command_match",
            )
        action = self._dictionary.match_action(activation.normalized_text)
        if action is not None:
            return VoiceRouteDecision(
                kind=VoiceRouteKind.ACTION,
                original_text=transcript,
                normalized_text=activation.normalized_text,
                stripped_prefix=activation.stripped_prefix,
                route_name=action.route,
                confidence=1.0,
                reason="action_match",
            )
        if self._ask_fallback_enabled and activation.normalized_text:
            return VoiceRouteDecision(
                kind=VoiceRouteKind.ASK_FALLBACK,
                original_text=transcript,
                normalized_text=activation.normalized_text,
                stripped_prefix=activation.stripped_prefix,
                reason="ask_fallback",
            )
        return VoiceRouteDecision(
            kind=VoiceRouteKind.LOCAL_HELP,
            original_text=transcript,
            normalized_text=activation.normalized_text,
            stripped_prefix=activation.stripped_prefix,
            reason="no_command_no_fallback",
        )


__all__ = [
    "VoiceRouteDecision",
    "VoiceRouteKind",
    "VoiceRouter",
]
