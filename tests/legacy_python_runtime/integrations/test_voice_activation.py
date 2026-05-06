"""Tests for YoYo voice activation prefix normalization."""

from __future__ import annotations

import pytest

from yoyopod.integrations.voice.activation import (
    VoiceActivationNormalizer,
    normalize_voice_activation,
)
from yoyopod.integrations.voice import VoiceActivationNormalizer as RootVoiceActivationNormalizer


@pytest.mark.parametrize(
    ("transcript", "expected_text", "expected_prefix"),
    [
        ("hey yoyo call mama", "call mama", "hey yoyo"),
        ("yoyo make it louder", "make it louder", "yoyo"),
        ("Hey, YoYo, why is the sky blue?", "why is the sky blue", "hey yoyo"),
        ("yo yo play music", "play music", "yoyo"),
        ("hey yoyo hey yoyo call mom", "call mom", "hey yoyo"),
        ("please call mom", "please call mom", ""),
    ],
)
def test_normalize_voice_activation_strips_configured_prefixes(
    transcript: str,
    expected_text: str,
    expected_prefix: str,
) -> None:
    result = normalize_voice_activation(transcript, prefixes=("hey yoyo", "yoyo"))

    assert result.original_text == transcript
    assert result.normalized_text == expected_text
    assert result.stripped_prefix == expected_prefix


def test_activation_normalizer_uses_settings_prefix_order() -> None:
    normalizer = VoiceActivationNormalizer(prefixes=("hey yoyo", "yoyo", "computer"))

    result = normalizer.normalize("computer open talk")

    assert result.normalized_text == "open talk"
    assert result.stripped_prefix == "computer"


def test_activation_normalizer_preserves_empty_and_whitespace_text() -> None:
    result = normalize_voice_activation("   ", prefixes=("hey yoyo", "yoyo"))

    assert result.normalized_text == ""
    assert result.stripped_prefix == ""


@pytest.mark.parametrize(
    "transcript",
    [
        "Please, call Mom!",
        "turn on Yo Yo mode",
    ],
)
def test_activation_normalizer_preserves_no_prefix_transcript_formatting(
    transcript: str,
) -> None:
    result = normalize_voice_activation(transcript, prefixes=("hey yoyo", "yoyo"))

    assert result.normalized_text == transcript.strip()
    assert result.stripped_prefix == ""


def test_voice_activation_normalizer_is_exported_from_voice_package_root() -> None:
    normalizer = RootVoiceActivationNormalizer(prefixes=("hey yoyo", "yoyo"))

    result = normalizer.normalize("yoyo play")

    assert result.normalized_text == "play"
    assert result.stripped_prefix == "yoyo"
