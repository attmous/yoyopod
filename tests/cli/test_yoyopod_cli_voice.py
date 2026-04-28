"""Tests for the yoyopod voice diagnostics CLI."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pytest import MonkeyPatch
from typer.testing import CliRunner

from yoyopod.integrations.voice.trace import VoiceTraceEntry, VoiceTraceStore
from yoyopod_cli.main import app


runner = CliRunner()


def _entry(turn_id: str, transcript: str) -> VoiceTraceEntry:
    return VoiceTraceEntry(
        turn_id=turn_id,
        started_at="2026-04-27T12:00:00.000Z",
        completed_at="2026-04-27T12:00:01.000Z",
        source="ptt",
        mode="cloud",
        route_kind="command",
        outcome="handled",
        command_intent="ask",
        transcript_raw=transcript,
        transcript_normalized=transcript,
    )


def test_voice_group_is_registered() -> None:
    result = runner.invoke(app, ["voice", "--help"])

    assert result.exit_code == 0
    assert "trace" in result.output


def test_voice_trace_last_prints_recent_rows(tmp_path: Path) -> None:
    trace_path = tmp_path / "turns.jsonl"
    store = VoiceTraceStore(path=trace_path, max_turns=5)
    store.append(_entry("turn-1", "play music"))
    store.append(_entry("turn-2", "why is the sky blue"))

    result = runner.invoke(
        app,
        ["voice", "trace", "last", "--limit", "1", "--path", str(trace_path)],
    )

    assert result.exit_code == 0
    assert "turn-2" in result.output
    assert "why is the sky blue" in result.output
    assert "turn-1" not in result.output


def test_voice_trace_last_uses_configured_default_path(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    trace_path = tmp_path / "configured-turns.jsonl"
    store = VoiceTraceStore(path=trace_path, max_turns=5)
    store.append(_entry("turn-configured", "call mama"))
    monkeypatch.setenv("YOYOPOD_VOICE_TRACE_PATH", str(trace_path))

    result = runner.invoke(app, ["voice", "trace", "last", "--limit", "1"])

    assert result.exit_code == 0
    assert "turn-configured" in result.output
    assert "call mama" in result.output


def test_voice_trace_last_tolerates_missing_file(tmp_path: Path) -> None:
    trace_path = tmp_path / "missing.jsonl"

    result = runner.invoke(app, ["voice", "trace", "last", "--path", str(trace_path)])

    assert result.exit_code == 0
    assert "No voice trace entries" in result.output


def test_voice_trace_last_ignores_corrupt_lines(tmp_path: Path) -> None:
    trace_path = tmp_path / "turns.jsonl"
    trace_path.write_text(
        "\n".join(
            [
                "not-json",
                json.dumps(_entry("turn-1", "play music").to_json_dict()),
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["voice", "trace", "last", "--path", str(trace_path)])

    assert result.exit_code == 0
    assert "turn-1" in result.output
    assert "not-json" not in result.output


def test_voice_dictionary_validate_accepts_valid_file(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "intents": {
                    "volume_up": {
                        "aliases": ["boost sound"],
                        "examples": ["boost sound"],
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["voice", "dictionary", "validate", "--path", str(commands_file)],
    )

    assert result.exit_code == 0
    assert "OK voice dictionary" in result.output


def test_voice_dictionary_validate_uses_configured_default_path(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "intents": {
                    "volume_up": {
                        "aliases": ["boost sound"],
                        "examples": ["boost sound"],
                    }
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("YOYOPOD_VOICE_COMMAND_DICTIONARY", str(commands_file))

    result = runner.invoke(app, ["voice", "dictionary", "validate"])

    assert result.exit_code == 0
    assert str(commands_file) in result.output
    assert "built-ins only" not in result.output


def test_voice_dictionary_validate_fails_on_errors(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "actions": {
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

    result = runner.invoke(
        app,
        ["voice", "dictionary", "validate", "--path", str(commands_file)],
    )

    assert result.exit_code == 1
    assert "unsafe route" in result.output


def test_voice_dictionary_validate_strict_fails_on_warnings(tmp_path: Path) -> None:
    commands_file = tmp_path / "commands.yaml"
    commands_file.write_text(
        yaml.safe_dump(
            {
                "intents": {
                    "volume_up": {
                        "aliases": ["up"],
                    },
                },
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["voice", "dictionary", "validate", "--path", str(commands_file), "--strict"],
    )

    assert result.exit_code == 1
    assert "WARN" in result.output


def test_voice_dictionary_validate_default_missing_uses_builtins(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("YOYOPOD_VOICE_COMMAND_DICTIONARY", raising=False)

    result = runner.invoke(app, ["voice", "dictionary", "validate"])

    assert result.exit_code == 0
    assert "built-ins only" in result.output
