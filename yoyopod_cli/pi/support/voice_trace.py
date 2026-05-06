"""Bounded JSONL voice interaction tracing."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import uuid
from typing import Any

from loguru import logger

DEFAULT_VOICE_TRACE_PATH = Path("logs/voice/turns.jsonl")
DEFAULT_TRANSCRIPT_LIMIT = 256


def utc_now_iso() -> str:
    """Return the current UTC timestamp with millisecond precision."""

    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_turn_id() -> str:
    """Return a compact random trace turn identifier."""

    return uuid.uuid4().hex[:16]


def _cap_text(value: str | None, limit: int) -> str | None:
    if value is None:
        return None

    normalized = " ".join(value.split())
    if not normalized:
        return ""
    if len(normalized) <= limit:
        return normalized
    if limit <= 0:
        return ""
    if limit <= 3:
        return normalized[:limit]
    return f"{normalized[: limit - 3]}..."


@dataclass(slots=True)
class VoiceTraceEntry:
    """One serialized voice interaction trace entry."""

    turn_id: str
    started_at: str
    completed_at: str
    source: str
    mode: str
    route_kind: str
    outcome: str
    schema_version: int = 1
    transcript_raw: str | None = None
    transcript_normalized: str | None = None
    activation_prefix: str | None = None
    command_intent: str | None = None
    command_confidence: float | None = None
    route_name: str | None = None
    ask_fallback: bool | None = None
    assistant_status: str | None = None
    assistant_title: str | None = None
    assistant_body_preview: str | None = None
    should_speak: bool | None = None
    auto_return: bool | None = None
    timings_ms: dict[str, Any] = field(default_factory=dict)
    audio_focus_before: dict[str, Any] = field(default_factory=dict)
    audio_focus_after: dict[str, Any] = field(default_factory=dict)
    music_before: dict[str, Any] = field(default_factory=dict)
    music_after: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    include_transcripts: bool = True
    text_limit: int = DEFAULT_TRANSCRIPT_LIMIT
    body_preview_chars: int = 160

    def to_json_dict(self) -> dict[str, Any]:
        """Return a compact JSON-ready trace payload."""

        payload: dict[str, Any] = {
            "schema_version": self.schema_version,
            "turn_id": self.turn_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "source": self.source,
            "mode": self.mode,
            "route_kind": self.route_kind,
            "outcome": self.outcome,
            "activation_prefix": self.activation_prefix,
            "command_intent": self.command_intent,
            "command_confidence": self.command_confidence,
            "route_name": self.route_name,
            "ask_fallback": self.ask_fallback,
            "assistant_status": self.assistant_status,
            "assistant_title": self.assistant_title,
            "assistant_body_preview": _cap_text(
                self.assistant_body_preview,
                self.body_preview_chars,
            ),
            "should_speak": self.should_speak,
            "auto_return": self.auto_return,
            "timings_ms": self.timings_ms,
            "audio_focus_before": self.audio_focus_before,
            "audio_focus_after": self.audio_focus_after,
            "music_before": self.music_before,
            "music_after": self.music_after,
            "error": self.error,
        }
        if self.include_transcripts:
            payload["transcript_raw"] = _cap_text(self.transcript_raw, self.text_limit)
            payload["transcript_normalized"] = _cap_text(
                self.transcript_normalized,
                self.text_limit,
            )

        return {key: value for key, value in payload.items() if value is not None and value != {}}


@dataclass(slots=True)
class VoiceTraceRecorder:
    """Mutable builder for one voice interaction trace entry."""

    store: VoiceTraceStore
    turn_id: str
    started_at: str
    source: str
    mode: str
    include_transcripts: bool = True
    body_preview_chars: int = 160
    route_kind: str = "unknown"
    outcome: str = "unknown"
    transcript_raw: str | None = None
    transcript_normalized: str | None = None
    activation_prefix: str | None = None
    command_intent: str | None = None
    command_confidence: float | None = None
    route_name: str | None = None
    ask_fallback: bool | None = None
    assistant_status: str | None = None
    assistant_title: str | None = None
    assistant_body_preview: str | None = None
    should_speak: bool | None = None
    auto_return: bool | None = None
    timings_ms: dict[str, Any] = field(default_factory=dict)
    audio_focus_before: dict[str, Any] = field(default_factory=dict)
    audio_focus_after: dict[str, Any] = field(default_factory=dict)
    music_before: dict[str, Any] = field(default_factory=dict)
    music_after: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    _completed: bool = False

    def record_error(self, stage: str, exc: BaseException) -> None:
        """Record a trace-scoped error without raising into voice handling."""

        self.route_kind = "error"
        self.error = {
            "stage": stage,
            "type": type(exc).__name__,
            "message": str(exc),
        }

    def complete(self) -> None:
        """Append the trace once with the recorder's current fields."""

        if self._completed:
            return
        self._completed = True
        self.store.append(
            VoiceTraceEntry(
                turn_id=self.turn_id,
                started_at=self.started_at,
                completed_at=utc_now_iso(),
                source=self.source,
                mode=self.mode,
                route_kind=self.route_kind,
                outcome=self.outcome,
                transcript_raw=self.transcript_raw,
                transcript_normalized=self.transcript_normalized,
                activation_prefix=self.activation_prefix,
                command_intent=self.command_intent,
                command_confidence=self.command_confidence,
                route_name=self.route_name,
                ask_fallback=self.ask_fallback,
                assistant_status=self.assistant_status,
                assistant_title=self.assistant_title,
                assistant_body_preview=self.assistant_body_preview,
                should_speak=self.should_speak,
                auto_return=self.auto_return,
                timings_ms=self.timings_ms,
                audio_focus_before=self.audio_focus_before,
                audio_focus_after=self.audio_focus_after,
                music_before=self.music_before,
                music_after=self.music_after,
                error=self.error,
                include_transcripts=self.include_transcripts,
                body_preview_chars=self.body_preview_chars,
            )
        )


