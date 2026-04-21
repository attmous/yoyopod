"""Unit tests for the small runtime metrics store."""

from __future__ import annotations

from queue import Queue
from types import SimpleNamespace

from yoyopod.core.status import RuntimeMetricsStore


def test_runtime_metrics_store_tracks_queue_backlog() -> None:
    """Queue snapshots should combine regular and safety callback backlog."""

    store = RuntimeMetricsStore()
    callbacks: Queue[object] = Queue()
    safety_callbacks: Queue[object] = Queue()

    callbacks.put(object())
    callbacks.put(object())
    safety_callbacks.put(object())

    assert store.pending_main_thread_callback_count(callbacks, safety_callbacks) == 3


def test_runtime_metrics_store_records_input_and_capture_markers() -> None:
    """Input and watchdog markers should stay together in one runtime-owned store."""

    store = RuntimeMetricsStore()

    store.note_input_activity(SimpleNamespace(value="select"), captured_at=12.5)
    store.note_handled_input(action_name="select", handled_at=13.0)
    store.record_responsiveness_capture(
        captured_at=14.0,
        reason="coordinator_stall_after_input",
        suspected_scope="input_to_runtime_handoff",
        summary="capture",
        artifacts={"snapshot": "/tmp/capture.json"},
    )

    assert store.last_input_activity_at == 12.5
    assert store.last_input_activity_action_name == "select"
    assert store.last_input_handled_at == 13.0
    assert store.last_input_handled_action_name == "select"
    assert store.last_responsiveness_capture_at == 14.0
    assert store.last_responsiveness_capture_reason == "coordinator_stall_after_input"
    assert store.last_responsiveness_capture_scope == "input_to_runtime_handoff"
    assert store.last_responsiveness_capture_summary == "capture"
    assert store.last_responsiveness_capture_artifacts == {
        "snapshot": "/tmp/capture.json"
    }
