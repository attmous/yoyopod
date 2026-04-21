"""Cross-domain audio focus ownership for the frozen scaffold spine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from yoyopod.core.events import AudioFocusGrantedEvent, AudioFocusLostEvent, FocusOwner


@dataclass(frozen=True, slots=True)
class RequestFocusCommand:
    """Request audio focus for one owner, optionally allowing preemption."""

    owner: FocusOwner
    allow_preempt: bool = True


@dataclass(frozen=True, slots=True)
class ReleaseFocusCommand:
    """Release audio focus for one owner."""

    owner: FocusOwner


@dataclass(slots=True)
class FocusController:
    """Mutable focus bookkeeping owned by the scaffold application."""

    owner: str | None = None


def setup(app: Any) -> FocusController:
    """Register focus services and seed the canonical focus state."""

    controller = FocusController()
    app.focus = controller
    seed_focus_state(app)
    app.services.register("focus", "request", lambda data: request_focus(app, controller, data))
    app.services.register("focus", "release", lambda data: release_focus(app, controller, data))
    return controller


def teardown(app: Any) -> None:
    """Drop focus helpers from the scaffold application."""

    if hasattr(app, "focus"):
        delattr(app, "focus")


def seed_focus_state(app: Any) -> None:
    """Seed the scaffold focus owner state."""

    app.states.set("focus.owner", None, {"preempted_by": None})


def request_focus(app: Any, controller: FocusController, command: RequestFocusCommand) -> bool:
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

    controller.owner = command.owner
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


def release_focus(app: Any, controller: FocusController, command: ReleaseFocusCommand) -> bool:
    """Release focus when the caller owns it."""

    if not isinstance(command, ReleaseFocusCommand):
        raise TypeError("focus.release expects ReleaseFocusCommand")

    current_owner = app.states.get_value("focus.owner")
    if current_owner != command.owner:
        return False

    controller.owner = None
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


__all__ = [
    "AudioFocusGrantedEvent",
    "AudioFocusLostEvent",
    "FocusController",
    "ReleaseFocusCommand",
    "RequestFocusCommand",
    "setup",
    "teardown",
]
