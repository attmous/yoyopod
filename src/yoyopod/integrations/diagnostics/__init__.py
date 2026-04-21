"""Diagnostics integration scaffold for the Phase A spine rewrite."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from yoyopod.integrations.diagnostics.commands import SnapshotCommand
from yoyopod.integrations.diagnostics.handlers import append_event_record, write_snapshot


@dataclass(slots=True)
class DiagnosticsIntegration:
    """Runtime handles owned by the scaffold diagnostics integration."""

    event_log_path: Path
    snapshot_dir: Path


def setup(
    app: Any,
    *,
    snapshot_dir: str | Path | None = None,
    now_provider: Callable[[], datetime] | None = None,
) -> DiagnosticsIntegration:
    """Register scaffold diagnostics services and event recording."""

    actual_now = now_provider or (lambda: datetime.now(timezone.utc))
    actual_snapshot_dir = Path(snapshot_dir or (Path.home() / ".yoyopod" / "logs"))
    event_log_path = actual_snapshot_dir / "events.jsonl"
    integration = DiagnosticsIntegration(
        event_log_path=event_log_path,
        snapshot_dir=actual_snapshot_dir,
    )

    app.integrations["diagnostics"] = integration
    app.bus.subscribe(
        object,
        lambda event: append_event_record(
            app,
            event,
            event_log_path=event_log_path,
            now_provider=actual_now,
        ),
    )
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
    return integration


def teardown(app: Any) -> None:
    """Drop the scaffold diagnostics integration handle."""

    app.integrations.pop("diagnostics", None)


def _coerce_snapshot_command(data: object) -> SnapshotCommand:
    if not isinstance(data, SnapshotCommand):
        raise TypeError("diagnostics.snapshot expects SnapshotCommand")
    return data


__all__ = ["DiagnosticsIntegration", "SnapshotCommand", "setup", "teardown"]
