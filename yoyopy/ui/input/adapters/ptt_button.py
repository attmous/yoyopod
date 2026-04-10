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

from yoyopy.ui.input.hal import InputAction, InputHAL


class PTTInputAdapter(InputHAL):
    """Input adapter for the Whisplay single button."""

    DEFAULT_DEBOUNCE_TIME = 0.05
    DEFAULT_LONG_PRESS_TIME = 0.8
    DEFAULT_DOUBLE_CLICK_TIME = 0.3
    DEFAULT_POLL_RATE = 0.01

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
        self.debounce_time = (
            self.DEFAULT_DEBOUNCE_TIME if debounce_time is None else debounce_time
        )
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

        self.button_pressed = False
        self.press_start_time: Optional[float] = None
        self.pending_single_tap_time: Optional[float] = None
        self.double_tap_candidate = False
        self.raw_ptt_passthrough = False
        self.raw_hold_started = False
        self._hold_back_fired = False

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
                InputAction.SELECT,
                InputAction.BACK,
            ]
            if self.raw_ptt_passthrough:
                actions.extend([InputAction.PTT_PRESS, InputAction.PTT_RELEASE])
            return actions

        return [
            InputAction.PTT_PRESS,
            InputAction.PTT_RELEASE,
        ]

    def set_raw_ptt_passthrough(self, enabled: bool) -> None:
        """Enable or disable raw PTT press/release passthrough while in navigation mode."""
        self.raw_ptt_passthrough = bool(enabled)
        self.raw_hold_started = False
        self.pending_single_tap_time = None
        self.double_tap_candidate = False

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
        """Fire BACK at the hold threshold while the button is still pressed."""
        if (
            not self.enable_navigation
            or self._hold_back_fired
            or self.press_start_time is None
            or self.raw_ptt_passthrough
        ):
            return
        if (current_time - self.press_start_time) >= self.long_press_time:
            self._hold_back_fired = True
            self._fire_action(
                InputAction.BACK,
                {
                    "method": "long_hold",
                    "duration": current_time - self.press_start_time,
                },
            )

    def _handle_button_press(self, current_time: float) -> None:
        """Record a physical button press."""
        self._fire_activity(
            {
                "timestamp": current_time,
                "pressed": True,
            }
        )
        self.double_tap_candidate = (
            self.enable_navigation
            and self.pending_single_tap_time is not None
            and (current_time - self.pending_single_tap_time) < self.double_click_time
        )
        if not self.double_tap_candidate:
            self._emit_pending_navigation(current_time)
        self.button_pressed = True
        self.press_start_time = current_time
        self.raw_hold_started = False
        self._hold_back_fired = False

        if self.raw_ptt_passthrough:
            self._fire_action(
                InputAction.PTT_PRESS,
                {
                    "timestamp": current_time,
                    "stage": "pressed",
                },
            )

        if not self.enable_navigation:
            self._fire_action(InputAction.PTT_PRESS, {"timestamp": current_time})

    def _handle_button_release(self, current_time: float) -> None:
        """Resolve a press/release sequence into the current interaction grammar."""
        self.button_pressed = False

        press_duration = 0.0
        if self.press_start_time is not None:
            press_duration = current_time - self.press_start_time

        if self.raw_ptt_passthrough:
            self._fire_action(
                InputAction.PTT_RELEASE,
                {
                    "timestamp": current_time,
                    "duration": press_duration,
                    "hold_started": self.raw_hold_started,
                },
            )

        if not self.enable_navigation:
            self._fire_action(
                InputAction.PTT_RELEASE,
                {
                    "timestamp": current_time,
                    "duration": press_duration,
                },
            )
            self.press_start_time = None
            self.double_tap_candidate = False
            self.raw_hold_started = False
            return

        if self.raw_ptt_passthrough and self.raw_hold_started:
            self.pending_single_tap_time = None
            self.double_tap_candidate = False
            self.press_start_time = None
            self.raw_hold_started = False
            return

        if self._hold_back_fired:
            self._hold_back_fired = False
            self._fire_action(
                InputAction.PTT_RELEASE,
                {
                    "timestamp": current_time,
                    "duration": press_duration,
                    "after_hold": True,
                },
            )
            self.press_start_time = None
            self.pending_single_tap_time = None
            self.double_tap_candidate = False
            self.raw_hold_started = False
            return

        if press_duration >= self.long_press_time:
            self.pending_single_tap_time = None
            self.double_tap_candidate = False
            self._fire_action(
                InputAction.BACK,
                {
                    "method": "long_hold",
                    "duration": press_duration,
                },
            )
            self.press_start_time = None
            self.raw_hold_started = False
            return

        if self.double_tap_candidate:
            self.pending_single_tap_time = None
            self.double_tap_candidate = False
            self._fire_action(
                InputAction.SELECT,
                {
                    "method": "double_tap",
                    "duration": press_duration,
                },
            )
            self.press_start_time = None
            self.raw_hold_started = False
            return

        self.double_tap_candidate = False
        self.pending_single_tap_time = current_time
        self.press_start_time = None
        self.raw_hold_started = False

    def _emit_pending_navigation(self, current_time: float) -> None:
        """Emit ADVANCE once the double-tap window has expired."""
        if not self.enable_navigation or self.button_pressed:
            return

        if self.pending_single_tap_time is None:
            return

        if (current_time - self.pending_single_tap_time) < self.double_click_time:
            return

        self.pending_single_tap_time = None
        self._fire_action(
            InputAction.ADVANCE,
            {
                "method": "single_tap",
                "timestamp": current_time,
            },
        )

    def _poll_button(self) -> None:
        """Poll the button and emit semantic actions."""
        logger.debug("PTT button polling started")

        while not self.stop_event.is_set():
            current_time = time.time()
            self._emit_pending_navigation(current_time)

            current_state = self._get_button_state()
            previous_state = self.button_pressed

            if current_state and not previous_state:
                press_detected_at = current_time
                time.sleep(self.debounce_time)
                current_state = self._get_button_state()
                if current_state:
                    self._handle_button_press(press_detected_at)

            elif (
                current_state
                and previous_state
                and self.press_start_time is not None
                and (current_time - self.press_start_time) >= self.long_press_time
            ):
                # existing raw_ptt_passthrough logic stays here
                if (
                    self.raw_ptt_passthrough
                    and not self.raw_hold_started
                ):
                    self.raw_hold_started = True
                    self._fire_action(
                        InputAction.PTT_PRESS,
                        {
                            "timestamp": current_time,
                            "stage": "hold_started",
                            "duration": current_time - self.press_start_time,
                        },
                    )
                # fire BACK at threshold for navigation mode
                self._check_hold_threshold(current_time)

            elif not current_state and previous_state:
                self._handle_button_release(time.time())

            time.sleep(self.poll_rate)

        logger.debug("PTT button polling stopped")
