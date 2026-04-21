"""
Single-button input adapter for the Whisplay HAT.

In Whisplay navigation mode the adapter emits:
- Single tap -> ADVANCE
- Double tap -> SELECT
- Long hold -> BACK

If navigation is disabled, the adapter falls back to raw PTT press/release
events for compatibility.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Event, Thread
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from yoyopod.ui.input.adapters.ptt_button_state import (
    PTTButtonState,
    PTTButtonStateMachine,
)
from yoyopod.ui.input.hal import InputAction, InputHAL


class PTTInputAdapter(InputHAL):
    """Input adapter for the Whisplay single button."""

    DEFAULT_DEBOUNCE_TIME = 0.05
    DEFAULT_LONG_PRESS_TIME = 0.8
    DEFAULT_DOUBLE_CLICK_TIME = 0.3
    DEFAULT_POLL_RATE = 0.03

    def __init__(
        self,
        whisplay_device: Optional[object] = None,
        enable_navigation: bool = True,
        debounce_time: float | None = None,
        double_click_time: float | None = None,
        long_press_time: float | None = None,
        simulate: bool = False,
    ) -> None:
        self.device = whisplay_device
        self.enable_navigation = enable_navigation
        self.simulate = simulate
        self.debounce_time = self.DEFAULT_DEBOUNCE_TIME if debounce_time is None else debounce_time
        self.double_click_time = (
            self.DEFAULT_DOUBLE_CLICK_TIME if double_click_time is None else double_click_time
        )
        self.long_press_time = (
            self.DEFAULT_LONG_PRESS_TIME if long_press_time is None else long_press_time
        )
        self.poll_rate = self.DEFAULT_POLL_RATE

        self.callbacks: Dict[InputAction, List[Callable]] = defaultdict(list)
        self.activity_callbacks: List[Callable[[Optional[Any]], None]] = []
        self.running = False
        self.poll_thread: Optional[Thread] = None
        self.stop_event = Event()

        self.state = PTTButtonState(
            enable_navigation=enable_navigation,
            debounce_time=self.debounce_time,
            double_click_time=self.double_click_time,
            long_press_time=self.long_press_time,
        )
        self._state_machine = PTTButtonStateMachine(
            state=self.state,
            emit_action=self._fire_action,
            emit_activity=self._fire_activity,
        )

        logger.debug(f"PTTInputAdapter initialized (navigation: {enable_navigation})")

    def start(self) -> None:
        """Start button polling."""
        if self.running:
            logger.warning("PTTInputAdapter already running")
            return

        self.running = True
        self.stop_event.clear()
        self.poll_thread = Thread(target=self._poll_button, daemon=True)
        self.poll_thread.start()
        logger.info("PTTInputAdapter started")

    def stop(self) -> None:
        """Stop button polling."""
        if not self.running:
            return

        self.running = False
        self.stop_event.set()

        if self.poll_thread:
            self.poll_thread.join(timeout=1.0)

        logger.info("PTTInputAdapter stopped")

    def on_action(
        self,
        action: InputAction,
        callback: Callable[[Optional[Any]], None],
    ) -> None:
        """Register callback for an action."""
        self.callbacks[action].append(callback)
        logger.debug(f"Registered callback for action: {action.value}")

    def clear_callbacks(self) -> None:
        """Clear all registered callbacks."""
        self.callbacks.clear()
        logger.debug("Cleared all PTT callbacks")

    def on_activity(self, callback: Callable[[Optional[Any]], None]) -> None:
        """Register a callback fired on raw physical button activity."""
        self.activity_callbacks.append(callback)
        logger.debug("Registered PTT raw activity callback")

    def get_capabilities(self) -> List[InputAction]:
        """Return supported actions for the current mode."""
        if self.enable_navigation:
            actions = [
                InputAction.ADVANCE,
                InputAction.BACK,
            ]
            if self._state_machine.double_tap_select_enabled:
                actions.append(InputAction.SELECT)
            if self.raw_ptt_passthrough:
                actions.extend([InputAction.PTT_PRESS, InputAction.PTT_RELEASE])
            return actions

        return [
            InputAction.PTT_PRESS,
            InputAction.PTT_RELEASE,
        ]

    def set_raw_ptt_passthrough(self, enabled: bool) -> None:
        """Enable or disable raw PTT press/release passthrough while in navigation mode."""
        self._state_machine.set_raw_ptt_passthrough(enabled)

    def set_double_tap_select_enabled(self, enabled: bool) -> None:
        """Enable or disable delayed double-tap select for one-button navigation."""
        self._state_machine.set_double_tap_select_enabled(enabled)

    def _get_button_state(self) -> bool:
        """Return True when the physical button is pressed."""
        if self.simulate or not self.device:
            return False

        try:
            if hasattr(self.device, "button_pressed") and callable(self.device.button_pressed):
                return self.device.button_pressed()
            if hasattr(self.device, "button_pressed"):
                return self.device.button_pressed
            if hasattr(self.device, "get_button_state"):
                return self.device.get_button_state()

            import RPi.GPIO as GPIO

            button_pin = 26
            return GPIO.input(button_pin) == GPIO.LOW
        except Exception as exc:
            logger.error(f"Error reading PTT button state: {exc}")
            return False

    def _fire_action(self, action: InputAction, data: Optional[Any] = None) -> None:
        """Fire registered callbacks for one action."""
        callbacks = self.callbacks.get(action, [])
        if not callbacks:
            return

        logger.debug(f"PTT action: {action.value}")
        for callback in callbacks:
            try:
                callback(data)
            except Exception as exc:
                logger.error(f"Error in PTT callback: {exc}")

    def _fire_activity(self, data: Optional[Any] = None) -> None:
        """Fire raw button activity callbacks."""
        for callback in self.activity_callbacks:
            try:
                callback(data)
            except Exception as exc:
                logger.error(f"Error in PTT activity callback: {exc}")

    def _check_hold_threshold(self, current_time: float) -> None:
        """Delegate hold-threshold processing to the state machine."""
        self._state_machine.check_hold_threshold(current_time)

    def _handle_button_press(self, current_time: float) -> None:
        """Delegate press handling to the state machine."""
        self._state_machine.handle_button_press(current_time)

    def _handle_button_release(self, current_time: float) -> None:
        """Delegate release handling to the state machine."""
        self._state_machine.handle_button_release(current_time)

    def _emit_pending_navigation(self, current_time: float) -> None:
        """Delegate pending navigation resolution to the state machine."""
        self._state_machine.emit_pending_navigation(current_time)

    def _observe_raw_state(self, current_state: bool, observed_at: float) -> None:
        """Track raw transitions in the state machine."""
        self._state_machine.observe_raw_state(current_state, observed_at)

    def _advance_debounced_state(self, current_time: float) -> None:
        """Delegate debounced state advancement to the state machine."""
        self._state_machine.advance_debounced_state(current_time)

    def _hold_deadline_pending(self) -> bool:
        """Return whether a hold deadline is still pending."""
        return self._state_machine.hold_deadline_pending()

    def _next_wait_timeout(self, current_time: float) -> float:
        """Return the next deadline for polling, debounce, hold, or single-tap resolution."""
        return self._state_machine.next_wait_timeout(current_time, self.poll_rate)

    def _poll_button(self) -> None:
        """Poll the button and emit semantic actions."""
        logger.debug("PTT button polling started")

        while not self.stop_event.is_set():
            current_time = time.monotonic()
            self._emit_pending_navigation(current_time)

            current_state = self._get_button_state()
            self._observe_raw_state(current_state, current_time)
            self._advance_debounced_state(current_time)

            if (
                self.button_pressed
                and self.press_start_time is not None
                and (current_time - self.press_start_time) >= self.long_press_time
            ):
                if self.raw_ptt_passthrough and not self.raw_hold_started:
                    self.raw_hold_started = True
                    self._fire_action(
                        InputAction.PTT_PRESS,
                        {
                            "timestamp": current_time,
                            "stage": "hold_started",
                            "duration": current_time - self.press_start_time,
                        },
                    )
                self._check_hold_threshold(current_time)

            self.stop_event.wait(self._next_wait_timeout(current_time))

        logger.debug("PTT button polling stopped")

    @property
    def button_pressed(self) -> bool:
        return self._state_machine.button_pressed

    @button_pressed.setter
    def button_pressed(self, value: bool) -> None:
        self._state_machine.button_pressed = value

    @property
    def press_start_time(self) -> Optional[float]:
        return self._state_machine.press_start_time

    @press_start_time.setter
    def press_start_time(self, value: Optional[float]) -> None:
        self._state_machine.press_start_time = value

    @property
    def pending_single_tap_time(self) -> Optional[float]:
        return self._state_machine.pending_single_tap_time

    @pending_single_tap_time.setter
    def pending_single_tap_time(self, value: Optional[float]) -> None:
        self._state_machine.pending_single_tap_time = value

    @property
    def double_tap_candidate(self) -> bool:
        return self._state_machine.double_tap_candidate

    @double_tap_candidate.setter
    def double_tap_candidate(self, value: bool) -> None:
        self._state_machine.double_tap_candidate = value

    @property
    def raw_ptt_passthrough(self) -> bool:
        return self._state_machine.raw_ptt_passthrough

    @raw_ptt_passthrough.setter
    def raw_ptt_passthrough(self, value: bool) -> None:
        self._state_machine.raw_ptt_passthrough = value

    @property
    def raw_hold_started(self) -> bool:
        return self._state_machine.raw_hold_started

    @raw_hold_started.setter
    def raw_hold_started(self, value: bool) -> None:
        self._state_machine.raw_hold_started = value

    @property
    def _hold_back_fired(self) -> bool:
        return self._state_machine.hold_back_fired

    @_hold_back_fired.setter
    def _hold_back_fired(self, value: bool) -> None:
        self._state_machine.hold_back_fired = value

    @property
    def _raw_button_state(self) -> bool:
        return self._state_machine.raw_button_state

    @_raw_button_state.setter
    def _raw_button_state(self, value: bool) -> None:
        self._state_machine.raw_button_state = value

    @property
    def _button_transition_time(self) -> Optional[float]:
        return self._state_machine.button_transition_time

    @_button_transition_time.setter
    def _button_transition_time(self, value: Optional[float]) -> None:
        self._state_machine.button_transition_time = value
