"""Tests for the core-owned cross-cutting event surface."""

from __future__ import annotations

import importlib

import pytest

import yoyopod.core as core_module
import yoyopod.core.events as core_events
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


def test_domain_events_are_not_reexported_from_core_surface() -> None:
    """Integration-owned event types should stay on their integration seams."""

    domain_event_names = (
        "CallEndedEvent",
        "MusicAvailabilityChangedEvent",
        "NetworkGpsFixEvent",
        "NetworkPppUpEvent",
        "PlaybackStateChangedEvent",
        "RegistrationChangedEvent",
        "TrackChangedEvent",
        "VoIPAvailabilityChangedEvent",
    )

    for event_name in domain_event_names:
        assert not hasattr(core_events, event_name)
        with pytest.raises(AttributeError):
            getattr(core_module, event_name)


def test_fsm_types_are_not_reexported_from_core_surface() -> None:
    """Domain-specific FSM types should stay on their owning integration seams."""

    for fsm_name in (
        "CallFSM",
        "CallInterruptionPolicy",
        "CallSessionState",
        "MusicFSM",
        "MusicState",
    ):
        with pytest.raises(AttributeError):
            getattr(core_module, fsm_name)

    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("yoyopod.core.fsm")
