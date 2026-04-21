"""Tests for new scaffold events exported from `yoyopod.core.events`."""

from __future__ import annotations

from yoyopod.core import (
    AudioFocusGrantedEvent,
    AudioFocusLostEvent,
    LifecycleEvent,
    StateChangedEvent,
)


def test_scaffold_events_are_constructible() -> None:
    lifecycle = LifecycleEvent(phase="ready", detail="booted")
    focus_granted = AudioFocusGrantedEvent(owner="call", preempted="music")
    focus_lost = AudioFocusLostEvent(owner="music", preempted_by="call")
    changed = StateChangedEvent(
        entity="call.state",
        old="idle",
        new="ringing",
        attrs={"caller": "Ada"},
        last_changed_at=1.5,
    )

    assert lifecycle.phase == "ready"
    assert focus_granted.preempted == "music"
    assert focus_lost.preempted_by == "call"
    assert changed.entity == "call.state"
