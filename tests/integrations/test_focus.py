"""Tests for the scaffold focus integration."""

from __future__ import annotations

from yoyopod.core import AudioFocusGrantedEvent, AudioFocusLostEvent, build_test_app, drain_all
from yoyopod.integrations.focus import (
    ReleaseFocusCommand,
    RequestFocusCommand,
    setup,
    teardown,
)


def test_focus_setup_seeds_owner_state() -> None:
    app = build_test_app()

    integration = setup(app)

    assert integration is app.integrations["focus"]
    assert integration.owner is None
    assert app.states.get_value("focus.owner") is None


def test_focus_request_preempts_previous_owner_and_emits_events() -> None:
    app = build_test_app()
    granted: list[AudioFocusGrantedEvent] = []
    lost: list[AudioFocusLostEvent] = []
    app.bus.subscribe(AudioFocusGrantedEvent, granted.append)
    app.bus.subscribe(AudioFocusLostEvent, lost.append)
    integration = setup(app)

    assert app.services.call("focus", "request", RequestFocusCommand(owner="music")) is True
    drain_all(app)

    assert integration.owner == "music"
    assert app.states.get_value("focus.owner") == "music"
    assert granted == [AudioFocusGrantedEvent(owner="music", preempted=None)]
    assert lost == []

    assert app.services.call("focus", "request", RequestFocusCommand(owner="call")) is True
    drain_all(app)

    assert integration.owner == "call"
    assert app.states.get_value("focus.owner") == "call"
    assert granted[-1] == AudioFocusGrantedEvent(owner="call", preempted="music")
    assert lost[-1] == AudioFocusLostEvent(owner="music", preempted_by="call")
    assert app.states.get("focus.owner").attrs == {
        "preempted_by": None,
        "preempted_owner": "music",
    }


def test_focus_request_can_decline_preemption() -> None:
    app = build_test_app()
    setup(app)

    assert app.services.call("focus", "request", RequestFocusCommand(owner="music")) is True
    assert (
        app.services.call(
            "focus",
            "request",
            RequestFocusCommand(owner="voice", allow_preempt=False),
        )
        is False
    )
    drain_all(app)

    assert app.states.get_value("focus.owner") == "music"


def test_focus_release_only_succeeds_for_current_owner() -> None:
    app = build_test_app()
    lost: list[AudioFocusLostEvent] = []
    app.bus.subscribe(AudioFocusLostEvent, lost.append)
    integration = setup(app)

    app.services.call("focus", "request", RequestFocusCommand(owner="call"))
    drain_all(app)

    assert app.services.call("focus", "release", ReleaseFocusCommand(owner="music")) is False
    assert app.services.call("focus", "release", ReleaseFocusCommand(owner="call")) is True
    drain_all(app)

    assert integration.owner is None
    assert app.states.get_value("focus.owner") is None
    assert lost[-1] == AudioFocusLostEvent(owner="call", preempted_by=None)

    teardown(app)
    assert "focus" not in app.integrations


def test_focus_services_reject_wrong_payload_types() -> None:
    app = build_test_app()
    setup(app)

    try:
        app.services.call("focus", "request", {"owner": "music"})  # type: ignore[arg-type]
    except TypeError as exc:
        assert str(exc) == "focus.request expects RequestFocusCommand"
    else:
        raise AssertionError("focus.request accepted an untyped payload")
