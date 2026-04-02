"""
Four-button input adapter for Pimoroni Display HAT Mini.

Maps physical buttons (A, B, X, Y) to semantic input actions.
"""

import time
from collections import defaultdict
from enum import Enum
from typing import Callable, Dict, Optional, Any, List
from threading import Thread, Event
from loguru import logger

from yoyopy.ui.input.input_hal import InputHAL, InputAction

try:
    from displayhatmini import DisplayHATMini
    HAS_BUTTONS = True
except Exception as e:
    HAS_BUTTONS = False
    logger.warning(
        f"DisplayHATMini unavailable or unusable ({e}) - "
        "button input will be simulated"
    )


class Button(Enum):
    """Physical button identifiers for Display HAT Mini."""
    A = "A"
    B = "B"
    X = "X"
    Y = "Y"


class ButtonEvent(Enum):
    """Physical button event types."""
    PRESS = "press"
    LONG_PRESS = "long_press"
    DOUBLE_PRESS = "double_press"


class FourButtonInputAdapter(InputHAL):
    """
    Input adapter for 4-button interface (Pimoroni Display HAT Mini).

    Maps physical buttons to semantic actions:
    - Button A → SELECT
    - Button B → BACK
    - Button X → UP
    - Button Y → DOWN

    Supports press, long press, and double press detection.
    """

    # Default button-to-action mapping
    DEFAULT_MAPPING = {
        Button.A: InputAction.SELECT,
        Button.B: InputAction.BACK,
        Button.X: InputAction.UP,
        Button.Y: InputAction.DOWN,
    }

    # Long press mappings (optional)
    LONG_PRESS_MAPPING = {
        Button.B: InputAction.HOME,  # Long press B = Home
    }

    # Timing constants (in seconds)
    DEBOUNCE_TIME = 0.05      # 50ms debounce
    LONG_PRESS_TIME = 1.0     # 1 second for long press
    DOUBLE_PRESS_TIME = 0.3   # 300ms window for double press

    def __init__(
        self,
        display_device: Optional[object] = None,
        button_mapping: Optional[Dict[Button, InputAction]] = None,
        simulate: bool = False
    ) -> None:
        """
        Initialize the four-button input adapter.

        Args:
            display_device: DisplayHATMini device instance
            button_mapping: Custom button-to-action mapping (optional)
            simulate: Run in simulation mode (no hardware)
        """
        self.simulate = simulate or not HAS_BUTTONS
        self.device = display_device
        self.mapping = button_mapping or self.DEFAULT_MAPPING

        # Callback storage
        self.callbacks: Dict[InputAction, List[Callable]] = defaultdict(list)

        # Polling thread control
        self.running = False
        self.poll_thread: Optional[Thread] = None
        self.stop_event = Event()

        # Button state tracking
        self.button_states: Dict[Button, bool] = {
            Button.A: False,
            Button.B: False,
            Button.X: False,
            Button.Y: False,
        }

        # Press time tracking for long press detection
        self.button_press_times: Dict[Button, Optional[float]] = {
            Button.A: None,
            Button.B: None,
            Button.X: None,
            Button.Y: None,
        }

        # Last press time for double press detection
        self.button_last_press: Dict[Button, Optional[float]] = {
            Button.A: None,
            Button.B: None,
            Button.X: None,
            Button.Y: None,
        }

        # Long press fired flags
        self.long_press_fired: Dict[Button, bool] = {
            Button.A: False,
            Button.B: False,
            Button.X: False,
            Button.Y: False,
        }

        if not self.simulate:
            logger.debug("FourButtonInputAdapter initialized with hardware")
        else:
            logger.debug("FourButtonInputAdapter running in simulation mode")

    def start(self) -> None:
        """Start button polling."""
        if self.running:
            logger.warning("FourButtonInputAdapter already running")
            return

        self.running = True
        self.stop_event.clear()
        self.poll_thread = Thread(target=self._poll_buttons, daemon=True)
        self.poll_thread.start()
        logger.info("FourButtonInputAdapter started")

    def stop(self) -> None:
        """Stop button polling."""
        if not self.running:
            return

        self.running = False
        self.stop_event.set()

        if self.poll_thread:
            self.poll_thread.join(timeout=1.0)

        logger.info("FourButtonInputAdapter stopped")

    def on_action(
        self,
        action: InputAction,
        callback: Callable[[Optional[Any]], None]
    ) -> None:
        """Register callback for an action."""
        self.callbacks[action].append(callback)
        logger.debug(f"Registered callback for action: {action.value}")

    def clear_callbacks(self) -> None:
        """Clear all registered callbacks."""
        self.callbacks.clear()
        logger.debug("Cleared all button callbacks")

    def get_capabilities(self) -> List[InputAction]:
        """Return list of supported actions."""
        # Return all actions from the mapping
        capabilities = list(self.mapping.values())
        capabilities.extend(self.LONG_PRESS_MAPPING.values())
        return list(set(capabilities))  # Remove duplicates

    def _get_button_state(self, button: Button) -> bool:
        """
        Get the current state of a button.

        Args:
            button: Button to check

        Returns:
            True if button is pressed, False otherwise
        """
        if self.simulate or not self.device:
            return False

        # Map button enum to displayhatmini button attributes
        button_map = {
            Button.A: self.device.read_button(self.device.BUTTON_A),
            Button.B: self.device.read_button(self.device.BUTTON_B),
            Button.X: self.device.read_button(self.device.BUTTON_X),
            Button.Y: self.device.read_button(self.device.BUTTON_Y),
        }

        return button_map.get(button, False)

    def _fire_action(self, action: InputAction, data: Optional[Any] = None) -> None:
        """
        Fire all registered callbacks for an action.

        Args:
            action: Action that occurred
            data: Optional data dict
        """
        callbacks = self.callbacks.get(action, [])
        if callbacks:
            logger.debug(f"Button action: {action.value}")
            for callback in callbacks:
                try:
                    callback(data)
                except Exception as e:
                    logger.error(f"Error in button callback: {e}")

    def _poll_buttons(self) -> None:
        """
        Poll button states in a loop.

        Runs in a separate thread and checks button states,
        detecting press types and firing appropriate callbacks.
        """
        logger.debug("Button polling started")

        while not self.stop_event.is_set():
            current_time = time.time()

            for button in Button:
                current_state = self._get_button_state(button)
                previous_state = self.button_states[button]

                # Button just pressed (transition from False to True)
                if current_state and not previous_state:
                    # Debounce
                    time.sleep(self.DEBOUNCE_TIME)
                    current_state = self._get_button_state(button)

                    if current_state:  # Still pressed after debounce
                        self.button_press_times[button] = current_time
                        self.button_states[button] = True
                        self.long_press_fired[button] = False
                        logger.trace(f"Button {button.value} pressed")

                # Button released (transition from True to False)
                elif not current_state and previous_state:
                    press_time = self.button_press_times[button]
                    self.button_states[button] = False

                    if press_time:
                        press_duration = current_time - press_time

                        # Don't fire PRESS if LONG_PRESS already fired
                        if not self.long_press_fired[button]:
                            # Map button to action and fire
                            action = self.mapping.get(button)
                            if action:
                                self._fire_action(action, {"button": button.value})

                        self.button_press_times[button] = None
                        logger.trace(f"Button {button.value} released after {press_duration:.2f}s")

                # Button held down - check for long press
                elif current_state and previous_state:
                    press_time = self.button_press_times[button]
                    if press_time and not self.long_press_fired[button]:
                        hold_duration = current_time - press_time
                        if hold_duration >= self.LONG_PRESS_TIME:
                            # Check for long press mapping
                            long_action = self.LONG_PRESS_MAPPING.get(button)
                            if long_action:
                                self._fire_action(long_action, {
                                    "button": button.value,
                                    "long_press": True
                                })
                            self.long_press_fired[button] = True

            time.sleep(0.01)  # 10ms polling rate

        logger.debug("Button polling stopped")
