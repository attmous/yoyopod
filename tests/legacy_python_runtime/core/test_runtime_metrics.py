"""Unit tests for the small runtime metrics store."""

from __future__ import annotations

from types import SimpleNamespace

from yoyopod.core.status import RuntimeMetricsStore


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


def test_runtime_metrics_records_input_to_action_latency() -> None:
    store = RuntimeMetricsStore()

    store.note_input_activity(SimpleNamespace(value="select"), captured_at=10.0)
    store.note_handled_input(action_name="select", handled_at=10.035)

    snapshot = store.responsiveness_snapshot(now=11.0)

    assert snapshot["responsiveness_input_to_action_count"] == 1
    assert snapshot["responsiveness_input_to_action_p95_ms"] == 35.0
    assert snapshot["responsiveness_input_to_action_last_ms"] == 35.0
    assert snapshot["responsiveness_last_input_to_action_name"] == "select"


def test_runtime_metrics_percentile_uses_half_up_indexing() -> None:
    store = RuntimeMetricsStore()

    store.note_input_activity(SimpleNamespace(value="first"), captured_at=10.0)
    store.note_handled_input(action_name="first", handled_at=10.010)
    store.note_input_activity(SimpleNamespace(value="second"), captured_at=20.0)
    store.note_handled_input(action_name="second", handled_at=20.050)

    snapshot = store.responsiveness_snapshot(now=21.0)

    assert snapshot["responsiveness_input_to_action_p50_ms"] == 50.0


def test_runtime_metrics_correlates_backlogged_inputs_fifo() -> None:
    store = RuntimeMetricsStore()

    store.note_input_activity(SimpleNamespace(value="first"), captured_at=10.0)
    store.note_input_activity(SimpleNamespace(value="second"), captured_at=20.0)
    store.note_handled_input(action_name="first", handled_at=10.050)
    store.note_handled_input(action_name="second", handled_at=20.025)

    snapshot = store.responsiveness_snapshot(now=21.0)

    assert snapshot["responsiveness_input_to_action_count"] == 2
    assert snapshot["responsiveness_input_to_action_max_ms"] == 50.0
    assert snapshot["responsiveness_input_to_action_last_ms"] == 25.0


def test_runtime_metrics_ignores_raw_activity_for_input_to_action_queue() -> None:
    store = RuntimeMetricsStore()

    store.note_input_activity(None, captured_at=9.0)
    store.note_input_activity(SimpleNamespace(value="select"), captured_at=10.0)
    store.note_handled_input(action_name="select", handled_at=10.050)

    snapshot = store.responsiveness_snapshot(now=11.0)

    assert snapshot["responsiveness_input_to_action_count"] == 1
    assert snapshot["responsiveness_input_to_action_last_ms"] == 50.0


def test_runtime_metrics_does_not_sample_raw_activity_without_semantic_marker() -> None:
    store = RuntimeMetricsStore()

    store.note_input_activity(None, captured_at=9.0)
    store.note_handled_input(action_name="select", handled_at=10.050)

    snapshot = store.responsiveness_snapshot(now=11.0)

    assert snapshot["responsiveness_input_to_action_count"] == 0
    assert snapshot["responsiveness_input_to_action_last_ms"] is None


def test_runtime_metrics_records_action_to_visible_refresh_latency() -> None:
    store = RuntimeMetricsStore()

    store.note_input_activity(SimpleNamespace(value="down"), captured_at=20.0)
    store.note_handled_input(action_name="down", handled_at=20.010)
    store.note_visible_refresh(refreshed_at=20.085)

    snapshot = store.responsiveness_snapshot(now=21.0)

    assert snapshot["responsiveness_action_to_visible_count"] == 1
    assert snapshot["responsiveness_action_to_visible_p95_ms"] == 75.0
    assert snapshot["responsiveness_action_to_visible_last_ms"] == 75.0
    assert snapshot["responsiveness_last_visible_action_name"] == "down"


def test_runtime_metrics_ignores_refresh_without_handled_input() -> None:
    store = RuntimeMetricsStore()

    store.note_visible_refresh(refreshed_at=30.0)

    snapshot = store.responsiveness_snapshot(now=31.0)

    assert snapshot["responsiveness_action_to_visible_count"] == 0
    assert snapshot["responsiveness_action_to_visible_p95_ms"] is None
