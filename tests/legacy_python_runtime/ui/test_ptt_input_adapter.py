"""Gesture-recognition tests for the Whisplay single-button adapter."""

from __future__ import annotations

from types import SimpleNamespace

from yoyopod.ui.input import InputAction
from yoyopod.ui.input.adapters import ptt_button
from yoyopod.ui.input.adapters.ptt_button import PTTInputAdapter


def _record_actions(adapter: PTTInputAdapter) -> list[InputAction]:
    actions: list[InputAction] = []
    for action in (
        InputAction.ADVANCE,
        InputAction.SELECT,
        InputAction.BACK,
        InputAction.PTT_PRESS,
        InputAction.PTT_RELEASE,
    ):
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


def test_double_tap_uses_second_press_time_not_second_release_time() -> None:
    """A confirm tap that begins in time should still select even if released later."""
    adapter = PTTInputAdapter(simulate=True, enable_navigation=True)
    actions = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    adapter._handle_button_release(0.1)
    adapter._handle_button_press(0.39)
    adapter._handle_button_release(0.5)
    adapter._emit_pending_navigation(0.9)

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


def test_disabling_double_tap_select_emits_advance_immediately() -> None:
    """Simple one-button mode should page immediately on short release."""
    adapter = PTTInputAdapter(simulate=True, enable_navigation=True)
    adapter.set_double_tap_select_enabled(False)
    actions = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    adapter._handle_button_release(0.1)

    assert actions == [InputAction.ADVANCE]


def test_double_tap_select_attribute_tracks_state_machine_configuration() -> None:
    """The adapter should continue exposing double_tap_select_enabled as a public attribute."""
    adapter = PTTInputAdapter(simulate=True, enable_navigation=True)

    assert adapter.double_tap_select_enabled is True

    adapter.double_tap_select_enabled = False

    assert adapter.double_tap_select_enabled is False
    assert adapter.state.double_tap_select_enabled is False
    assert InputAction.SELECT not in adapter.get_capabilities()

    adapter.set_double_tap_select_enabled(False)

    assert adapter.double_tap_select_enabled is False
    assert InputAction.SELECT not in adapter.get_capabilities()


def test_enable_navigation_attribute_remains_the_single_source_of_truth() -> None:
    """Toggling enable_navigation on the adapter should update the shared state object."""
    adapter = PTTInputAdapter(simulate=True, enable_navigation=True)

    adapter.enable_navigation = False

    assert adapter.enable_navigation is False
    assert adapter.state.enable_navigation is False
    assert adapter.get_capabilities() == [InputAction.PTT_PRESS, InputAction.PTT_RELEASE]


def test_timing_attributes_remain_synchronized_with_state_machine() -> None:
    """Public timing attributes should update the shared timing state used by gesture logic."""
    adapter = PTTInputAdapter(simulate=True, enable_navigation=True)

    adapter.debounce_time = 0.08
    adapter.double_click_time = 0.24
    adapter.long_press_time = 0.95

    assert adapter.debounce_time == 0.08
    assert adapter.double_click_time == 0.24
    assert adapter.long_press_time == 0.95
    assert adapter.state.debounce_time == 0.08
    assert adapter.state.double_click_time == 0.24
    assert adapter.state.long_press_time == 0.95


def test_button_press_fires_raw_activity_immediately() -> None:
    """Physical button presses should emit wake-worthy activity before gesture resolution."""
    adapter = PTTInputAdapter(simulate=True, enable_navigation=True)
    activity_events: list[dict] = []
    adapter.on_activity(lambda data=None: activity_events.append(data or {}))

    adapter._handle_button_press(0.25)

    assert activity_events == [{"timestamp": 0.25, "pressed": True}]


