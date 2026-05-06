"""Tests for strict voice command dictionary validation."""

from __future__ import annotations

from pathlib import Path

import yaml

from yoyopod.integrations.voice.dictionary_validator import (
    validate_voice_command_dictionary,
)


def _write_yaml(path: Path, payload: object) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def test_validator_accepts_matching_examples_and_safe_action(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    _write_yaml(
        commands_file,
        {
            "version": 1,
            "intents": {
                "call_contact": {
                    "aliases": ["call mama"],
                    "examples": ["call mama"],
                },
                "volume_up": {
                    "aliases": ["boost sound"],
                    "examples": ["boost sound", "louder"],
                },
            },
            "actions": {
                "open_talk": {
                    "aliases": ["open talk"],
                    "route": "open_talk",
                },
            },
        },
    )

    result = validate_voice_command_dictionary(commands_file)

    assert not result.errors
    assert result.has_errors is False


def test_validator_reports_bad_example_intent(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    _write_yaml(
        commands_file,
        {
            "intents": {
                "volume_up": {
                    "examples": ["call mama"],
                },
            },
        },
    )

    result = validate_voice_command_dictionary(commands_file)

    assert any("expected volume_up" in issue.message for issue in result.errors)


def test_validator_reports_unsafe_action_route(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    _write_yaml(
        commands_file,
        {
            "actions": {
                "shell": {
                    "aliases": ["run update"],
                    "route": "powershell",
                },
            },
        },
    )

    result = validate_voice_command_dictionary(commands_file)

    assert any("unsafe route" in issue.message for issue in result.errors)


def test_dictionary_validator_reports_action_alias_that_matches_command(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    _write_yaml(
        commands_file,
        {
            "actions": {
                "open_talk": {
                    "aliases": ["volume up"],
                    "route": "open_talk",
                },
            },
        },
    )

    result = validate_voice_command_dictionary(commands_file)

    assert any(
        "conflicts with command intent" in issue.message and "volume_up" in issue.message
        for issue in result.errors
    )


def test_dictionary_validator_reports_action_alias_that_fuzzily_matches_command(
    tmp_path: Path,
) -> None:
    commands_file = tmp_path / "commands.yaml"
    _write_yaml(
        commands_file,
        {
            "actions": {
                "open_talk": {
                    "aliases": ["increase the volume"],
                    "route": "open_talk",
                },
            },
        },
    )

    result = validate_voice_command_dictionary(commands_file)

    assert any(
        "conflicts with command intent" in issue.message and "volume_up" in issue.message
        for issue in result.errors
    )


def test_dictionary_validator_reports_action_without_aliases(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    _write_yaml(
        commands_file,
        {
            "actions": {
                "open_talk": {
                    "route": "open_talk",
                },
            },
        },
    )

    result = validate_voice_command_dictionary(commands_file)

    assert any("at least one alias" in issue.message for issue in result.errors)


def test_dictionary_validator_reports_action_with_blank_aliases(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    _write_yaml(
        commands_file,
        {
            "actions": {
                "open_talk": {
                    "aliases": ["   "],
                    "route": "open_talk",
                },
            },
        },
    )

    result = validate_voice_command_dictionary(commands_file)

    assert any("at least one alias" in issue.message for issue in result.errors)


def test_validator_reports_duplicate_alias_across_different_owners(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    _write_yaml(
        commands_file,
        {
            "intents": {
                "volume_up": {
                    "aliases": ["open talk"],
                },
            },
            "actions": {
                "open_talk": {
                    "aliases": ["open talk"],
                    "route": "open_talk",
                },
            },
        },
    )

    result = validate_voice_command_dictionary(commands_file)

    assert any("duplicate alias" in issue.message for issue in result.errors)


def test_validator_reports_duplicate_alias_within_one_intent(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    _write_yaml(
        commands_file,
        {
            "intents": {
                "volume_up": {
                    "aliases": ["boost sound", "boost sound"],
                },
            },
        },
    )

    result = validate_voice_command_dictionary(commands_file)

    assert any("duplicate alias" in issue.message for issue in result.errors)


def test_validator_reports_duplicate_alias_within_one_action(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    _write_yaml(
        commands_file,
        {
            "actions": {
                "open_talk": {
                    "aliases": ["open talk", "open talk"],
                    "route": "open_talk",
                },
            },
        },
    )

    result = validate_voice_command_dictionary(commands_file)

    assert any("duplicate alias" in issue.message for issue in result.errors)


def test_validator_reports_yaml_parse_error(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text("intents: [", encoding="utf-8")

    result = validate_voice_command_dictionary(commands_file)

    assert any("YAML parse error" in issue.message for issue in result.errors)


def test_validator_warns_for_short_alias_without_errors(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    _write_yaml(
        commands_file,
        {
            "intents": {
                "volume_up": {
                    "aliases": ["up"],
                },
            },
        },
    )

    result = validate_voice_command_dictionary(commands_file)

    assert not result.errors
    assert any("short" in issue.message for issue in result.warnings)
