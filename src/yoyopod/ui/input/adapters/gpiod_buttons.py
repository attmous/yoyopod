"""
Four-button input adapter using gpiod (libgpiod).

Reads physical buttons via Linux GPIO character device instead of
RPi.GPIO or displayhatmini. Designed for non-Pi boards where the
Pimoroni Display HAT Mini is connected.

Button mapping matches FourButtonInputAdapter:
  A -> SELECT, B -> BACK (long: HOME), X -> UP, Y -> DOWN
"""

from __future__ import annotations

import select
import time
from collections import defaultdict
from datetime import datetime
from enum import Enum
from threading import Event, Thread
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from yoyopod.ui.input.hal import InputAction, InputHAL

from yoyopod.ui.input.gpiod_compat import (
    HAS_GPIOD,
    get_event_fd,
    open_chip,
    read_edge_events,
    request_input,
    request_input_events,
)


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
_POLL_INTERVAL = 0.03
_EDGE_IDLE_WAIT_TIMEOUT = 0.5
_EDGE_EVENT_RISING = {"rising", "rising_edge", "line_event_rising_edge", "edge_rising", "1"}
_EDGE_EVENT_FALLING = {"falling", "falling_edge", "line_event_falling_edge", "edge_falling", "2"}


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
        self._line_event_fds: dict[Button, int] = {}

        # Button state tracking
        self._raw_button_states: dict[Button, bool] = {b: False for b in Button}
        self._transition_times: dict[Button, Optional[float]] = {b: None for b in Button}
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
                chip = open_chip(chip_name)
                self._chips.append(chip)
                line = self._request_line(chip, line_offset, button)
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

    def _request_line(self, chip: object, line_offset: int, button: Button) -> object:
        """Request one GPIO line, preferring both-edge events when supported."""
        consumer = f"pimoroni-btn-{button.value}"

        try:
            line = request_input_events(chip, line_offset, consumer)
        except Exception as exc:
            logger.debug(
                "Falling back to polled GPIO input for button {}: {}",
                button.value,
                exc,
            )
            return request_input(chip, line_offset, consumer)

        event_fd = get_event_fd(line)
        if event_fd is None:
            logger.debug(
                "GPIO edge events unavailable for button {}; using polling loop",
                button.value,
            )
            return line

        self._line_event_fds[button] = event_fd
        return line

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

    def _observe_raw_state(self, button: Button, current_state: bool, observed_at: float) -> None:
        """Track raw GPIO edges and start a debounce window when the level changes."""
        if current_state == self._raw_button_states[button]:
            return

        self._raw_button_states[button] = current_state
        self._transition_times[button] = observed_at

    def _advance_button_state(self, button: Button, current_time: float) -> None:
        """Promote debounced raw state changes into semantic button actions."""
        transition_started_at = self._transition_times[button]
        stable_state = self._button_states[button]
        raw_state = self._raw_button_states[button]

        if transition_started_at is not None and (current_time - transition_started_at) >= _DEBOUNCE_TIME:
            self._transition_times[button] = None
            if raw_state != stable_state:
                if raw_state:
                    self._button_states[button] = True
                    self._press_times[button] = transition_started_at
                    self._long_fired[button] = False
                else:
                    self._button_states[button] = False
                    press_time = self._press_times[button]
                    if press_time is not None and not self._long_fired[button]:
                        action = _PRESS_MAPPING.get(button)
                        if action:
                            self._fire_action(action, {"button": button.value})
                    self._press_times[button] = None

        press_time = self._press_times[button]
        if self._button_states[button] and press_time is not None and not self._long_fired[button]:
            if current_time - press_time >= _LONG_PRESS_TIME:
                long_action = _LONG_PRESS_MAPPING.get(button)
                if long_action:
                    self._fire_action(
                        long_action,
                        {"button": button.value, "long_press": True},
                    )
                self._long_fired[button] = True

    def _next_poll_timeout(self, current_time: float) -> float:
        """Return the next timeout for the fallback polling loop."""
        deadlines = [_POLL_INTERVAL]

        for transition_started_at in self._transition_times.values():
            if transition_started_at is None:
                continue
            deadlines.append(
                max(0.0, _DEBOUNCE_TIME - (current_time - transition_started_at))
            )

        for button in Button:
            press_time = self._press_times[button]
            if press_time is None or not self._button_states[button] or self._long_fired[button]:
                continue
            deadlines.append(
                max(0.0, _LONG_PRESS_TIME - (current_time - press_time))
            )

        return min(deadlines)

    def _next_event_timeout(self, current_time: float) -> float:
        """Return the next timeout for the edge-driven wait loop."""
        deadlines: list[float] = []

        for transition_started_at in self._transition_times.values():
            if transition_started_at is None:
                continue
            deadlines.append(
                max(0.0, _DEBOUNCE_TIME - (current_time - transition_started_at))
            )

        for button in Button:
            press_time = self._press_times[button]
            if press_time is None or not self._button_states[button] or self._long_fired[button]:
                continue
            deadlines.append(
                max(0.0, _LONG_PRESS_TIME - (current_time - press_time))
            )

        if deadlines:
            return min(deadlines)
        return _EDGE_IDLE_WAIT_TIMEOUT

    def _poll_line_states(self, current_time: float) -> None:
        """Update button state using a periodic GPIO read loop."""
        for button in Button:
            if self.simulate and button not in self._lines:
                continue
            current_state = self._read_button(button)
            self._observe_raw_state(button, current_state, current_time)
            self._advance_button_state(button, current_time)

    def _seed_event_loop_states(self, observed_at: float) -> None:
        """Prime raw/stable state from live GPIO levels before waiting on edges."""
        for button in Button:
            if button not in self._lines:
                continue

            current_state = self._read_button(button)
            self._raw_button_states[button] = current_state
            self._button_states[button] = current_state
            self._transition_times[button] = None
            self._long_fired[button] = False
            self._press_times[button] = observed_at if current_state else None

    def _edge_event_state(self, event: object) -> bool | None:
        """Translate a gpiod edge-event object into the adapter's pressed state."""
        for attr_name in ("event_type", "type"):
            edge_type = getattr(event, attr_name, None)
            state = self._edge_type_to_pressed_state(edge_type)
            if state is not None:
                return state

        for attr_name in ("rising_edge", "is_rising_edge"):
            value = getattr(event, attr_name, None)
            if value is True:
                return False
            if value is False:
                return True

        for attr_name in ("falling_edge", "is_falling_edge"):
            value = getattr(event, attr_name, None)
            if value is True:
                return True
            if value is False:
                return False

        return None

    def _edge_event_timestamp_seconds(self, event: object) -> float | None:
        """Extract an event timestamp as seconds without assuming a clock domain."""
        timestamp_ns = getattr(event, "timestamp_ns", None)
        if isinstance(timestamp_ns, int):
            return timestamp_ns / 1_000_000_000

        timestamp = getattr(event, "timestamp", None)
        if isinstance(timestamp, datetime):
            return timestamp.timestamp()
        if isinstance(timestamp, (int, float)):
            return float(timestamp)

        sec = getattr(event, "sec", None)
        nsec = getattr(event, "nsec", None)
        if isinstance(sec, int) and isinstance(nsec, int):
            return sec + (nsec / 1_000_000_000)

        return None

    def _edge_event_observed_at(
        self,
        event: object,
        fallback: float,
        first_timestamp: float | None,
    ) -> float:
        """Project event ordering onto the local monotonic clock used by the FSM."""
        timestamp_seconds = self._edge_event_timestamp_seconds(event)
        if timestamp_seconds is None or first_timestamp is None:
            return fallback

        return fallback + max(0.0, timestamp_seconds - first_timestamp)

    def _edge_type_to_pressed_state(self, edge_type: object) -> bool | None:
        """Map gpiod edge direction identifiers onto active-low pressed state."""
        if edge_type is None:
            return None

        normalized = str(edge_type).rsplit(".", 1)[-1].lower()
        if normalized in _EDGE_EVENT_RISING:
            return False
        if normalized in _EDGE_EVENT_FALLING:
            return True
        return None

    def _apply_edge_events(self, button: Button, line: object, observed_at: float) -> None:
        """Replay drained edge transitions without collapsing them into one sampled level."""
        events = read_edge_events(line)
        if not events:
            self._observe_raw_state(button, self._read_button(button), observed_at)
            return

        first_timestamp = None
        for event in events:
            timestamp_seconds = self._edge_event_timestamp_seconds(event)
            if timestamp_seconds is not None:
                first_timestamp = timestamp_seconds
                break

        for event in events:
            event_at = self._edge_event_observed_at(event, observed_at, first_timestamp)
            self._advance_button_state(button, event_at)
            event_state = self._edge_event_state(event)
            if event_state is None:
                event_state = self._read_button(button)
            self._observe_raw_state(button, event_state, event_at)
            self._advance_button_state(button, event_at)

    def _event_wait_loop(self) -> None:
        """Block on GPIO edge file descriptors so idle threads stay asleep."""
        fd_to_button = {fd: button for button, fd in self._line_event_fds.items()}
        self._seed_event_loop_states(time.monotonic())

        while not self._stop_event.is_set():
            current_time = time.monotonic()
            timeout = self._next_event_timeout(current_time)

            try:
                ready, _, _ = select.select(list(fd_to_button), [], [], timeout)
            except OSError as exc:
                logger.warning("GPIO edge wait failed; falling back to polled reads: {}", exc)
                self._polling_loop()
                return

            # Some buttons may have new edges while others only need their existing
            # debounce or long-press deadlines advanced. Reusing one monotonic
            # timestamp keeps every button in this wake cycle ordered against the
            # same "now", so unready buttons can safely advance without a fresh read.
            observed_at = time.monotonic()
            for fd in ready:
                button = fd_to_button.get(fd)
                if button is None:
                    continue
                line = self._lines.get(button)
                if line is None:
                    continue
                try:
                    self._apply_edge_events(button, line, observed_at)
                except Exception as exc:
                    logger.debug(
                        "Failed to drain GPIO edge events for button {}; sampling level directly: {}",
                        button.value,
                        exc,
                    )
                    self._observe_raw_state(button, self._read_button(button), observed_at)

            for button in Button:
                self._advance_button_state(button, observed_at)

    def _polling_loop(self) -> None:
        """Fallback polling path for runtimes without GPIO edge waits."""
        while not self._stop_event.is_set():
            current_time = time.monotonic()
            self._poll_line_states(current_time)
            self._stop_event.wait(self._next_poll_timeout(current_time))

    def _poll_loop(self) -> None:
        """Dispatch to the lowest-churn GPIO wait loop available on this runtime."""
        if self._line_event_fds and len(self._line_event_fds) == len(self._lines):
            self._event_wait_loop()
            return

        self._polling_loop()
