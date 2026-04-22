"""Deterministic parsing and fuzzy grammar templates for local voice commands."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
import re

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_POLITE_PREFIX_TOKENS = frozenset(
    {
        "please",
        "hey",
        "hi",
        "hello",
        "yo",
        "can",
        "could",
        "would",
        "will",
        "you",
    }
)
_SLOT_FILLER_TOKENS = frozenset({"a", "an", "the", "to", "for", "my", "please", "now"})


class VoiceCommandIntent(StrEnum):
    """Supported first-pass local voice intents."""

    CALL_CONTACT = "call_contact"
    PLAY_MUSIC = "play_music"
    READ_SCREEN = "read_screen"
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    MUTE_MIC = "mute_mic"
    UNMUTE_MIC = "unmute_mic"
    UNKNOWN = "unknown"


@dataclass(slots=True, frozen=True)
class VoiceCommandMatch:
    """Structured result from matching a transcript to a local intent."""

    intent: VoiceCommandIntent
    transcript: str
    contact_name: str = ""

    @property
    def is_command(self) -> bool:
        """Return True when the transcript mapped to a known command."""

        return self.intent is not VoiceCommandIntent.UNKNOWN


@dataclass(slots=True, frozen=True)
class VoiceCommandTemplate:
    """Declarative grammar template for one command intent."""

    intent: VoiceCommandIntent
    trigger_phrases: tuple[str, ...]
    examples: tuple[str, ...]
    slot_name: str | None = None
    fuzzy_threshold: float = 0.82


VOICE_COMMAND_GRAMMAR: tuple[VoiceCommandTemplate, ...] = (
    VoiceCommandTemplate(
        intent=VoiceCommandIntent.CALL_CONTACT,
        trigger_phrases=("call", "phone", "ring"),
        examples=("call mom", "call dad", "please call mama"),
        slot_name="contact_name",
        fuzzy_threshold=0.86,
    ),
    VoiceCommandTemplate(
        intent=VoiceCommandIntent.VOLUME_UP,
        trigger_phrases=(
            "volume up",
            "turn volume up",
            "turn it up",
            "raise volume",
            "increase volume",
        ),
        examples=("volume up", "turn it up", "please raise volume"),
        fuzzy_threshold=0.78,
    ),
    VoiceCommandTemplate(
        intent=VoiceCommandIntent.VOLUME_DOWN,
        trigger_phrases=(
            "volume down",
            "turn volume down",
            "turn it down",
            "lower volume",
            "decrease volume",
        ),
        examples=("volume down", "turn it down"),
        fuzzy_threshold=0.78,
    ),
    VoiceCommandTemplate(
        intent=VoiceCommandIntent.PLAY_MUSIC,
        trigger_phrases=(
            "play music",
            "play some music",
            "start music",
            "start some music",
            "start playing music",
            "shuffle music",
        ),
        examples=("play music", "play some music", "start music"),
        fuzzy_threshold=0.78,
    ),
    VoiceCommandTemplate(
        intent=VoiceCommandIntent.READ_SCREEN,
        trigger_phrases=("read screen", "read the screen", "read this screen"),
        examples=("read screen", "read the screen"),
        fuzzy_threshold=0.8,
    ),
    VoiceCommandTemplate(
        intent=VoiceCommandIntent.UNMUTE_MIC,
        trigger_phrases=("unmute mic", "unmute microphone"),
        examples=("unmute mic", "unmute microphone"),
        fuzzy_threshold=0.84,
    ),
    VoiceCommandTemplate(
        intent=VoiceCommandIntent.MUTE_MIC,
        trigger_phrases=("mute mic", "mute microphone"),
        examples=("mute mic", "mute microphone"),
        fuzzy_threshold=0.84,
    ),
)


def match_voice_command(transcript: str) -> VoiceCommandMatch:
    """Map a transcript to the first supported local voice command."""

    tokens = _strip_polite_prefix(_tokenize(transcript))
    if not tokens:
        return VoiceCommandMatch(VoiceCommandIntent.UNKNOWN, transcript=transcript)

    slot_match = _match_slot_command(tokens, transcript)
    if slot_match is not None:
        return slot_match

    fixed_match = _match_fixed_command(tokens, transcript)
    if fixed_match is not None:
        return fixed_match

    return VoiceCommandMatch(VoiceCommandIntent.UNKNOWN, transcript=transcript)


def _match_slot_command(tokens: tuple[str, ...], transcript: str) -> VoiceCommandMatch | None:
    """Return the best slot-bearing command match for the given tokens."""

    best_score = 0.0
    best_match: VoiceCommandMatch | None = None
    for template in VOICE_COMMAND_GRAMMAR:
        if template.slot_name is None:
            continue
        for phrase in template.trigger_phrases:
            phrase_tokens = _tokenize(phrase)
            if not phrase_tokens:
                continue
            max_start = len(tokens) - len(phrase_tokens)
            for start in range(max_start + 1):
                window = tokens[start : start + len(phrase_tokens)]
                score = (
                    1.0 if window == phrase_tokens else _phrase_similarity(window, phrase_tokens)
                )
                if score < template.fuzzy_threshold:
                    continue
                slot_tokens = _trim_slot_tokens(tokens[start + len(phrase_tokens) :])
                if not slot_tokens:
                    continue
                if score > best_score:
                    best_score = score
                    best_match = VoiceCommandMatch(
                        template.intent,
                        transcript=transcript,
                        contact_name=" ".join(slot_tokens),
                    )
    return best_match


def _match_fixed_command(tokens: tuple[str, ...], transcript: str) -> VoiceCommandMatch | None:
    """Return the best fixed-phrase command match for the given tokens."""

    best_score = 0.0
    best_intent: VoiceCommandIntent | None = None
    for template in VOICE_COMMAND_GRAMMAR:
        if template.slot_name is not None:
            continue
        for phrase in template.trigger_phrases:
            phrase_tokens = _tokenize(phrase)
            if not phrase_tokens:
                continue
            score = _best_window_score(tokens, phrase_tokens)
            if score >= template.fuzzy_threshold and score > best_score:
                best_score = score
                best_intent = template.intent
    if best_intent is None:
        return None
    return VoiceCommandMatch(best_intent, transcript=transcript)


def _best_window_score(tokens: tuple[str, ...], phrase_tokens: tuple[str, ...]) -> float:
    """Return the best score between one transcript and one grammar phrase."""

    best_score = 0.0
    if len(tokens) <= len(phrase_tokens) + 2:
        window_sizes = range(max(1, len(phrase_tokens) - 1), len(tokens) + 1)
    else:
        window_sizes = range(max(1, len(phrase_tokens) - 1), len(phrase_tokens) + 3)
    for window_size in window_sizes:
        for start in range(len(tokens) - window_size + 1):
            window = tokens[start : start + window_size]
            score = 1.0 if window == phrase_tokens else _phrase_similarity(window, phrase_tokens)
            if score > best_score:
                best_score = score
    return best_score


def _phrase_similarity(candidate_tokens: tuple[str, ...], phrase_tokens: tuple[str, ...]) -> float:
    """Return a fuzzy similarity score between two token sequences."""

    candidate = " ".join(candidate_tokens)
    phrase = " ".join(phrase_tokens)
    text_ratio = SequenceMatcher(None, candidate, phrase).ratio()
    overlap = _token_overlap(candidate_tokens, phrase_tokens)
    return max(text_ratio, overlap)


def _token_overlap(candidate_tokens: tuple[str, ...], phrase_tokens: tuple[str, ...]) -> float:
    """Return a simple symmetric token-overlap score."""

    candidate_set = set(candidate_tokens)
    phrase_set = set(phrase_tokens)
    if not candidate_set or not phrase_set:
        return 0.0
    return (2.0 * len(candidate_set & phrase_set)) / (len(candidate_set) + len(phrase_set))


def _trim_slot_tokens(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """Trim filler tokens around a slot extracted from the transcript."""

    start = 0
    end = len(tokens)
    while start < end and tokens[start] in _SLOT_FILLER_TOKENS:
        start += 1
    while end > start and tokens[end - 1] in _SLOT_FILLER_TOKENS:
        end -= 1
    return tokens[start:end]


def _strip_polite_prefix(tokens: tuple[str, ...]) -> tuple[str, ...]:
    """Drop leading politeness words before command matching."""

    start = 0
    while start < len(tokens) and tokens[start] in _POLITE_PREFIX_TOKENS:
        start += 1
    return tokens[start:]


def _tokenize(text: str) -> tuple[str, ...]:
    """Split one transcript into normalized lowercase tokens."""

    return tuple(_TOKEN_RE.findall(text.lower()))


__all__ = [
    "VOICE_COMMAND_GRAMMAR",
    "VoiceCommandIntent",
    "VoiceCommandMatch",
    "VoiceCommandTemplate",
    "match_voice_command",
]
