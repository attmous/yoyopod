"""Gesture-recognition tests for the Whisplay single-button adapter."""

from __future__ import annotations

from yoyopy.ui.input import InputAction
from yoyopy.ui.input.adapters.ptt_button import PTTInputAdapter


def _record_actions(adapter: PTTInputAdapter) -> list[InputAction]:
    actions: list[InputAction] = []
    for action in (InputAction.ADVANCE, InputAction.SELECT, InputAction.BACK):
        adapter.on_action(action, lambda data=None, action=action: actions.append(action))
    return actions


def test_single_tap_emits_advance_after_double_tap_window() -> None:
    """Single taps should resolve to ADVANCE only after the timeout expires."""
    adapter = PTTInputAdapter(simulate=True, enable_navigation=True)
    actions = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    adapter._handle_button_release(0.1)
    adapter._emit_pending_navigation(0.39)
    assert actions == []

    adapter._emit_pending_navigation(0.41)
    assert actions == [InputAction.ADVANCE]


def test_double_tap_emits_select_and_cancels_pending_advance() -> None:
    """A second tap inside the window should emit SELECT instead of ADVANCE."""
    adapter = PTTInputAdapter(simulate=True, enable_navigation=True)
    actions = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    adapter._handle_button_release(0.1)
    adapter._handle_button_press(0.25)
    adapter._handle_button_release(0.35)
    adapter._emit_pending_navigation(0.7)

    assert actions == [InputAction.SELECT]


def test_long_hold_emits_back() -> None:
    """Long holds should map to BACK in one-button navigation mode."""
    adapter = PTTInputAdapter(simulate=True, enable_navigation=True)
    actions = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    adapter._handle_button_release(0.85)

    assert actions == [InputAction.BACK]


def test_long_hold_suppresses_pending_single_tap() -> None:
    """A pending single tap should be cleared if the next gesture becomes a long hold."""
    adapter = PTTInputAdapter(simulate=True, enable_navigation=True)
    actions = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    adapter._handle_button_release(0.1)
    adapter._handle_button_press(0.25)
    adapter._handle_button_release(1.1)
    adapter._emit_pending_navigation(1.5)

    assert actions == [InputAction.BACK]
