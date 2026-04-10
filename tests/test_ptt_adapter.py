"""Tests for PTT adapter hold-threshold and PTT_RELEASE behavior."""

from __future__ import annotations

from typing import Any, Optional

from yoyopy.ui.input import InputAction
from yoyopy.ui.input.adapters.ptt_button import PTTInputAdapter


class FakePTTAdapter(PTTInputAdapter):
    """PTT adapter with controllable button state for deterministic testing."""

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("simulate", True)
        kwargs.setdefault("enable_navigation", True)
        super().__init__(**kwargs)
        self._fake_button_state = False

    def _get_button_state(self) -> bool:
        return self._fake_button_state


def _record_actions(adapter: PTTInputAdapter) -> list[tuple[InputAction, Optional[Any]]]:
    """Register callbacks on all relevant actions and return a log of (action, data) tuples."""
    log: list[tuple[InputAction, Optional[Any]]] = []
    for action in (
        InputAction.ADVANCE,
        InputAction.SELECT,
        InputAction.BACK,
        InputAction.PTT_PRESS,
        InputAction.PTT_RELEASE,
    ):
        adapter.on_action(
            action,
            lambda data=None, a=action: log.append((a, data)),
        )
    return log


def test_back_fires_at_hold_threshold_while_pressed() -> None:
    """BACK should fire at the 800ms threshold while the button is still pressed."""
    adapter = FakePTTAdapter()
    log = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    # Button is still held -- simulate the poll loop detecting the threshold
    adapter._check_hold_threshold(0.85)

    actions = [action for action, _ in log]
    assert InputAction.BACK in actions
    # Verify it was tagged as long_hold
    back_entries = [(a, d) for a, d in log if a == InputAction.BACK]
    assert len(back_entries) == 1
    assert back_entries[0][1]["method"] == "long_hold"


def test_ptt_release_fires_on_release_after_hold() -> None:
    """PTT_RELEASE with after_hold=True should fire on release after a hold-triggered BACK."""
    adapter = FakePTTAdapter()
    log = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    adapter._check_hold_threshold(0.85)
    adapter._handle_button_release(1.2)

    actions = [action for action, _ in log]
    assert actions == [InputAction.BACK, InputAction.PTT_RELEASE]

    release_entries = [(a, d) for a, d in log if a == InputAction.PTT_RELEASE]
    assert len(release_entries) == 1
    assert release_entries[0][1]["after_hold"] is True


def test_back_does_not_fire_again_on_release_after_threshold() -> None:
    """BACK must NOT fire a second time on release if it already fired at the threshold."""
    adapter = FakePTTAdapter()
    log = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    adapter._check_hold_threshold(0.85)
    adapter._handle_button_release(1.2)

    back_count = sum(1 for a, _ in log if a == InputAction.BACK)
    assert back_count == 1


def test_short_press_produces_advance() -> None:
    """A short press should still produce ADVANCE, not BACK or PTT_RELEASE."""
    adapter = FakePTTAdapter()
    log = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    adapter._handle_button_release(0.1)
    # Let the double-tap window expire
    adapter._emit_pending_navigation(0.5)

    actions = [action for action, _ in log]
    assert actions == [InputAction.ADVANCE]


def test_double_tap_produces_select() -> None:
    """Double-tap should still produce SELECT."""
    adapter = FakePTTAdapter()
    log = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    adapter._handle_button_release(0.1)
    adapter._handle_button_press(0.25)
    adapter._handle_button_release(0.35)
    adapter._emit_pending_navigation(0.7)

    actions = [action for action, _ in log]
    assert actions == [InputAction.SELECT]


def test_check_hold_threshold_does_not_fire_when_navigation_disabled() -> None:
    """_check_hold_threshold should be a no-op when navigation is disabled."""
    adapter = FakePTTAdapter(enable_navigation=False)
    log = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    adapter._check_hold_threshold(0.85)

    back_entries = [a for a, _ in log if a == InputAction.BACK]
    assert back_entries == []


def test_check_hold_threshold_does_not_fire_during_raw_ptt_passthrough() -> None:
    """_check_hold_threshold should be a no-op when raw_ptt_passthrough is active."""
    adapter = FakePTTAdapter()
    adapter.set_raw_ptt_passthrough(True)
    log = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    adapter._check_hold_threshold(0.85)

    back_entries = [a for a, _ in log if a == InputAction.BACK]
    assert back_entries == []


def test_check_hold_threshold_fires_only_once() -> None:
    """Repeated _check_hold_threshold calls should not fire BACK more than once."""
    adapter = FakePTTAdapter()
    log = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    adapter._check_hold_threshold(0.85)
    adapter._check_hold_threshold(0.90)
    adapter._check_hold_threshold(1.00)

    back_count = sum(1 for a, _ in log if a == InputAction.BACK)
    assert back_count == 1


def test_hold_back_fired_resets_on_next_press() -> None:
    """The _hold_back_fired flag should reset on the next button press."""
    adapter = FakePTTAdapter()
    log = _record_actions(adapter)

    # First gesture: hold triggers BACK
    adapter._handle_button_press(0.0)
    adapter._check_hold_threshold(0.85)
    adapter._handle_button_release(1.2)

    # Second gesture: another hold should also trigger BACK
    adapter._handle_button_press(2.0)
    adapter._check_hold_threshold(2.85)
    adapter._handle_button_release(3.0)

    back_count = sum(1 for a, _ in log if a == InputAction.BACK)
    assert back_count == 2
