"""Core diagnostics helpers for the frozen scaffold spine."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from yoyopod.core.diagnostics.event_log import EventLogWriter
from yoyopod.core.diagnostics.snapshots import SnapshotCommand, write_snapshot


@dataclass(slots=True)
class DiagnosticsRuntime:
    """Runtime handles owned by the core diagnostics helpers."""

    event_log_path: Path
    snapshot_dir: Path
    event_log: EventLogWriter


def setup(
    app: Any,
    *,
    snapshot_dir: str | Path | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> DiagnosticsRuntime:
    """Register diagnostics services and event recording."""

    actual_now = now_provider or (lambda: datetime.now(timezone.utc))
    actual_snapshot_dir = Path(snapshot_dir or (Path.home() / ".yoyopod" / "logs"))
    event_log_path = actual_snapshot_dir / "events.jsonl"
    event_log = EventLogWriter(
        log_buffer=app.log_buffer,
        event_log_path=event_log_path,
        now_provider=actual_now,
    )
    runtime = DiagnosticsRuntime(
        event_log_path=event_log_path,
        snapshot_dir=actual_snapshot_dir,
        event_log=event_log,
    )

    app.diagnostics = runtime
    app.bus.set_diagnostics_log(event_log)
    app.scheduler.set_diagnostics_log(event_log)
    app.services.set_diagnostics_log(event_log)
    app.background.set_diagnostics_log(event_log)
    app.bus.subscribe(object, event_log.append_event)
    app.services.register(
        "diagnostics",
        "snapshot",
        lambda data: write_snapshot(
            app,
            _coerce_snapshot_command(data),
            snapshot_dir=actual_snapshot_dir,
            event_log_path=event_log_path,
            now_provider=actual_now,
        ),
    )
    return runtime


def teardown(app: Any) -> None:
    """Drop diagnostics helpers from the scaffold application."""

    if hasattr(app, "diagnostics"):
        delattr(app, "diagnostics")
    app.bus.set_diagnostics_log(None)
    app.scheduler.set_diagnostics_log(None)
    app.services.set_diagnostics_log(app.log_buffer)
    app.background.set_diagnostics_log(app.log_buffer)


def _coerce_snapshot_command(data: object) -> SnapshotCommand:
    if not isinstance(data, SnapshotCommand):
        raise TypeError("diagnostics.snapshot expects SnapshotCommand")
    return data


__all__ = [
    "DiagnosticsRuntime",
    "EventLogWriter",
    "SnapshotCommand",
    "setup",
    "teardown",
    "write_snapshot",
]
