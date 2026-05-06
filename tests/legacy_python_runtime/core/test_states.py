"""Tests for the scaffold entity store."""

from __future__ import annotations

from yoyopod.core import StateChangedEvent, States
from yoyopod.core.bus import Bus


def test_states_set_publishes_state_changed_event() -> None:
    bus = Bus()
    states = States(bus, clock=lambda: 12.5)
    seen: list[StateChangedEvent] = []
    bus.subscribe(StateChangedEvent, seen.append)

    states.set("call.state", "ringing", {"caller": "Ada"})
    bus.drain()

    assert states.get_value("call.state") == "ringing"
    assert seen == [
        StateChangedEvent(
            entity="call.state",
            old=None,
            new="ringing",
            attrs={"caller": "Ada"},
            last_changed_at=12.5,
        )
    ]


def test_states_set_is_noop_when_value_and_attrs_match() -> None:
    bus = Bus()
    states = States(bus, clock=lambda: 1.0)
    seen: list[StateChangedEvent] = []
    bus.subscribe(StateChangedEvent, seen.append)

    states.set("music.state", "paused", {"source": "call"})
    states.set("music.state", "paused", {"source": "call"})
    bus.drain()

    assert len(seen) == 1


def test_states_all_and_get_return_copied_attrs() -> None:
    bus = Bus()
    states = States(bus)
    states.set("screen.state", "awake", {"brightness": 80})
    bus.drain()

    one = states.get("screen.state")
    all_states = states.all()

    assert one is not None
    one.attrs["brightness"] = 10
    all_states["screen.state"].attrs["brightness"] = 5
    assert states.get("screen.state").attrs == {"brightness": 80}
