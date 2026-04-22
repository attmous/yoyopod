"""Tests for the core recovery supervisor."""

from __future__ import annotations

import time
from types import SimpleNamespace

from tests.fixtures.app import build_test_app, drain_all
from yoyopod.core.events import BackendStoppedEvent
from yoyopod.core.recovery import (
    RecoveryAttemptedEvent,
    RequestRecoveryCommand,
    RecoveryState,
    RuntimeRecoveryService,
    setup,
    teardown,
)


def test_recovery_setup_registers_supervisor_and_manual_service() -> None:
    app = build_test_app()
    attempts: list[str] = []
    events: list[RecoveryAttemptedEvent] = []
    app.bus.subscribe(RecoveryAttemptedEvent, events.append)

    integration = setup(app, initial_delay_seconds=0.01, max_delay_seconds=0.05)
    app.recovery_supervisor.register_retry_handler(
        "music",
        lambda: (attempts.append("music"), True)[1],
    )

    app.services.call(
        "recovery",
        "request_recovery",
        RequestRecoveryCommand(domain="music"),
    )

    _drain_until(lambda: len(events) == 1, app)

    assert integration is app.recovery
    assert attempts == ["music"]
    assert events == [RecoveryAttemptedEvent(domain="music", success=True, reason="manual")]

    teardown(app)
    assert not hasattr(app, "recovery")


def test_recovery_backend_stopped_event_triggers_retry() -> None:
    app = build_test_app()
    attempts: list[str] = []
    events: list[RecoveryAttemptedEvent] = []
    app.bus.subscribe(RecoveryAttemptedEvent, events.append)
    setup(app, initial_delay_seconds=0.01, max_delay_seconds=0.05)
    app.recovery_supervisor.register_retry_handler(
        "call",
        lambda: (attempts.append("call"), True)[1],
    )

    app.bus.publish(BackendStoppedEvent(domain="call", reason="lost"))
    drain_all(app)
    _drain_until(lambda: len(events) == 1, app)

    assert attempts == ["call"]
    assert events[-1] == RecoveryAttemptedEvent(domain="call", success=True, reason="lost")


def test_recovery_retries_failures_with_backoff_until_success() -> None:
    app = build_test_app()
    events: list[RecoveryAttemptedEvent] = []
    app.bus.subscribe(RecoveryAttemptedEvent, events.append)
    setup(app, initial_delay_seconds=0.01, max_delay_seconds=0.02)

    attempts = {"count": 0}

    def flaky_handler() -> bool:
        attempts["count"] += 1
        return attempts["count"] >= 3

    app.recovery_supervisor.register_retry_handler("network", flaky_handler)
    app.services.call(
        "recovery",
        "request_recovery",
        RequestRecoveryCommand(domain="network"),
    )

    _drain_until(lambda: len(events) >= 3, app, timeout_seconds=1.0)

    assert attempts["count"] >= 3
    assert [event.success for event in events[:3]] == [False, False, True]
    assert events[0].reason == "manual"
    assert events[1].reason == "retry_1"
    assert events[2].reason == "retry_2"


def test_recovery_service_rejects_wrong_payload_type() -> None:
    app = build_test_app()
    setup(app, initial_delay_seconds=0.01, max_delay_seconds=0.05)

    try:
        app.services.call("recovery", "request_recovery", {"domain": "music"})  # type: ignore[arg-type]
    except TypeError as exc:
        assert str(exc) == "recovery.request_recovery expects RequestRecoveryCommand"
    else:
        raise AssertionError("recovery.request_recovery accepted an untyped payload")


def test_runtime_recovery_skips_music_restart_during_active_call() -> None:
    """Music recovery should not start while the call FSM is active."""

    app = SimpleNamespace(
        music_backend=SimpleNamespace(is_connected=False, startup_in_progress=False),
        app_state_runtime=SimpleNamespace(call_fsm=SimpleNamespace(is_active=True)),
        _music_recovery=RecoveryState(),
        _stopping=False,
    )
    service = RuntimeRecoveryService(app)
    started: list[float] = []
    service.start_music_recovery_worker = lambda recovery_now: started.append(recovery_now)

    service.attempt_music_recovery(12.5)

    assert started == []
    assert app._music_recovery.in_flight is False


def _drain_until(predicate, app, *, timeout_seconds: float = 0.5) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        drain_all(app)
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not satisfied before timeout")
