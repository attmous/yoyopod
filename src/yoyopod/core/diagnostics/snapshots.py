"""Diagnostics snapshots for the frozen scaffold spine."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from yoyopod.core.diagnostics.event_log import _jsonify
from yoyopod.core.status import build_runtime_status


@dataclass(frozen=True, slots=True)
class SnapshotCommand:
    """Write one scaffold diagnostics snapshot to disk."""

    reason: str
    tail_lines: int = 50


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
        **build_runtime_status(app),
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


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return cleaned or "snapshot"
