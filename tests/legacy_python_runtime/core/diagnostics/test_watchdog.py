"""Tests for the opt-in responsiveness watchdog."""

from __future__ import annotations

from yoyopod.core.diagnostics.watchdog import (
    ResponsivenessWatchdog,
    evaluate_responsiveness_status,
)


def _status(**overrides: object) -> dict[str, object]:
    status = {
        "state": "menu",
        "current_screen": "menu",
        "display_backend": "lvgl",
        "loop_heartbeat_age_seconds": 0.1,
        "lvgl_pump_age_seconds": 0.1,
        "pending_scheduler_tasks": 0,
        "pending_bus_events": 0,
        "input_activity_age_seconds": None,
        "handled_input_activity_age_seconds": None,
        "last_input_action": None,
        "last_handled_input_action": None,
    }
    status.update(overrides)
    return status


def test_evaluate_responsiveness_status_ignores_healthy_loop() -> None:
    """Healthy loop heartbeats should not trigger automatic evidence capture."""

    decision = evaluate_responsiveness_status(
        _status(loop_heartbeat_age_seconds=0.8),
        stall_threshold_seconds=5.0,
        recent_input_window_seconds=3.0,
    )

    assert decision is None


def test_evaluate_responsiveness_status_flags_recent_input_handoff_stall() -> None:
    """Recent raw input with a stale coordinator heartbeat should point at the handoff seam."""

    decision = evaluate_responsiveness_status(
        _status(
            loop_heartbeat_age_seconds=6.5,
            input_activity_age_seconds=0.4,
            handled_input_activity_age_seconds=7.1,
            last_input_action="select",
            last_handled_input_action="back",
        ),
        stall_threshold_seconds=5.0,
        recent_input_window_seconds=3.0,
    )

    assert decision is not None
    assert decision.reason == "coordinator_stall_after_input"
    assert decision.suspected_scope == "input_to_runtime_handoff"
    assert "last_input=select" in decision.summary


def test_evaluate_responsiveness_status_flags_pending_work_stall() -> None:
    """Queued callbacks or events should be surfaced as broader runtime stalls."""

    decision = evaluate_responsiveness_status(
        _status(
            loop_heartbeat_age_seconds=5.5,
            pending_scheduler_tasks=2,
            pending_bus_events=1,
        ),
        stall_threshold_seconds=5.0,
        recent_input_window_seconds=3.0,
    )

    assert decision is not None
    assert decision.reason == "coordinator_stall_with_pending_work"
    assert decision.suspected_scope == "runtime"


def test_watchdog_captures_once_per_stall_until_recovery() -> None:
    """A persistent stall should capture once, then arm again only after recovery."""

    current_status = _status(
        loop_heartbeat_age_seconds=6.0,
        pending_scheduler_tasks=1,
    )
    captures: list[str] = []
    now = [0.0]

    watchdog = ResponsivenessWatchdog(
        status_provider=lambda: current_status,
        capture_callback=lambda decision, status: captures.append(
            f"{decision.reason}:{status['loop_heartbeat_age_seconds']}"
        ),
        stall_threshold_seconds=5.0,
        recent_input_window_seconds=3.0,
        poll_interval_seconds=1.0,
        capture_cooldown_seconds=10.0,
        time_provider=lambda: now[0],
    )

    first = watchdog.poll_once()
    second = watchdog.poll_once()

    assert first is not None
    assert second is None
    assert captures == ["coordinator_stall_with_pending_work:6.0"]

    current_status["loop_heartbeat_age_seconds"] = 0.2
    assert watchdog.poll_once() is None

    current_status["loop_heartbeat_age_seconds"] = 6.0
    now[0] = 20.0
    third = watchdog.poll_once()

    assert third is not None
    assert captures == [
        "coordinator_stall_with_pending_work:6.0",
        "coordinator_stall_with_pending_work:6.0",
    ]
