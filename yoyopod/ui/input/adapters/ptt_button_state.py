"""State machine for the PTT one-button interaction profile.

The state machine intentionally keeps the full temporal grammar for the single
button in one place: debounce, pending tap resolution, and hold thresholds all
share the same mutable timeline. Keeping those transitions together makes the
adapter smaller without scattering gesture state across multiple helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from yoyopod.ui.input.hal import InputAction


@dataclass
class PTTButtonState:
    """Runtime state tracked by the PTT interaction machine."""

    enable_navigation: bool
    debounce_time: float
    double_click_time: float
    long_press_time: float

    button_pressed: bool = False
    _raw_button_state: bool = False
    _button_transition_time: Optional[float] = None
    press_start_time: Optional[float] = None
    pending_single_tap_time: Optional[float] = None
    double_tap_candidate: bool = False
    raw_ptt_passthrough: bool = False
    raw_hold_started: bool = False
    _hold_back_fired: bool = False
    double_tap_select_enabled: bool = True


class PTTButtonStateMachine:
    """Decodes raw button edges into high-level input actions."""

    def __init__(
        self,
        state: PTTButtonState,
        emit_action: Callable[[InputAction, Optional[dict]], None],
        emit_activity: Callable[[dict], None],
    ) -> None:
        self._state = state
        self._emit_action = emit_action
        self._emit_activity = emit_activity

    def set_raw_ptt_passthrough(self, enabled: bool) -> None:
        self._state.raw_ptt_passthrough = bool(enabled)
        self._state.raw_hold_started = False
        self._state.pending_single_tap_time = None
        self._state.double_tap_candidate = False

    def set_double_tap_select_enabled(self, enabled: bool) -> None:
        self._state.double_tap_select_enabled = bool(enabled)
        self._state.pending_single_tap_time = None
        self._state.double_tap_candidate = False

    def _fire_action(self, action: InputAction, data: Optional[dict] = None) -> None:
        self._emit_action(action, data)

    def check_hold_threshold(self, current_time: float) -> None:
        """Fire BACK at the hold threshold while the button is still pressed."""
        if (
            not self._state.enable_navigation
            or self._state._hold_back_fired
            or self._state.press_start_time is None
            or self._state.raw_ptt_passthrough
        ):
            return
        if (current_time - self._state.press_start_time) >= self._state.long_press_time:
            self._state._hold_back_fired = True
            self._fire_action(
                InputAction.BACK,
                {
                    "method": "long_hold",
                    "duration": current_time - self._state.press_start_time,
                },
            )

    def handle_button_press(self, current_time: float) -> None:
        """Record a physical button press."""
        self._emit_activity(
            {
                "timestamp": current_time,
                "pressed": True,
            }
        )
        self._state.double_tap_candidate = (
            self._state.enable_navigation
            and self._state.double_tap_select_enabled
            and self._state.pending_single_tap_time is not None
            and (current_time - self._state.pending_single_tap_time) < self._state.double_click_time
        )
        if not self._state.double_tap_candidate and self._state.double_tap_select_enabled:
            self.emit_pending_navigation(current_time)
        self._state.button_pressed = True
        self._state.press_start_time = current_time
        self._state.raw_hold_started = False
        self._state._hold_back_fired = False

        if self._state.raw_ptt_passthrough:
            self._fire_action(
                InputAction.PTT_PRESS,
                {
                    "timestamp": current_time,
                    "stage": "pressed",
                },
            )

        if not self._state.enable_navigation:
            self._fire_action(InputAction.PTT_PRESS, {"timestamp": current_time})

    def handle_button_release(self, current_time: float) -> None:
        """Resolve a press/release sequence into the current interaction grammar."""
        self._state.button_pressed = False

        press_duration = 0.0
        if self._state.press_start_time is not None:
            press_duration = current_time - self._state.press_start_time

        if self._state.raw_ptt_passthrough:
            self._fire_action(
                InputAction.PTT_RELEASE,
                {
                    "timestamp": current_time,
                    "duration": press_duration,
                    "hold_started": self._state.raw_hold_started,
                },
            )

        if not self._state.enable_navigation:
            self._fire_action(
                InputAction.PTT_RELEASE,
                {
                    "timestamp": current_time,
                    "duration": press_duration,
                },
            )
            self._state.press_start_time = None
            self._state.double_tap_candidate = False
            self._state.raw_hold_started = False
            return

        if self._state.raw_ptt_passthrough and self._state.raw_hold_started:
            self._state.pending_single_tap_time = None
            self._state.double_tap_candidate = False
            self._state.press_start_time = None
            self._state.raw_hold_started = False
            return

        if self._state._hold_back_fired:
            self._state._hold_back_fired = False
            self._fire_action(
                InputAction.PTT_RELEASE,
                {
                    "timestamp": current_time,
                    "duration": press_duration,
                    "after_hold": True,
                },
            )
            self._state.press_start_time = None
            self._state.pending_single_tap_time = None
            self._state.double_tap_candidate = False
            self._state.raw_hold_started = False
            return

        if press_duration >= self._state.long_press_time:
            self._state.pending_single_tap_time = None
            self._state.double_tap_candidate = False
            self._fire_action(
                InputAction.BACK,
                {
                    "method": "long_hold",
                    "duration": press_duration,
                },
            )
            self._state.press_start_time = None
            self._state.raw_hold_started = False
            return

        if not self._state.double_tap_select_enabled:
            self._state.pending_single_tap_time = None
            self._state.double_tap_candidate = False
            self._fire_action(
                InputAction.ADVANCE,
                {
                    "method": "single_tap",
                    "timestamp": current_time,
                },
            )
            self._state.press_start_time = None
            self._state.raw_hold_started = False
            return

        if self._state.double_tap_candidate:
            self._state.pending_single_tap_time = None
            self._state.double_tap_candidate = False
            self._fire_action(
                InputAction.SELECT,
                {
                    "method": "double_tap",
                    "duration": press_duration,
                },
            )
            self._state.press_start_time = None
            self._state.raw_hold_started = False
            return

        self._state.double_tap_candidate = False
        self._state.pending_single_tap_time = current_time
        self._state.press_start_time = None
        self._state.raw_hold_started = False

    def emit_pending_navigation(self, current_time: float) -> None:
        """Emit ADVANCE once the double-tap window has expired."""
        if (
            not self._state.enable_navigation
            or not self._state.double_tap_select_enabled
            or self._state.button_pressed
            or self._state._raw_button_state
        ):
            return

        if self._state.pending_single_tap_time is None:
            return

        if (current_time - self._state.pending_single_tap_time) < self._state.double_click_time:
            return

        self._state.pending_single_tap_time = None
        self._fire_action(
            InputAction.ADVANCE,
            {
                "method": "single_tap",
                "timestamp": current_time,
            },
        )

    def observe_raw_state(self, current_state: bool, observed_at: float) -> None:
        """Track raw button transitions and start debounce windows when needed."""
        if current_state == self._state._raw_button_state:
            return

        self._state._raw_button_state = current_state
        self._state._button_transition_time = observed_at

    def advance_debounced_state(self, current_time: float) -> None:
        """Resolve a debounced physical state change into press/release handlers."""
        transition_started_at = self._state._button_transition_time
        if transition_started_at is None:
            return

        if (current_time - transition_started_at) < self._state.debounce_time:
            return

        self._state._button_transition_time = None
        if self._state._raw_button_state == self._state.button_pressed:
            return

        if self._state._raw_button_state:
            self.handle_button_press(transition_started_at)
        else:
            self.handle_button_release(transition_started_at)

    def hold_deadline_pending(self) -> bool:
        """Return True while a held button still has threshold work pending."""
        if not self._state.button_pressed or self._state.press_start_time is None:
            return False
        if self._state.raw_ptt_passthrough:
            return not self._state.raw_hold_started
        if not self._state.enable_navigation:
            return False
        return not self._state._hold_back_fired

    def next_wait_timeout(self, current_time: float, poll_rate: float) -> float:
        """Return the next deadline for polling, debounce, hold, or single-tap resolution."""
        deadlines = [poll_rate]

        if self._state._button_transition_time is not None:
            deadlines.append(
                max(
                    0.0,
                    self._state.debounce_time
                    - (current_time - self._state._button_transition_time),
                )
            )

        if self.hold_deadline_pending() and self._state.press_start_time is not None:
            hold_remaining = self._state.long_press_time - (
                current_time - self._state.press_start_time
            )
            if hold_remaining > 0.0:
                deadlines.append(hold_remaining)

        if (
            self._state.enable_navigation
            and self._state.double_tap_select_enabled
            and not self._state.button_pressed
            and not self._state._raw_button_state
            and self._state.pending_single_tap_time is not None
        ):
            deadlines.append(
                max(
                    0.0,
                    self._state.double_click_time
                    - (current_time - self._state.pending_single_tap_time),
                )
            )

        return min(deadlines)
