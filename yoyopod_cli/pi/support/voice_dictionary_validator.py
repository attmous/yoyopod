"""Strict validation for mutable voice command dictionaries."""

from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
import re
from typing import Any

import yaml

from yoyopod_cli.pi.support.voice_commands import VoiceCommandIntent, match_voice_command
from yoyopod_cli.pi.support.voice_dictionary import (
    SAFE_VOICE_ROUTE_ACTIONS,
    _merge_dictionary_payload,
)

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_SHORT_PHRASE_ALLOWLIST = frozenset({"play", "louder", "quieter"})
_KNOWN_CONFIGURABLE_INTENTS = frozenset(
    intent.value for intent in VoiceCommandIntent if intent is not VoiceCommandIntent.UNKNOWN
)


@dataclass(slots=True, frozen=True)
class DictionaryValidationIssue:
    """One voice dictionary validation issue."""

    location: str
    message: str


@dataclass(slots=True, frozen=True)
class DictionaryValidationResult:
    """Strict voice dictionary validation result."""

    errors: tuple[DictionaryValidationIssue, ...]
    warnings: tuple[DictionaryValidationIssue, ...]

    @property
    def has_errors(self) -> bool:
        """Return True when validation found errors."""

        return bool(self.errors)

    @property
    def has_warnings(self) -> bool:
        """Return True when validation found warnings."""

        return bool(self.warnings)


