"""Handlers for the scaffold focus integration."""

from __future__ import annotations

from typing import Any

from yoyopod.core import AudioFocusGrantedEvent, AudioFocusLostEvent
from yoyopod.integrations.focus.commands import ReleaseFocusCommand, RequestFocusCommand


def seed_focus_state(app: Any) -> None:
    """Seed the scaffold focus owner state."""

    app.states.set("focus.owner", None, {"preempted_by": None})


def request_focus(app: Any, integration: Any, command: RequestFocusCommand) -> bool:
    """Grant focus to one owner, preempting the current owner when allowed."""

    if not isinstance(command, RequestFocusCommand):
        raise TypeError("focus.request expects RequestFocusCommand")

    current_owner = app.states.get_value("focus.owner")
    if current_owner == command.owner:
        return True

    if current_owner is not None and not command.allow_preempt:
        return False

    if current_owner is not None:
        app.bus.publish(AudioFocusLostEvent(owner=current_owner, preempted_by=command.owner))

    integration.owner = command.owner
    app.states.set(
        "focus.owner",
        command.owner,
        {
            "preempted_by": None,
            "preempted_owner": current_owner,
        },
    )
    app.bus.publish(AudioFocusGrantedEvent(owner=command.owner, preempted=current_owner))
    return True


def release_focus(app: Any, integration: Any, command: ReleaseFocusCommand) -> bool:
    """Release focus when the caller owns it."""

    if not isinstance(command, ReleaseFocusCommand):
        raise TypeError("focus.release expects ReleaseFocusCommand")

    current_owner = app.states.get_value("focus.owner")
    if current_owner != command.owner:
        return False

    integration.owner = None
    app.states.set(
        "focus.owner",
        None,
        {
            "preempted_by": None,
            "released_by": command.owner,
        },
    )
    app.bus.publish(AudioFocusLostEvent(owner=command.owner, preempted_by=None))
    return True
