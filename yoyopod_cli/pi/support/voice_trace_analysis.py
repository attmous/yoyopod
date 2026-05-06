"""Summaries for local voice trace entries."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter
from typing import Any

_FAILURE_ROUTE_KINDS = frozenset({"error", "silence", "unknown"})
_FAILURE_OUTCOME_TOKENS = ("fail", "error", "cancel", "unknown", "not_recognized", "no_match")


@dataclass(slots=True, frozen=True)
class VoiceTraceFailure:
    """One recent failed voice turn extracted for diagnostics."""

    turn_id: str
    route_kind: str
    outcome: str
    text: str


@dataclass(slots=True, frozen=True)
class VoiceTraceAnalysis:
    """Aggregate counters and failure samples for voice traces."""

    total_turns: int = 0
    route_counts: dict[str, int] = field(default_factory=dict)
    outcome_counts: dict[str, int] = field(default_factory=dict)
    command_counts: dict[str, int] = field(default_factory=dict)
    ask_fallback_turns: int = 0
    recent_failures: list[VoiceTraceFailure] = field(default_factory=list)
    unknown_phrases: dict[str, int] = field(default_factory=dict)


def analyze_voice_trace(
    entries: list[dict[str, Any]],
    *,
    failure_limit: int = 5,
) -> VoiceTraceAnalysis:
    """Return aggregate diagnostics for voice trace entries."""

    route_counts: Counter[str] = Counter()
    outcome_counts: Counter[str] = Counter()
    command_counts: Counter[str] = Counter()
    unknown_phrases: Counter[str] = Counter()
    failures: list[VoiceTraceFailure] = []
    ask_fallback_turns = 0

    for entry in entries:
        route_kind = _clean_value(entry.get("route_kind")) or "unknown"
        outcome = _clean_value(entry.get("outcome")) or "unknown"
        route_counts[route_kind] += 1
        outcome_counts[outcome] += 1

        command_intent = _clean_value(entry.get("command_intent"))
        if command_intent:
            command_counts[command_intent] += 1
        if entry.get("ask_fallback") is True:
            ask_fallback_turns += 1

        text = _trace_text(entry)
        if route_kind == "unknown" and text:
            unknown_phrases[text] += 1
        if _is_failure(route_kind=route_kind, outcome=outcome):
            failures.append(
                VoiceTraceFailure(
                    turn_id=_clean_value(entry.get("turn_id")) or "",
                    route_kind=route_kind,
                    outcome=outcome,
                    text=text,
                )
            )

    return VoiceTraceAnalysis(
        total_turns=len(entries),
        route_counts=_sorted_counts(route_counts),
        outcome_counts=_sorted_counts(outcome_counts),
        command_counts=_sorted_counts(command_counts),
        ask_fallback_turns=ask_fallback_turns,
        recent_failures=failures[-max(0, failure_limit) :] if failure_limit > 0 else [],
        unknown_phrases=_sorted_counts(unknown_phrases),
    )


def _clean_value(value: object) -> str:
    return " ".join(str(value or "").split())


def _trace_text(entry: dict[str, Any]) -> str:
    return (
        _clean_value(entry.get("transcript_normalized"))
        or _clean_value(entry.get("transcript_raw"))
        or _clean_value(entry.get("assistant_body_preview"))
    )


def _is_failure(*, route_kind: str, outcome: str) -> bool:
    if route_kind in _FAILURE_ROUTE_KINDS:
        return True
    lowered = outcome.lower()
    return any(token in lowered for token in _FAILURE_OUTCOME_TOKENS)


def _sorted_counts(counter: Counter[str]) -> dict[str, int]:
    return {key: counter[key] for key in sorted(counter)}


__all__ = [
    "VoiceTraceAnalysis",
    "VoiceTraceFailure",
    "analyze_voice_trace",
]
