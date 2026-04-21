"""Handlers and serializers for the scaffold diagnostics integration."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from yoyopod.core.events import LifecycleEvent
from yoyopod.core.states import StateValue
from yoyopod.integrations.diagnostics.commands import SnapshotCommand


def append_event_record(
    app: Any,
    event: object,
    *,
    event_log_path: Path,
    now_provider: Callable[[], datetime],
) -> dict[str, object]:
    """Serialize one scaffold event, append it to logs, and return the entry."""

    entry = {
        "ts": _isoformat(now_provider()),
        "kind": "lifecycle" if isinstance(event, LifecycleEvent) else "event",
        "type": event.__class__.__name__,
        "payload": _jsonify(_serialize_event_payload(event)),
    }
    app.log_buffer.append(entry)
    event_log_path.parent.mkdir(parents=True, exist_ok=True)
    with event_log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, sort_keys=True))
        handle.write("\n")
    return entry


def write_snapshot(
    app: Any,
    command: SnapshotCommand,
    *,
    snapshot_dir: Path,
    event_log_path: Path,
    now_provider: Callable[[], datetime],
) -> Path:
    """Write one diagnostics snapshot and return its path."""

    if not isinstance(command, SnapshotCommand):
        raise TypeError("diagnostics.snapshot expects SnapshotCommand")

    snapshot_dir.mkdir(parents=True, exist_ok=True)
    timestamp = now_provider()
    tail_entries = app.log_buffer.tail(command.tail_lines)
    payload = {
        "ts": _isoformat(timestamp),
        "reason": command.reason,
        "states": {
            entity: _serialize_state_value(value)
            for entity, value in sorted(app.states.all().items())
        },
        "subscriptions": app.bus.subscription_counts(),
        "services": [f"{domain}.{service}" for domain, service in app.services.registered()],
        "tick_stats_last_100": app.tick_stats_snapshot(),
        "recent_events_tail_path": event_log_path.name,
        "recent_events_tail_lines": len(tail_entries),
        "recent_events_tail": _jsonify(tail_entries),
    }
    file_name = (
        "snapshot-" f"{timestamp.strftime('%Y%m%dT%H%M%SZ')}-" f"{_slugify(command.reason)}.json"
    )
    snapshot_path = snapshot_dir / file_name
    with snapshot_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
    return snapshot_path


def _serialize_event_payload(event: object) -> object:
    if is_dataclass(event):
        return asdict(event)
    return repr(event)


def _serialize_state_value(value: StateValue) -> dict[str, object]:
    return {
        "value": _jsonify(value.value),
        "attrs": _jsonify(dict(value.attrs)),
        "last_changed_at": value.last_changed_at,
    }


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "snapshot"


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
