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
        self.running = False
        self.poll_thread: Optional[Thread] = None
        self.stop_event = Event()

        self.button_pressed = False
        self.press_start_time: Optional[float] = None
        self.pending_single_tap_time: Optional[float] = None

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

    def get_capabilities(self) -> List[InputAction]:
        """Return supported actions for the current mode."""
        if self.enable_navigation:
            return [
                InputAction.ADVANCE,
                InputAction.SELECT,
                InputAction.BACK,
            ]

        return [
            InputAction.PTT_PRESS,
            InputAction.PTT_RELEASE,
        ]

    def _get_button_state(self) -> bool:
        """Return True when the physical button is pressed."""
        if self.simulate or not self.device:
            return False

        try:
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

    def _handle_button_press(self, current_time: float) -> None:
        """Record a physical button press."""
        self._emit_pending_navigation(current_time)
        self.button_pressed = True
        self.press_start_time = current_time

        if not self.enable_navigation:
            self._fire_action(InputAction.PTT_PRESS, {"timestamp": current_time})

    def _handle_button_release(self, current_time: float) -> None:
        """Resolve a press/release sequence into the current interaction grammar."""
        self.button_pressed = False

        press_duration = 0.0
        if self.press_start_time is not None:
            press_duration = current_time - self.press_start_time

        if not self.enable_navigation:
            self._fire_action(
                InputAction.PTT_RELEASE,
                {
                    "timestamp": current_time,
                    "duration": press_duration,
                },
            )
            self.press_start_time = None
            return

        if press_duration >= self.long_press_time:
            self.pending_single_tap_time = None
            self._fire_action(
                InputAction.BACK,
                {
                    "method": "long_hold",
                    "duration": press_duration,
                },
            )
            self.press_start_time = None
            return

        if (
            self.pending_single_tap_time is not None
            and (current_time - self.pending_single_tap_time) < self.double_click_time
        ):
            self.pending_single_tap_time = None
            self._fire_action(
                InputAction.SELECT,
                {
                    "method": "double_tap",
                    "duration": press_duration,
                },
            )
            self.press_start_time = None
            return

        self.pending_single_tap_time = current_time
        self.press_start_time = None

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
                time.sleep(self.debounce_time)
                current_state = self._get_button_state()
                if current_state:
                    self._handle_button_press(time.time())

            elif not current_state and previous_state:
                self._handle_button_release(time.time())

            time.sleep(self.poll_rate)

        logger.debug("PTT button polling stopped")
