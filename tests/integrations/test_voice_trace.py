"""Tests for bounded voice turn tracing."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from yoyopod.integrations.voice.trace import (
    DEFAULT_VOICE_TRACE_PATH,
    VoiceTraceEntry,
    VoiceTraceStore,
    new_turn_id,
    utc_now_iso,
)


def _entry(turn_id: str, transcript: str = "play music") -> VoiceTraceEntry:
    return VoiceTraceEntry(
        turn_id=turn_id,
        started_at="2026-04-27T12:00:00.000Z",
        completed_at="2026-04-27T12:00:01.000Z",
        source="ptt",
        mode="cloud",
        route_kind="command",
        outcome="handled",
        transcript_raw=transcript,
        transcript_normalized=transcript.lower(),
        assistant_body_preview="Starting local music now",
    )


def test_voice_trace_entry_json_caps_text_and_uses_schema_version() -> None:
    entry = VoiceTraceEntry(
        turn_id="turn-1",
        started_at="2026-04-27T12:00:00.000Z",
        completed_at="2026-04-27T12:00:01.000Z",
        source="ptt",
        mode="cloud",
        route_kind="command",
        outcome="handled",
        transcript_raw="  one\n two   three four  ",
        transcript_normalized="ONE   TWO THREE FOUR",
        assistant_body_preview="alpha beta gamma",
        text_limit=12,
        body_preview_chars=10,
    )

    payload = entry.to_json_dict()

    assert payload["schema_version"] == 1
    assert payload["transcript_raw"] == "one two t..."
    assert payload["transcript_normalized"] == "ONE TWO T..."
    assert payload["assistant_body_preview"] == "alpha b..."
    assert "timings_ms" not in payload
    assert "error" not in payload


def test_voice_trace_entry_omits_transcripts_when_disabled() -> None:
    entry = _entry("turn-1")
    entry.include_transcripts = False

    payload = entry.to_json_dict()

    assert "transcript_raw" not in payload
    assert "transcript_normalized" not in payload
    assert payload["assistant_body_preview"] == "Starting local music now"


def test_voice_trace_store_appends_rotates_and_reads_recent(tmp_path: Path) -> None:
    store = VoiceTraceStore(path=tmp_path / "voice" / "turns.jsonl", max_turns=3)

    for index in range(5):
        store.append(_entry(f"turn-{index}"))

    assert [item["turn_id"] for item in store.read_recent(limit=2)] == ["turn-3", "turn-4"]
    assert [item["turn_id"] for item in store.read_recent(limit=10)] == [
        "turn-2",
        "turn-3",
        "turn-4",
    ]

    lines = store.path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["turn_id"] for line in lines] == ["turn-2", "turn-3", "turn-4"]


def test_voice_trace_store_ignores_corrupt_lines_and_preserves_valid_lines(
    tmp_path: Path,
) -> None:
    path = tmp_path / "turns.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(_entry("valid-1").to_json_dict()),
                "{not-json",
                json.dumps(_entry("valid-2").to_json_dict()),
                "",
            ]
        ),
        encoding="utf-8",
    )
    store = VoiceTraceStore(path=path, max_turns=2)

    store.append(_entry("valid-3"))

    assert [item["turn_id"] for item in store.read_recent(limit=10)] == ["valid-2", "valid-3"]
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["turn_id"] for line in lines] == ["valid-2", "valid-3"]


def test_voice_trace_store_from_settings_uses_runtime_trace_settings(tmp_path: Path) -> None:
    trace_path = tmp_path / "settings-turns.jsonl"
    settings = SimpleNamespace(voice_trace_path=str(trace_path), voice_trace_max_turns=7)

    store = VoiceTraceStore.from_settings(settings)

    assert store.path == trace_path
    assert store.max_turns == 7


def test_voice_trace_helpers_make_trace_identifiers() -> None:
    timestamp = utc_now_iso()
    turn_id = new_turn_id()

    assert timestamp.endswith("Z")
    assert len(timestamp) == len("2026-04-27T12:00:00.000Z")
    assert len(turn_id) == 16
    assert int(turn_id, 16) >= 0


def test_default_voice_trace_path_constant() -> None:
    assert DEFAULT_VOICE_TRACE_PATH == Path("logs/voice/turns.jsonl")