def validate_voice_command_dictionary(
    path: str | Path,
    *,
    allow_missing: bool = False,
) -> DictionaryValidationResult:
    """Strictly validate a mutable voice command dictionary YAML file."""

    dictionary_path = Path(path)
    if not dictionary_path.exists():
        if allow_missing:
            return DictionaryValidationResult(errors=(), warnings=())
        return _result(error=("path", "dictionary file not found"))

    try:
        payload = yaml.safe_load(dictionary_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        return _result(error=("path", f"YAML parse error: {exc}"))
    except OSError as exc:
        return _result(error=("path", f"dictionary file read error: {exc}"))

    if not isinstance(payload, dict):
        return _result(error=("root", "root must be a mapping"))

    errors: list[DictionaryValidationIssue] = []
    warnings: list[DictionaryValidationIssue] = []
    example_locations: dict[tuple[str, str], str] = {}
    action_alias_locations: dict[tuple[str, str], str] = {}
    alias_locations: dict[str, str] = {}
    reported_alias_duplicates: set[str] = set()

    _validate_intents(
        payload.get("intents"),
        errors,
        warnings,
        example_locations,
        alias_locations,
        reported_alias_duplicates,
    )
    _validate_actions(
        payload.get("actions"),
        errors,
        warnings,
        action_alias_locations,
        alias_locations,
        reported_alias_duplicates,
    )

    if not errors:
        dictionary = _merge_dictionary_payload(payload)
        _validate_examples(dictionary.to_grammar(), example_locations, errors)
        _validate_action_aliases(dictionary.grammar, action_alias_locations, errors)

    return DictionaryValidationResult(errors=tuple(errors), warnings=tuple(warnings))


def _validate_intents(
    payload: Any,
    errors: list[DictionaryValidationIssue],
    warnings: list[DictionaryValidationIssue],
    example_locations: dict[tuple[str, str], str],
    alias_locations: dict[str, str],
    reported_alias_duplicates: set[str],
) -> None:
    if payload is None:
        return
    if not isinstance(payload, dict):
        errors.append(DictionaryValidationIssue("intents", "intents must be a mapping"))
        return

    for intent_name, intent_payload in payload.items():
        intent_location = f"intents.{intent_name}"
        if not isinstance(intent_name, str):
            errors.append(DictionaryValidationIssue("intents", "intent key must be a string"))
            continue
        if intent_name not in _KNOWN_CONFIGURABLE_INTENTS:
            errors.append(
                DictionaryValidationIssue(intent_location, f"unknown intent {intent_name}")
            )
            continue
        if not isinstance(intent_payload, dict):
            errors.append(
                DictionaryValidationIssue(intent_location, "intent payload must be a mapping")
            )
            continue

        aliases = _validate_phrase_field(
            intent_payload.get("aliases"),
            f"{intent_location}.aliases",
            errors,
            warnings,
        )
        for index, alias in enumerate(aliases):
            alias_location = _phrase_location(f"{intent_location}.aliases", index, aliases)
            _record_alias(alias, alias_location, alias_locations, reported_alias_duplicates, errors)

        examples = _validate_phrase_field(
            intent_payload.get("examples"),
            f"{intent_location}.examples",
            errors,
            warnings,
        )
        if intent_payload.get("enabled") is not False:
            for index, example in enumerate(examples):
                example_location = _phrase_location(f"{intent_location}.examples", index, examples)
                example_locations[(intent_name, example)] = example_location

        if "fuzzy_threshold" in intent_payload:
            _validate_threshold(
                intent_payload["fuzzy_threshold"],
                f"{intent_location}.fuzzy_threshold",
                errors,
            )


def _validate_actions(
    payload: Any,
    errors: list[DictionaryValidationIssue],
    warnings: list[DictionaryValidationIssue],
    action_alias_locations: dict[tuple[str, str], str],
    alias_locations: dict[str, str],
    reported_alias_duplicates: set[str],
) -> None:
    if payload is None:
        return
    if not isinstance(payload, dict):
        errors.append(DictionaryValidationIssue("actions", "actions must be a mapping"))
        return

    for action_name, action_payload in payload.items():
        action_location = f"actions.{action_name}"
        if not isinstance(action_name, str):
            errors.append(DictionaryValidationIssue("actions", "action key must be a string"))
            continue
        if not isinstance(action_payload, dict):
            errors.append(
                DictionaryValidationIssue(action_location, "action payload must be a mapping")
            )
            continue

        route = action_payload.get("route")
        route_location = f"{action_location}.route"
        if not isinstance(route, str):
            errors.append(DictionaryValidationIssue(route_location, "route must be a string"))
        elif route not in SAFE_VOICE_ROUTE_ACTIONS:
            errors.append(DictionaryValidationIssue(route_location, f"unsafe route {route}"))

        aliases = _validate_phrase_field(
            action_payload.get("aliases"),
            f"{action_location}.aliases",
            errors,
            warnings,
        )
        if not aliases:
            errors.append(
                DictionaryValidationIssue(
                    f"{action_location}.aliases",
                    "action must define at least one alias",
                )
            )
        for index, alias in enumerate(aliases):
            alias_location = _phrase_location(f"{action_location}.aliases", index, aliases)
            _record_alias(alias, alias_location, alias_locations, reported_alias_duplicates, errors)
            action_alias_locations[(action_name, alias)] = alias_location


def _validate_phrase_field(
    value: Any,
    location: str,
    errors: list[DictionaryValidationIssue],
    warnings: list[DictionaryValidationIssue],
) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        phrases: tuple[str, ...] = (value,)
    elif isinstance(value, list | tuple):
        phrase_items: list[str] = []
        for index, item in enumerate(value):
            if not isinstance(item, str):
                errors.append(
                    DictionaryValidationIssue(f"{location}[{index}]", "phrase must be a string")
                )
                continue
            phrase_items.append(item)
        phrases = tuple(phrase_items)
    else:
        errors.append(DictionaryValidationIssue(location, "must be a string or list of strings"))
        return ()

    stripped_phrases = tuple(phrase.strip() for phrase in phrases if phrase.strip())
    for index, phrase in enumerate(stripped_phrases):
        phrase_location = _phrase_location(location, index, stripped_phrases)
        _warn_short_phrase(phrase, phrase_location, warnings)
    return stripped_phrases


def _validate_threshold(
    value: Any,
    location: str,
    errors: list[DictionaryValidationIssue],
) -> None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        errors.append(DictionaryValidationIssue(location, "fuzzy_threshold must be numeric"))
        return
    threshold = float(value)
    if not math.isfinite(threshold) or threshold < 0.0 or threshold > 1.0:
        errors.append(
            DictionaryValidationIssue(location, "fuzzy_threshold must be between 0.0 and 1.0")
        )


def _record_alias(
    alias: str,
    location: str,
    alias_locations: dict[str, str],
    reported_alias_duplicates: set[str],
    errors: list[DictionaryValidationIssue],
) -> None:
    normalized = _normalize_phrase(alias)
    if not normalized:
        return
    existing = alias_locations.get(normalized)
    if existing is None:
        alias_locations[normalized] = location
        return

    if normalized in reported_alias_duplicates:
        return
    reported_alias_duplicates.add(normalized)
    errors.append(
        DictionaryValidationIssue(
            location,
            f"duplicate alias {normalized!r} also used by {existing}",
        )
    )


def _validate_examples(
    grammar: Any,
    example_locations: dict[tuple[str, str], str],
    errors: list[DictionaryValidationIssue],
) -> None:
    for template in grammar:
        if template.intent is VoiceCommandIntent.UNKNOWN:
            continue
        for example in template.examples:
            location = example_locations.get((template.intent.value, example))
            if location is None:
                continue
            match = match_voice_command(example, grammar=grammar)
            if match.intent is not template.intent:
                errors.append(
                    DictionaryValidationIssue(
                        location,
                        f"example matched {match.intent.value}; expected {template.intent.value}",
                    )
                )


def _validate_action_aliases(
    grammar: Any,
    action_alias_locations: dict[tuple[str, str], str],
    errors: list[DictionaryValidationIssue],
) -> None:
    for (_action_name, alias), location in action_alias_locations.items():
        match = match_voice_command(alias, grammar=grammar)
        if match.intent is VoiceCommandIntent.UNKNOWN:
            continue
        errors.append(
            DictionaryValidationIssue(
                location,
                f"action alias conflicts with command intent {match.intent.value}",
            )
        )


def _warn_short_phrase(
    phrase: str,
    location: str,
    warnings: list[DictionaryValidationIssue],
) -> None:
    normalized = _normalize_phrase(phrase)
    if normalized in _SHORT_PHRASE_ALLOWLIST:
        return
    if len(normalized.split()) == 1:
        warnings.append(
            DictionaryValidationIssue(location, f"short single-token phrase {normalized!r}")
        )


def _phrase_location(base_location: str, index: int, phrases: tuple[str, ...]) -> str:
    if len(phrases) == 1:
        return base_location
    return f"{base_location}[{index}]"


def _normalize_phrase(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(value.lower()))


def _result(
    *,
    error: tuple[str, str] | None = None,
) -> DictionaryValidationResult:
    if error is None:
        return DictionaryValidationResult(errors=(), warnings=())
    location, message = error
    return DictionaryValidationResult(
        errors=(DictionaryValidationIssue(location, message),),
        warnings=(),
    )


__all__ = [
    "DictionaryValidationIssue",
    "DictionaryValidationResult",
    "validate_voice_command_dictionary",
]
