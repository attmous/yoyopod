"""Normalize optional YoYo activation phrases from voice transcripts."""

from __future__ import annotations

from dataclasses import dataclass
import re

_TOKEN_RE = re.compile(r"[a-z0-9']+")


@dataclass(slots=True, frozen=True)
class VoiceActivationResult:
    """Normalized voice transcript plus any stripped activation prefix."""

    original_text: str
    normalized_text: str
    stripped_prefix: str = ""


class VoiceActivationNormalizer:
    """Strip optional wake-style prefixes after button-gated activation."""

    def __init__(self, *, prefixes: tuple[str, ...]) -> None:
        self._prefixes = tuple(
            normalized for prefix in prefixes if (normalized := _normalize_phrase(prefix))
        )
        self._prefix_tokens = tuple(
            (prefix, _tokenize(prefix)) for prefix in self._prefixes if _tokenize(prefix)
        )

    def normalize(self, transcript: str) -> VoiceActivationResult:
        """Return transcript text with repeated configured activation prefixes stripped."""

        original = transcript
        tokens = list(_tokenize(transcript))
        stripped_prefix = ""
        while tokens:
            matched = False
            for prefix, prefix_tokens in self._prefix_tokens:
                if _tokens_start_with(tokens, prefix_tokens):
                    stripped_prefix = stripped_prefix or prefix
                    tokens = tokens[len(prefix_tokens) :]
                    matched = True
                    break
            if not matched:
                break
        if not stripped_prefix:
            normalized_text = original.strip()
        else:
            normalized_text = " ".join(tokens)
        return VoiceActivationResult(
            original_text=original,
            normalized_text=normalized_text,
            stripped_prefix=stripped_prefix,
        )


def normalize_voice_activation(
    transcript: str,
    *,
    prefixes: tuple[str, ...],
) -> VoiceActivationResult:
    """Convenience wrapper for one-off activation normalization."""

    return VoiceActivationNormalizer(prefixes=prefixes).normalize(transcript)


def _normalize_phrase(value: str) -> str:
    return " ".join(_tokenize(value))


def _tokenize(text: str) -> tuple[str, ...]:
    tokens = list(_TOKEN_RE.findall(text.lower()))
    normalized: list[str] = []
    index = 0
    while index < len(tokens):
        if index + 1 < len(tokens) and tokens[index] == "yo" and tokens[index + 1] == "yo":
            normalized.append("yoyo")
            index += 2
            continue
        normalized.append(tokens[index])
        index += 1
    return tuple(normalized)


def _tokens_start_with(tokens: list[str], prefix_tokens: tuple[str, ...]) -> bool:
    return len(tokens) >= len(prefix_tokens) and tuple(tokens[: len(prefix_tokens)]) == prefix_tokens


__all__ = [
    "VoiceActivationNormalizer",
    "VoiceActivationResult",
    "normalize_voice_activation",
]
