"""Deterministic parsing and fuzzy grammar templates for local voice commands."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import StrEnum
import re

_TOKEN_RE = re.compile(r"[a-z0-9']+")
_LATIN_COMMAND_TOKEN_RE = re.compile(r"[A-Za-z0-9']+")
_SCRIPT_COMMAND_TOKEN_RE = re.compile(r"[\u0600-\u06ff]+")
_HANGUL_COMMAND_TOKEN_RE = re.compile(r"[\uac00-\ud7af]+")
_CJK_COMMAND_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]+")
_STT_COMMAND_TOKEN_ALIASES = {
    "kual": "call",
}
_HANGUL_COMMAND_ALIASES = {
    "\uace0": "call",
    "\ucf5c": "call",
    "\ub9c8\ub9c8": "mama",
}
_CJK_COMMAND_ALIASES = {
    "\u63a8": "play",
    "\u97f3\u4e50": "music",
}
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
_NEGATION_TOKENS = frozenset(
    {"no", "not", "never", "dont", "don't", "cant", "can't", "cannot", "wont", "won't", "n't"}
)
_NEGATION_TOKEN_SEQUENCES = (
    ("can", "t"),
    ("do", "nt"),
    ("do", "n", "t"),
    ("don", "t"),
    ("won", "t"),
)
_EXACT_TRIGGER_SUFFIX_TOKENS = frozenset({"please", "now"})
_SCRIPT_COMMAND_ALIASES = {
    "\u06a9\u0648": "call",
    "\u0643\u0648": "call",
    "\u06a9\u0648\u0644": "call",
    "\u0643\u0648\u0644": "call",
    "\u0645\u0627\u0645\u0627": "mama",
    "\u0648\u0648\u0644\u06cc\u0648\u0645": "volume",
    "\u0648\u0648\u0644\u064a\u0648\u0645": "volume",
    "\u0648\u0644\u06cc\u0648\u0645": "volume",
    "\u0648\u0644\u064a\u0648\u0645": "volume",
    "\u0648\u0627\u0644\u06cc\u0648\u0645": "volume",
    "\u0648\u0627\u0644\u064a\u0648\u0645": "volume",
    "\u0627\u067e": "up",
    "\u0622\u067e": "up",
    "\u062f\u0627\u0648\u0646": "down",
    "\u062f\u0627\u0646": "down",
    "\u067e\u0644\u06cc": "play",
    "\u067e\u0644\u064a": "play",
    "\u0645\u0648\u0632\u06cc\u06a9": "music",
    "\u0645\u0648\u0632\u064a\u0643": "music",
    "\u0645\u06cc\u0648\u0632\u06cc\u06a9": "music",
    "\u0645\u064a\u0648\u0632\u064a\u0643": "music",
}
_SCRIPT_CHAR_TRANSLATION = str.maketrans(
    {
        "\u064a": "\u06cc",
        "\u0643": "\u06a9",
        "\u0622": "\u0627",
    }
)


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
    exact_trigger_phrases: tuple[str, ...] = ()


VOICE_COMMAND_GRAMMAR: tuple[VoiceCommandTemplate, ...] = (
    VoiceCommandTemplate(
        intent=VoiceCommandIntent.CALL_CONTACT,
        trigger_phrases=("call", "phone", "ring"),
        examples=(
            "call mom",
            "call dad",
            "please call mama",
            "call mama",
            "call my mama",
            "call mommy",
            "please call my mom",
            "ring mama",
            "phone mom",
            "call daddy",
            "call papa",
            "ring papa",
        ),
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
            "louder",
            "make it louder",
            "too quiet",
        ),
        examples=("volume up", "turn it up", "please raise volume", "louder"),
        exact_trigger_phrases=("louder",),
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
            "quieter",
            "make it quieter",
            "too loud",
        ),
        examples=("volume down", "turn it down", "quieter"),
        exact_trigger_phrases=("quieter",),
        fuzzy_threshold=0.78,
    ),
    VoiceCommandTemplate(
        intent=VoiceCommandIntent.PLAY_MUSIC,
        trigger_phrases=(
            "play music",
            "play",
            "play some music",
            "start music",
            "start some music",
            "start playing music",
            "shuffle music",
            "play a song",
            "play songs",
            "put on music",
            "start songs",
            "play kids music",
        ),
        examples=("play music", "play some music", "start music", "play a song"),
        exact_trigger_phrases=(
            "play",
            "play a song",
            "play songs",
            "put on music",
            "start songs",
            "play kids music",
        ),
        fuzzy_threshold=0.78,
    ),
    VoiceCommandTemplate(
        intent=VoiceCommandIntent.READ_SCREEN,
        trigger_phrases=(
            "read screen",
            "read the screen",
            "read this screen",
            "read this",
            "what is on the screen",
            "tell me what is on the screen",
        ),
        examples=("read screen", "read the screen", "read this"),
        exact_trigger_phrases=(
            "read screen",
            "read the screen",
            "read this screen",
            "read this",
            "what is on the screen",
            "tell me what is on the screen",
        ),
        fuzzy_threshold=0.8,
    ),
    VoiceCommandTemplate(
        intent=VoiceCommandIntent.UNMUTE_MIC,
        trigger_phrases=(
            "unmute mic",
            "unmute microphone",
            "unmute the mic",
            "unmute the microphone",
            "turn on the mic",
            "turn on microphone",
            "turn on the microphone",
        ),
        examples=("unmute mic", "unmute microphone", "turn on the mic"),
        exact_trigger_phrases=(
            "unmute mic",
            "unmute microphone",
            "unmute the mic",
            "unmute the microphone",
            "turn on the mic",
            "turn on microphone",
            "turn on the microphone",
        ),
        fuzzy_threshold=0.84,
    ),
    VoiceCommandTemplate(
        intent=VoiceCommandIntent.MUTE_MIC,
        trigger_phrases=(
            "mute mic",
            "mute microphone",
            "mute the mic",
            "mute the microphone",
            "turn off the mic",
            "turn off microphone",
            "turn off the microphone",
        ),
        examples=("mute mic", "mute microphone", "turn off the mic"),
        exact_trigger_phrases=(
            "mute mic",
            "mute microphone",
            "mute the mic",
            "mute the microphone",
            "turn off the mic",
            "turn off microphone",
            "turn off the microphone",
        ),
        fuzzy_threshold=0.84,
    ),
)


def match_voice_command(
    transcript: str,
    *,
    grammar: tuple[VoiceCommandTemplate, ...] | None = None,
) -> VoiceCommandMatch:
    """Map a transcript to the first supported local voice command."""

    effective_grammar = VOICE_COMMAND_GRAMMAR if grammar is None else grammar
    normalized_transcript = _expand_script_command_aliases(transcript)
    transcript_tokens = _tokenize(normalized_transcript)
    if _has_negation(transcript_tokens):
        return VoiceCommandMatch(VoiceCommandIntent.UNKNOWN, transcript=transcript)

    tokens = _strip_polite_prefix(transcript_tokens)
    if not tokens:
        return VoiceCommandMatch(VoiceCommandIntent.UNKNOWN, transcript=transcript)

    slot_match = _match_slot_command(tokens, transcript, grammar=effective_grammar)
    if slot_match is not None:
        return slot_match

    fixed_match = _match_fixed_command(tokens, transcript, grammar=effective_grammar)
    if fixed_match is not None:
        return fixed_match

    return VoiceCommandMatch(VoiceCommandIntent.UNKNOWN, transcript=transcript)


def _expand_script_command_aliases(transcript: str) -> str:
    """Expand common cloud-STT script transliterations into command words."""

    normalized = transcript.translate(_SCRIPT_CHAR_TRANSLATION)

    def replace_script_token(match: re.Match[str]) -> str:
        token = match.group(0)
        replacement = _SCRIPT_COMMAND_ALIASES.get(token)
        if replacement is None:
            return token
        return f" {replacement} "

    def replace_hangul_token(match: re.Match[str]) -> str:
        token = match.group(0)
        replacement = _HANGUL_COMMAND_ALIASES.get(token)
        if replacement is None:
            return token
        return f" {replacement} "

    def replace_cjk_token(match: re.Match[str]) -> str:
        token = match.group(0)
        replacement = _CJK_COMMAND_ALIASES.get(token)
        if replacement is None:
            return token
        return f" {replacement} "

    def replace_latin_token(match: re.Match[str]) -> str:
        token = match.group(0)
        replacement = _STT_COMMAND_TOKEN_ALIASES.get(token.lower())
        if replacement is None:
            return token
        return replacement

    normalized = _SCRIPT_COMMAND_TOKEN_RE.sub(replace_script_token, normalized)
    normalized = _HANGUL_COMMAND_TOKEN_RE.sub(replace_hangul_token, normalized)
    normalized = _CJK_COMMAND_TOKEN_RE.sub(replace_cjk_token, normalized)
    return _LATIN_COMMAND_TOKEN_RE.sub(replace_latin_token, normalized)


def _match_slot_command(
    tokens: tuple[str, ...],
    transcript: str,
    *,
    grammar: tuple[VoiceCommandTemplate, ...],
) -> VoiceCommandMatch | None:
    """Return the best slot-bearing command match for the given tokens."""

    best_score = 0.0
    best_match: VoiceCommandMatch | None = None
    for template in grammar:
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
                if _has_negation_before_window(tokens, start):
                    continue
                raw_slot_tokens = tokens[start + len(phrase_tokens) :]
                if _has_negation(raw_slot_tokens):
                    continue
                slot_tokens = _trim_slot_tokens(raw_slot_tokens)
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


def _match_fixed_command(
    tokens: tuple[str, ...],
    transcript: str,
    *,
    grammar: tuple[VoiceCommandTemplate, ...],
) -> VoiceCommandMatch | None:
    """Return the best fixed-phrase command match for the given tokens."""

    best_score = 0.0
    best_intent: VoiceCommandIntent | None = None
    for template in grammar:
        if template.slot_name is not None:
            continue
        for phrase in template.trigger_phrases:
            phrase_tokens = _tokenize(phrase)
            if not phrase_tokens:
                continue
            exact_phrase = phrase in template.exact_trigger_phrases
            if exact_phrase and not _matches_exact_trigger(tokens, phrase_tokens):
                continue
            if exact_phrase:
                score = 1.0
            else:
                score, start, end = _best_window_match(tokens, phrase_tokens)
                if _has_negation_before_window(tokens, start) or _has_negation(tokens[start:end]):
                    continue
            if score >= template.fuzzy_threshold and score > best_score:
                best_score = score
                best_intent = template.intent
    if best_intent is None:
        return None
    return VoiceCommandMatch(best_intent, transcript=transcript)


def _best_window_match(
    tokens: tuple[str, ...], phrase_tokens: tuple[str, ...]
) -> tuple[float, int, int]:
    """Return the best score and window span for one transcript and phrase."""

    best_score = 0.0
    best_start = 0
    best_end = 0
    if len(tokens) <= len(phrase_tokens) + 2:
        window_sizes = range(max(1, len(phrase_tokens) - 1), len(tokens) + 1)
    else:
        window_sizes = range(max(1, len(phrase_tokens) - 1), len(phrase_tokens) + 3)
    for window_size in window_sizes:
        for start in range(len(tokens) - window_size + 1):
            end = start + window_size
            window = tokens[start : start + window_size]
            score = 1.0 if window == phrase_tokens else _phrase_similarity(window, phrase_tokens)
            if score > best_score:
                best_score = score
                best_start = start
                best_end = end
    return best_score, best_start, best_end


def _has_negation_before_window(tokens: tuple[str, ...], start: int) -> bool:
    """Return True when a command window is preceded by negation."""

    return _has_negation(tokens[:start])


def _has_negation(tokens: tuple[str, ...]) -> bool:
    """Return True when any token is a negation token."""

    if any(token in _NEGATION_TOKENS for token in tokens):
        return True
    return any(_contains_token_sequence(tokens, sequence) for sequence in _NEGATION_TOKEN_SEQUENCES)


def _contains_token_sequence(tokens: tuple[str, ...], sequence: tuple[str, ...]) -> bool:
    """Return True when tokens contain a contiguous token sequence."""

    if len(tokens) < len(sequence):
        return False
    return any(tokens[index : index + len(sequence)] == sequence for index in range(len(tokens)))


def _matches_exact_trigger(tokens: tuple[str, ...], phrase_tokens: tuple[str, ...]) -> bool:
    """Return True when tokens match an exact trigger plus harmless polite suffixes."""

    end = len(tokens)
    while end > 0 and tokens[end - 1] in _EXACT_TRIGGER_SUFFIX_TOKENS:
        end -= 1
    return tokens[:end] == phrase_tokens


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
