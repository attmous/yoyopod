"""JSONL diagnostics event log for the frozen scaffold spine."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Protocol

from yoyopod.core.events import LifecycleEvent


class _LogBuffer(Protocol):
    def append(self, entry: Any) -> None:
        """Append one diagnostics entry."""


class EventLogWriter:
    """Append normalized diagnostics entries to both memory and JSONL."""

    def __init__(
        self,
        *,
        log_buffer: _LogBuffer,
        event_log_path: Path,
        now_provider: Callable[[], datetime],
    ) -> None:
        self._log_buffer = log_buffer
        self.event_log_path = event_log_path
        self._now_provider = now_provider

    def append(self, entry: dict[str, object]) -> dict[str, object]:
        """Normalize and persist one diagnostics entry."""

        normalized = {
            "ts": entry.get("ts", _isoformat(self._now_provider())),
            **{key: _jsonify(value) for key, value in entry.items() if key != "ts"},
        }
        self._log_buffer.append(normalized)
        self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.event_log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(normalized, sort_keys=True))
            handle.write("\n")
        return normalized

    def append_event(self, event: object) -> dict[str, object]:
        """Serialize one scaffold event and persist it."""

        return self.append(
            {
                "kind": "lifecycle" if isinstance(event, LifecycleEvent) else "event",
                "type": event.__class__.__name__,
                "payload": _serialize_event_payload(event),
            }
        )


def _serialize_event_payload(event: object) -> object:
    if is_dataclass(event):
        return asdict(event)
    return repr(event)


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonify(value: object) -> object:
    if is_dataclass(value):
        return _jsonify(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonify(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonify(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return _isoformat(value)
    if isinstance(value, Enum):
        return value.value
    return value


__all__ = ["EventLogWriter"]
