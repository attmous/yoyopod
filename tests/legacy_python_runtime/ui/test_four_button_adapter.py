"""Focused tests for the four-button input adapter wait behavior."""

from __future__ import annotations

from yoyopod.ui.input import InputAction
from yoyopod.ui.input.adapters.four_button import Button, FourButtonInputAdapter


def test_idle_poll_loop_waits_on_stop_event_between_samples() -> None:
    """The polling thread should park on the stop event between idle samples."""

    adapter = FourButtonInputAdapter(simulate=True)
    waits: list[float] = []

    class FakeStopEvent:
        def __init__(self) -> None:
            self._set = False

        def is_set(self) -> bool:
            return self._set

        def wait(self, timeout: float | None = None) -> bool:
            waits.append(0.0 if timeout is None else timeout)
            self._set = True
            return True

    adapter.stop_event = FakeStopEvent()

    adapter._poll_buttons()

    assert waits == [adapter.POLL_INTERVAL]


def test_debounced_release_emits_button_action_without_inline_sleep() -> None:
    """Stable press and release edges should still map to the configured action."""

    adapter = FourButtonInputAdapter(simulate=True)
    actions: list[tuple[InputAction, object | None]] = []
    adapter.on_action(
        InputAction.SELECT,
        lambda data=None: actions.append((InputAction.SELECT, data)),
    )

    adapter._observe_raw_state(Button.A, True, 1.0)
    adapter._advance_button_state(Button.A, 1.06)
    adapter._observe_raw_state(Button.A, False, 1.20)
    adapter._advance_button_state(Button.A, 1.26)

    assert actions == [
        (InputAction.SELECT, {"button": "A"}),
    ]
