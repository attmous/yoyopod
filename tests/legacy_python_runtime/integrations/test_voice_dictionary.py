"""Tests for mutable voice command dictionary loading."""

from __future__ import annotations

from pathlib import Path

import yaml

from yoyopod.integrations.voice.commands import VoiceCommandIntent, match_voice_command
from yoyopod.integrations.voice.dictionary import (
    SAFE_VOICE_ROUTE_ACTIONS,
    VoiceCommandDictionary,
    build_voice_command_transcription_prompt,
    load_voice_command_dictionary,
)


def test_dictionary_defaults_include_builtin_voice_commands() -> None:
    dictionary = VoiceCommandDictionary.from_builtins()

    grammar = dictionary.to_grammar()

    assert (
        match_voice_command("call mom", grammar=grammar).intent is VoiceCommandIntent.CALL_CONTACT
    )
    assert (
        match_voice_command("play music", grammar=grammar).intent is VoiceCommandIntent.PLAY_MUSIC
    )


def test_dictionary_adds_aliases_from_mutable_yaml(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "intents": {
                    "volume_up": {
                        "aliases": ["boost sound"],
                        "examples": ["boost sound"],
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    dictionary = load_voice_command_dictionary(commands_file)

    assert (
        match_voice_command("boost sound", grammar=dictionary.to_grammar()).intent
        is VoiceCommandIntent.VOLUME_UP
    )


def test_dictionary_transcription_prompt_includes_mutable_yaml_phrases(
    tmp_path: Path,
) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "intents": {
                    "volume_up": {
                        "aliases": ["boost sound"],
                        "examples": ["boost sound"],
                    }
                },
                "actions": {
                    "open_talk": {
                        "aliases": ["open talk"],
                        "route": "open_talk",
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    dictionary = load_voice_command_dictionary(commands_file)

    prompt = build_voice_command_transcription_prompt(
        dictionary,
        activation_prefixes=("yoyo", "hey yoyo"),
    )

    assert "English Latin letters" in prompt
    assert "boost sound" in prompt
    assert "open talk" in prompt
    assert "hey yoyo" in prompt


def test_dictionary_can_disable_mutable_intent(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "intents": {
                    "play_music": {
                        "enabled": False,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    dictionary = load_voice_command_dictionary(commands_file)

    assert (
        match_voice_command("play music", grammar=dictionary.to_grammar()).intent
        is VoiceCommandIntent.UNKNOWN
    )


def test_dictionary_rejects_unsafe_actions(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "actions": {
                    "open_talk": {
                        "aliases": ["open talk"],
                        "route": "open_talk",
                    },
                    "shell": {
                        "aliases": ["run update"],
                        "route": "powershell",
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    dictionary = load_voice_command_dictionary(commands_file)

    assert dictionary.actions["open_talk"].route == "open_talk"
    assert "shell" not in dictionary.actions
    assert "open_talk" in SAFE_VOICE_ROUTE_ACTIONS


def test_dictionary_matches_safe_action_alias_exactly(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "actions": {
                    "open_talk": {
                        "aliases": ["Open Talk"],
                        "route": "open_talk",
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    dictionary = load_voice_command_dictionary(commands_file)

    assert dictionary.match_action("  open   talk  ") == dictionary.actions["open_talk"]
    assert dictionary.match_action("open talk now") is None


def test_dictionary_rejects_negative_fuzzy_threshold(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "intents": {
                    "volume_up": {
                        "fuzzy_threshold": -1,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    dictionary = load_voice_command_dictionary(commands_file)
    grammar = dictionary.to_grammar()

    assert (
        match_voice_command("what is the weather", grammar=grammar).intent
        is VoiceCommandIntent.UNKNOWN
    )
    assert match_voice_command("volume up", grammar=grammar).intent is VoiceCommandIntent.VOLUME_UP


def test_dictionary_rejects_out_of_range_fuzzy_threshold(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "intents": {
                    "volume_up": {
                        "fuzzy_threshold": 1.1,
                    }
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    dictionary = load_voice_command_dictionary(commands_file)

    assert (
        match_voice_command("volume up", grammar=dictionary.to_grammar()).intent
        is VoiceCommandIntent.VOLUME_UP
    )


def test_dictionary_ignores_actions_with_blank_aliases(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "version": 1,
                "actions": {
                    "open_talk": {
                        "aliases": ["   "],
                        "route": "open_talk",
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    dictionary = load_voice_command_dictionary(commands_file)

    assert dictionary.actions == {}


def test_dictionary_invalid_yaml_uses_builtins(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text("intents: [", encoding="utf-8")

    dictionary = load_voice_command_dictionary(commands_file)

    assert (
        match_voice_command("volume up", grammar=dictionary.to_grammar()).intent
        is VoiceCommandIntent.VOLUME_UP
    )
