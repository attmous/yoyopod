"""Tests for the scaffold diagnostics event log and snapshots."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from tests.fixtures.app import build_test_app
from yoyopod.core.diagnostics import setup, teardown
from yoyopod.core.diagnostics.snapshots import SnapshotCommand


def test_diagnostics_setup_records_events_and_writes_snapshot(tmp_path: Path) -> None:
    app = build_test_app()
    logs_dir = tmp_path / "logs"
    now = datetime(2026, 4, 21, 12, 0, 0, tzinfo=timezone.utc)

    runtime = setup(
        app,
        snapshot_dir=logs_dir,
        now_provider=lambda: now,
    )

    app.start()
    app.states.set("display.awake", True, {"source": "test"})
    app.tick()

    log_entries = app.log_buffer.snapshot()
    assert runtime is app.diagnostics
    assert any(
        entry["kind"] == "lifecycle" and entry["payload"]["phase"] == "starting"
        for entry in log_entries
    )
    assert any(
        entry["kind"] == "event"
        and entry["type"] == "StateChangedEvent"
        and entry["payload"]["entity"] == "display.awake"
        for entry in log_entries
    )

    snapshot_path = app.services.call(
        "diagnostics",
        "snapshot",
        SnapshotCommand(reason="Bug Report", tail_lines=8),
    )

    assert snapshot_path == logs_dir / "snapshot-20260421T120000Z-bug-report.json"
    payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["reason"] == "Bug Report"
    assert payload["states"]["display.awake"]["value"] is True
    assert payload["states"]["display.awake"]["attrs"] == {"source": "test"}
    assert payload["services"] == ["diagnostics.snapshot"]
    assert payload["subscriptions"] == {"object": 1}
    assert payload["tick_stats_last_100"]["sample_count"] == 1
    assert payload["recent_events_tail_path"] == "events.jsonl"
    assert payload["recent_events_tail_lines"] >= 2
    assert any(entry["kind"] == "command" for entry in payload["recent_events_tail"])

    event_log_lines = (logs_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(event_log_lines) == 4
    first_event = json.loads(event_log_lines[0])
    assert first_event["kind"] == "lifecycle"
    assert first_event["payload"]["phase"] == "starting"

    teardown(app)
    assert not hasattr(app, "diagnostics")


def test_diagnostics_snapshot_rejects_untyped_payload(tmp_path: Path) -> None:
    app = build_test_app()
    setup(app, snapshot_dir=tmp_path)

    try:
        app.services.call("diagnostics", "snapshot", {"reason": "bad"})  # type: ignore[arg-type]
    except TypeError as exc:
        assert str(exc) == "diagnostics.snapshot expects SnapshotCommand"
    else:
        raise AssertionError("diagnostics.snapshot accepted an untyped payload")
