"""Mutable voice command dictionary layered over built-in grammar."""

from __future__ import annotations

from dataclasses import dataclass, replace
import math
from pathlib import Path
from typing import Any

from loguru import logger
import yaml

from yoyopod_cli.pi.support.voice_commands import (
    VOICE_COMMAND_GRAMMAR,
    VoiceCommandIntent,
    VoiceCommandTemplate,
)

SAFE_VOICE_ROUTE_ACTIONS = frozenset({"open_talk", "open_listen", "open_setup", "go_home", "back"})
_DEFAULT_TRANSCRIPTION_PROMPT = (
    "Transcribe this YoYoPod voice command in English Latin letters. "
    "Do not output Arabic, Persian, Korean, or other non-Latin scripts. "
    "Preserve family names such as mama, baba, mom, dad, mommy, daddy, and papa."
)


@dataclass(slots=True, frozen=True)
class VoiceCommandAction:
    """Mutable dictionary action routed by a later command layer."""

    name: str
    aliases: tuple[str, ...]
    route: str


@dataclass(slots=True, frozen=True)
class VoiceCommandDictionary:
    """Voice grammar loaded from built-ins plus mutable command YAML."""

    grammar: tuple[VoiceCommandTemplate, ...]
    actions: dict[str, VoiceCommandAction]

    @classmethod
    def from_builtins(cls) -> VoiceCommandDictionary:
        """Return a dictionary containing only the built-in command grammar."""

        return cls(grammar=VOICE_COMMAND_GRAMMAR, actions={})

    def to_grammar(self) -> tuple[VoiceCommandTemplate, ...]:
        """Return parser grammar with safe action aliases appended."""

        action_templates = tuple(
            VoiceCommandTemplate(
                intent=VoiceCommandIntent.UNKNOWN,
                trigger_phrases=action.aliases,
                examples=action.aliases,
                fuzzy_threshold=0.9,
                exact_trigger_phrases=action.aliases,
            )
            for action in self.actions.values()
        )
        return self.grammar + action_templates

    def match_action(self, transcript: str) -> VoiceCommandAction | None:
        """Return an exact safe route action match for one normalized transcript."""

        normalized_transcript = _normalize_action_text(transcript)
        if not normalized_transcript:
            return None
        for action in self.actions.values():
            if any(
                _normalize_action_text(alias) == normalized_transcript for alias in action.aliases
            ):
                return action
        return None


def build_voice_command_transcription_prompt(
    dictionary: VoiceCommandDictionary,
    *,
    activation_prefixes: tuple[str, ...] = (),
    base_prompt: str = "",
    max_phrases: int = 80,
) -> str:
    """Return an STT prompt biased toward configured YoYoPod command phrases."""

    phrases = _dedupe(
        tuple(prefix for prefix in activation_prefixes if prefix.strip())
        + tuple(
            phrase
            for template in dictionary.to_grammar()
            for phrase in (*template.examples, *template.trigger_phrases)
        )
        + tuple(alias for action in dictionary.actions.values() for alias in action.aliases)
    )
    selected = ", ".join(phrases[:max_phrases])
    prompt = base_prompt.strip() or _DEFAULT_TRANSCRIPTION_PROMPT
    if selected:
        prompt = f"{prompt} Likely phrases include: {selected}."
    return prompt


def load_voice_command_dictionary(path: str | Path | None) -> VoiceCommandDictionary:
    """Load a mutable command dictionary, falling back to built-ins on invalid input."""

    if path is None:
        return VoiceCommandDictionary.from_builtins()

    dictionary_path = Path(path)
    if not dictionary_path.exists():
        return VoiceCommandDictionary.from_builtins()

    try:
        payload = yaml.safe_load(dictionary_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        logger.warning("Unable to load voice command dictionary {}: {}", dictionary_path, exc)
        return VoiceCommandDictionary.from_builtins()

    if not isinstance(payload, dict):
        logger.warning(
            "Ignoring voice command dictionary with non-mapping root: {}", dictionary_path
        )
        return VoiceCommandDictionary.from_builtins()

    return _merge_dictionary_payload(payload)


def _merge_dictionary_payload(payload: dict[Any, Any]) -> VoiceCommandDictionary:
    grammar = _merge_intent_payload(VOICE_COMMAND_GRAMMAR, payload.get("intents"))
    actions = _load_actions(payload.get("actions"))
    return VoiceCommandDictionary(grammar=grammar, actions=actions)


def _merge_intent_payload(
    grammar: tuple[VoiceCommandTemplate, ...],
    payload: Any,
) -> tuple[VoiceCommandTemplate, ...]:
    if not isinstance(payload, dict):
        return grammar

    templates_by_intent = {template.intent.value: template for template in grammar}
    disabled_intents: set[str] = set()

    for intent_name, intent_payload in payload.items():
        if not isinstance(intent_name, str) or not isinstance(intent_payload, dict):
            continue
        if intent_name not in templates_by_intent:
            logger.warning("Ignoring unknown voice command intent in dictionary: {}", intent_name)
            continue

        if intent_payload.get("enabled") is False:
            disabled_intents.add(intent_name)
            continue

        template = templates_by_intent[intent_name]
        aliases = _string_tuple(intent_payload.get("aliases"))
        examples = _string_tuple(intent_payload.get("examples"))
        fuzzy_threshold = template.fuzzy_threshold
        if "fuzzy_threshold" in intent_payload:
            try:
                candidate_threshold = float(intent_payload["fuzzy_threshold"])
            except (TypeError, ValueError):
                logger.warning(
                    "Ignoring invalid fuzzy threshold for voice command intent: {}", intent_name
                )
            else:
                if math.isfinite(candidate_threshold) and 0.0 <= candidate_threshold <= 1.0:
                    fuzzy_threshold = candidate_threshold
                else:
                    logger.warning(
                        "Ignoring invalid fuzzy threshold for voice command intent: {}",
                        intent_name,
                    )

        templates_by_intent[intent_name] = replace(
            template,
            trigger_phrases=_dedupe(template.trigger_phrases + aliases),
            examples=_dedupe(template.examples + examples),
            fuzzy_threshold=fuzzy_threshold,
        )

    return tuple(
        templates_by_intent[template.intent.value]
        for template in grammar
        if template.intent.value not in disabled_intents
    )


def _load_actions(payload: Any) -> dict[str, VoiceCommandAction]:
    if not isinstance(payload, dict):
        return {}

    actions: dict[str, VoiceCommandAction] = {}
    for action_name, action_payload in payload.items():
        if not isinstance(action_name, str) or not isinstance(action_payload, dict):
            continue

        route = action_payload.get("route")
        if not isinstance(route, str) or route not in SAFE_VOICE_ROUTE_ACTIONS:
            logger.warning("Ignoring unsafe voice route action: {}", action_name)
            continue

        aliases = _string_tuple(action_payload.get("aliases"))
        if not aliases:
            logger.warning("Ignoring voice route action without aliases: {}", action_name)
            continue

        actions[action_name] = VoiceCommandAction(name=action_name, aliases=aliases, route=route)

    return actions


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        stripped = value.strip()
        return (stripped,) if stripped else ()
    if not isinstance(value, list | tuple):
        return ()
    return tuple(stripped for item in value if isinstance(item, str) if (stripped := item.strip()))


def _dedupe(values: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(values))


def _normalize_action_text(value: str) -> str:
    return " ".join(value.strip().lower().split())


__all__ = [
    "SAFE_VOICE_ROUTE_ACTIONS",
    "VoiceCommandAction",
    "VoiceCommandDictionary",
    "build_voice_command_transcription_prompt",
    "load_voice_command_dictionary",
]