@dataclass(slots=True)
class VoiceTraceStore:
    """Bounded JSONL trace store for recent voice turns."""

    path: Path
    max_turns: int = 50

    @classmethod
    def from_settings(cls, settings: Any) -> VoiceTraceStore:
        """Build a trace store from resolved runtime voice settings."""

        return cls(
            path=Path(getattr(settings, "voice_trace_path", DEFAULT_VOICE_TRACE_PATH)),
            max_turns=int(getattr(settings, "voice_trace_max_turns", 50)),
        )

    def append(self, entry: VoiceTraceEntry) -> None:
        """Append one trace entry and keep only the latest configured turns."""

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            entries = self._read_all_valid()
            entries.append(entry.to_json_dict())
            if self.max_turns > 0:
                entries = entries[-self.max_turns :]
            else:
                entries = []
            temp_path = self.path.with_name(f"{self.path.name}.tmp")
            temp_path.write_text(
                "".join(f"{json.dumps(item, sort_keys=True)}\n" for item in entries),
                encoding="utf-8",
            )
            os.replace(temp_path, self.path)
        except Exception as exc:  # pragma: no cover - defensive runtime guard
            logger.debug("Unable to append voice trace {}: {}", self.path, exc)

    def read_recent(self, limit: int) -> list[dict[str, Any]]:
        """Return the latest valid trace entries in chronological order."""

        if limit <= 0:
            return []
        return self._read_all_valid()[-limit:]

    def _read_all_valid(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []

        entries: list[dict[str, Any]] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            logger.debug("Unable to read voice trace {}: {}", self.path, exc)
            return []

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                item = json.loads(stripped)
            except json.JSONDecodeError as exc:
                logger.debug("Ignoring corrupt voice trace line in {}: {}", self.path, exc)
                continue
            if isinstance(item, dict):
                entries.append(item)
            else:
                logger.debug("Ignoring non-object voice trace line in {}", self.path)
        return entries


__all__ = [
    "DEFAULT_TRANSCRIPT_LIMIT",
    "DEFAULT_VOICE_TRACE_PATH",
    "VoiceTraceEntry",
    "VoiceTraceRecorder",
    "VoiceTraceStore",
    "new_turn_id",
    "utc_now_iso",
]
