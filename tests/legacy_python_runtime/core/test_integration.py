"""End-to-end smoke tests for the scaffold core primitives."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from tests.fixtures.app import assert_events_contain, build_test_app, drain_all
from yoyopod.core import LifecycleEvent, StateChangedEvent, UserActivityEvent


@dataclass(frozen=True, slots=True)
class SetCallStateCommand:
    """Command used by the smoke test call service."""

    value: str


def test_full_round_trip_backend_to_state_to_subscriber() -> None:
    app = build_test_app()
    state_events: list[StateChangedEvent] = []
    activity_events: list[UserActivityEvent] = []
    app.bus.subscribe(StateChangedEvent, state_events.append)
    app.bus.subscribe(UserActivityEvent, activity_events.append)

    def set_call_state(command: SetCallStateCommand | None) -> None:
        assert isinstance(command, SetCallStateCommand)
        app.states.set("call.state", command.value)
        app.bus.publish(UserActivityEvent(action_name=f"call_{command.value}"))

    app.services.register("call", "set_state", set_call_state)

    worker = threading.Thread(
        target=lambda: app.scheduler.run_on_main(
            lambda: app.services.call("call", "set_state", SetCallStateCommand(value="incoming"))
        )
    )
    worker.start()
    worker.join()

    assert drain_all(app) == 3
    assert_events_contain(state_events, StateChangedEvent, entity="call.state", new="incoming")
    assert_events_contain(activity_events, UserActivityEvent, action_name="call_incoming")


def test_integration_lifecycle_events_and_teardown_reverse_order() -> None:
    app = build_test_app()
    seen: list[str] = []
    lifecycle_events: list[LifecycleEvent] = []
    app.bus.subscribe(LifecycleEvent, lifecycle_events.append)

    app.register_integration(
        "a",
        setup=lambda _app: seen.append("setup-a"),
        teardown=lambda _app: seen.append("teardown-a"),
    )
    app.register_integration(
        "b",
        setup=lambda _app: seen.append("setup-b"),
        teardown=lambda _app: seen.append("teardown-b"),
    )

    app.setup()
    app.stop()
    drain_all(app)

    assert seen == ["setup-a", "setup-b", "teardown-b", "teardown-a"]
    assert [(event.phase, event.detail) for event in lifecycle_events] == [
        ("setup_start", "a"),
        ("setup_complete", "a"),
        ("setup_start", "b"),
        ("setup_complete", "b"),
        ("stopping", ""),
        ("teardown_start", "b"),
        ("teardown_complete", "b"),
        ("teardown_start", "a"),
        ("teardown_complete", "a"),
        ("stopped", ""),
    ]


def test_off_main_bus_publish_rejected() -> None:
    app = build_test_app()
    errors: list[RuntimeError] = []

    worker = threading.Thread(
        target=lambda: _capture_runtime_error(
            errors,
            lambda: app.bus.publish(UserActivityEvent(action_name="unexpected")),
        )
    )
    worker.start()
    worker.join()

    assert len(errors) == 1
    assert "main thread" in str(errors[0])


def test_event_trace_assertion_helper_matches_real_state_events() -> None:
    app = build_test_app()
    captured_events: list[StateChangedEvent] = []
    app.bus.subscribe(StateChangedEvent, captured_events.append)

    app.states.set("call.state", "idle")
    app.states.set("music.state", "playing")
    drain_all(app)

    matched = assert_events_contain(
        captured_events,
        StateChangedEvent,
        entity="music.state",
        new="playing",
    )

    assert matched.entity == "music.state"
    assert [event.entity for event in captured_events] == ["call.state", "music.state"]


def _capture_runtime_error(errors: list[RuntimeError], fn: Callable[[], None]) -> None:
    try:
        fn()
    except RuntimeError as exc:
        errors.append(exc)
