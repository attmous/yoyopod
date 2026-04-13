"""
Four-button input adapter using gpiod (libgpiod).

Reads physical buttons via Linux GPIO character device instead of
RPi.GPIO or displayhatmini. Designed for non-Pi boards where the
Pimoroni Display HAT Mini is connected.

Button mapping matches FourButtonInputAdapter:
  A -> SELECT, B -> BACK (long: HOME), X -> UP, Y -> DOWN
"""

from __future__ import annotations

import time
from collections import defaultdict
from enum import Enum
from threading import Event, Thread
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from yoyopy.ui.input.hal import InputAction, InputHAL

try:
    import gpiod

    HAS_GPIOD = True
except ImportError:
    gpiod = None  # type: ignore[assignment]
    HAS_GPIOD = False


class Button(Enum):
    """Physical button identifiers."""

    A = "A"
    B = "B"
    X = "X"
    Y = "Y"


# Button-to-action mapping
_PRESS_MAPPING: dict[Button, InputAction] = {
    Button.A: InputAction.SELECT,
    Button.B: InputAction.BACK,
    Button.X: InputAction.UP,
    Button.Y: InputAction.DOWN,
}

_LONG_PRESS_MAPPING: dict[Button, InputAction] = {
    Button.B: InputAction.HOME,
}

# Timing constants (seconds)
_DEBOUNCE_TIME = 0.05
_LONG_PRESS_TIME = 1.0


class GpiodButtonAdapter(InputHAL):
    """Four-button input via gpiod with debounce and long-press detection."""

    def __init__(
        self,
        pin_config: dict[str, Any],
        simulate: bool = False,
    ) -> None:
        self.simulate = simulate or not HAS_GPIOD
        self.callbacks: Dict[InputAction, List[Callable]] = defaultdict(list)
        self.running = False
        self._poll_thread: Optional[Thread] = None
        self._stop_event = Event()

        # GPIO line handles keyed by Button
        self._lines: dict[Button, object] = {}
        self._chips: list[object] = []

        # Button state tracking
        self._button_states: dict[Button, bool] = {b: False for b in Button}
        self._press_times: dict[Button, Optional[float]] = {b: None for b in Button}
        self._long_fired: dict[Button, bool] = {b: False for b in Button}

        if not self.simulate:
            self._open_gpio_lines(pin_config)
        else:
            logger.debug("GpiodButtonAdapter running in simulation mode")

    def _open_gpio_lines(self, pin_config: dict[str, Any]) -> None:
        """Request GPIO lines for each button."""
        button_keys = [
            ("button_a", Button.A),
            ("button_b", Button.B),
            ("button_x", Button.X),
            ("button_y", Button.Y),
        ]

        for key, button in button_keys:
            pin = pin_config.get(key)
            if pin is None:
                logger.warning(
                    "No GPIO config for button {} (key={}), skipping",
                    button.value,
                    key,
                )
                continue

            chip_name = (
                pin.get("chip") if isinstance(pin, dict) else getattr(pin, "chip", None)
            )
            line_offset = (
                pin.get("line") if isinstance(pin, dict) else getattr(pin, "line", None)
            )
            if chip_name is None or line_offset is None:
                logger.warning(
                    "Incomplete GPIO config for button {}, skipping", button.value
                )
                continue

            try:
                chip = gpiod.Chip(chip_name)
                self._chips.append(chip)
                line = chip.get_line(line_offset)
                line.request(
                    consumer=f"pimoroni-btn-{button.value}",
                    type=gpiod.LINE_REQ_DIR_IN,
                    flags=gpiod.LINE_REQ_FLAG_BIAS_DISABLE,
                )
                self._lines[button] = line
                logger.debug(
                    "Button {} on {}:{}", button.value, chip_name, line_offset
                )
            except Exception as e:
                logger.warning(
                    "Failed to acquire GPIO for button {}: {}", button.value, e
                )

        logger.info(
            "GpiodButtonAdapter: {} of 4 buttons acquired", len(self._lines)
        )

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self._poll_thread = Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        logger.info("GpiodButtonAdapter started")

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        self._stop_event.set()
        if self._poll_thread:
            self._poll_thread.join(timeout=1.0)
        for line in self._lines.values():
            try:
                line.release()
            except Exception:
                pass
        for chip in self._chips:
            try:
                chip.close()
            except Exception:
                pass
        self._lines.clear()
        self._chips.clear()
        logger.info("GpiodButtonAdapter stopped")

    def on_action(
        self, action: InputAction, callback: Callable[[Optional[Any]], None]
    ) -> None:
        self.callbacks[action].append(callback)

    def clear_callbacks(self) -> None:
        self.callbacks.clear()

    def get_capabilities(self) -> List[InputAction]:
        caps = list(_PRESS_MAPPING.values())
        caps.extend(_LONG_PRESS_MAPPING.values())
        return list(set(caps))

    def _fire_action(self, action: InputAction, data: Optional[Any] = None) -> None:
        for cb in self.callbacks.get(action, []):
            try:
                cb(data)
            except Exception as e:
                logger.error("Error in button callback: {}", e)

    def _read_button(self, button: Button) -> bool:
        """Read a button GPIO line. Active-low: pressed = 0."""
        line = self._lines.get(button)
        if line is None:
            return False
        try:
            return line.get_value() == 0
        except Exception:
            return False

    def _poll_loop(self) -> None:
        """Poll button states at 10ms intervals with debounce and long-press."""
        while not self._stop_event.is_set():
            now = time.time()

            for button in Button:
                if self.simulate and button not in self._lines:
                    continue

                current = self._read_button(button)
                previous = self._button_states[button]

                # Press detected
                if current and not previous:
                    time.sleep(_DEBOUNCE_TIME)
                    current = self._read_button(button)
                    if current:
                        self._button_states[button] = True
                        self._press_times[button] = now
                        self._long_fired[button] = False

                # Release detected
                elif not current and previous:
                    self._button_states[button] = False
                    if (
                        self._press_times[button] is not None
                        and not self._long_fired[button]
                    ):
                        action = _PRESS_MAPPING.get(button)
                        if action:
                            self._fire_action(action, {"button": button.value})
                    self._press_times[button] = None

                # Held — check long press
                elif current and previous:
                    pt = self._press_times[button]
                    if pt is not None and not self._long_fired[button]:
                        if now - pt >= _LONG_PRESS_TIME:
                            long_action = _LONG_PRESS_MAPPING.get(button)
                            if long_action:
                                self._fire_action(
                                    long_action,
                                    {"button": button.value, "long_press": True},
                                )
                            self._long_fired[button] = True

            time.sleep(0.01)