def test_raw_press_transition_fires_wake_activity_before_debounce_resolution() -> None:
    """A sleeping screen should wake on the physical edge, even before debounce accepts it."""
    adapter = PTTInputAdapter(
        simulate=True,
        enable_navigation=True,
        debounce_time=0.05,
    )
    activity_events: list[dict] = []
    actions = _record_actions(adapter)
    adapter.on_activity(lambda data=None: activity_events.append(data or {}))

    adapter._observe_raw_state(True, 0.10)

    assert activity_events == [
        {"timestamp": 0.10, "pressed": True, "stage": "raw_press"},
    ]
    assert actions == []


def test_poll_loop_preserves_double_tap_window_across_debounce(monkeypatch) -> None:
    """A second tap near the timeout should still resolve to SELECT, not ADVANCE."""
    adapter = PTTInputAdapter(
        simulate=False,
        enable_navigation=True,
        debounce_time=0.05,
        double_click_time=0.3,
    )
    actions = _record_actions(adapter)

    clock = SimpleNamespace(current=0.0)

    def fake_time() -> float:
        return clock.current

    class FakeStopEvent:
        def is_set(self) -> bool:
            return clock.current >= 0.8

        def wait(self, timeout: float | None = None) -> bool:
            step = 0.0005 if timeout is None else max(timeout, 0.0005)
            clock.current = round(clock.current + step, 4)
            return False

    def fake_button_state() -> bool:
        current = clock.current
        return (0.0 <= current < 0.10) or (0.39 <= current < 0.49)

    monkeypatch.setattr(ptt_button.time, "monotonic", fake_time)
    adapter._get_button_state = fake_button_state
    adapter.poll_rate = 0.01
    adapter.stop_event = FakeStopEvent()

    adapter._poll_button()

    assert actions == [InputAction.SELECT]


def test_idle_poll_loop_waits_on_stop_event_between_samples() -> None:
    """The one-button adapter should sleep on the stop event while idle."""

    adapter = PTTInputAdapter(simulate=True, enable_navigation=True)
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

    adapter._poll_button()

    assert waits == [adapter.poll_rate]


def test_next_wait_timeout_falls_back_to_poll_rate_after_navigation_hold_fires() -> None:
    """Held navigation presses should return to the idle cadence after BACK has fired."""

    adapter = PTTInputAdapter(simulate=True, enable_navigation=True)
    adapter.button_pressed = True
    adapter.press_start_time = 0.0
    adapter._hold_back_fired = True

    assert adapter._next_wait_timeout(adapter.long_press_time + 0.1) == adapter.poll_rate


def test_next_wait_timeout_falls_back_to_poll_rate_after_raw_hold_starts() -> None:
    """Raw passthrough holds should not keep scheduling zero-time wakeups."""

    adapter = PTTInputAdapter(simulate=True, enable_navigation=True)
    adapter.set_raw_ptt_passthrough(True)
    adapter.button_pressed = True
    adapter.press_start_time = 0.0
    adapter.raw_hold_started = True

    assert adapter._next_wait_timeout(adapter.long_press_time + 0.1) == adapter.poll_rate


def test_raw_ptt_passthrough_emits_hold_press_and_release_without_back() -> None:
    """Voice-note passthrough should surface raw hold events and suppress BACK."""

    adapter = PTTInputAdapter(simulate=True, enable_navigation=True)
    adapter.set_raw_ptt_passthrough(True)
    actions = _record_actions(adapter)

    adapter._handle_button_press(0.0)
    adapter._poll_button = lambda: None  # not used; keep static analysis quiet
    adapter.press_start_time = 0.0
    adapter.button_pressed = True
    adapter.raw_hold_started = False
    if (0.85 - adapter.press_start_time) >= adapter.long_press_time:
        adapter.raw_hold_started = True
        adapter._fire_action(InputAction.PTT_PRESS, {"stage": "hold_started", "duration": 0.85})
    adapter._handle_button_release(0.85)

    assert actions == [InputAction.PTT_PRESS, InputAction.PTT_PRESS, InputAction.PTT_RELEASE]
