"""
Keyboard input adapter for YoyoPod simulation mode.

Provides keyboard input support using the pynput library for global
keyboard event capture. Works in both focused terminal and background.

Keyboard mapping:
- Enter / Space → SELECT
- Esc / Backspace → BACK
- Up Arrow / K → UP
- Down Arrow / J → DOWN

Author: YoyoPod Team
Date: 2025-11-30
"""

from yoyopod.ui.input.hal import InputHAL, InputAction
from typing import List, Callable, Any, Optional
from loguru import logger
import threading

# Try to import pynput
try:
    from pynput import keyboard
    HAS_PYNPUT = True
except ImportError:
    HAS_PYNPUT = False
    logger.warning("pynput library not available - keyboard input will not work")
    logger.warning("Install with: pip install pynput")


class KeyboardInputAdapter(InputHAL):
    """
    Keyboard input adapter for simulation mode.

    Captures keyboard events globally using pynput and maps them to
    semantic InputAction events. Allows control of YoyoPod from keyboard
    during simulation mode.

    Keyboard Mapping:
        Enter / Space    → SELECT (confirm/select)
        Esc / Backspace  → BACK (go back/cancel)
        Up Arrow / K     → UP (navigate up)
        Down Arrow / J   → DOWN (navigate down)

    Example:
        >>> adapter = KeyboardInputAdapter()
        >>> adapter.register_callback(InputAction.SELECT, lambda: print("Selected!"))
        >>> adapter.start()
        >>> # Press Enter to trigger callback
        >>> adapter.stop()
    """

    def __init__(self):
        """Initialize the keyboard input adapter."""
        self.callbacks: dict[InputAction, List[Callable]] = {}
        self.listener: Optional['keyboard.Listener'] = None
        self.running = False
        self._lock = threading.Lock()

        if not HAS_PYNPUT:
            logger.error("KeyboardInputAdapter requires pynput library")
            logger.error("Install with: pip install pynput")

        logger.info("Keyboard input adapter initialized")

    def get_capabilities(self) -> List[InputAction]:
        """
        Get list of input actions supported by this adapter.

        Returns:
            List of InputAction values that this adapter can generate
        """
        return [
            InputAction.SELECT,
            InputAction.BACK,
            InputAction.UP,
            InputAction.DOWN
        ]

    def on_action(
        self,
        action: InputAction,
        callback: Callable[[Optional[Any]], None]
    ) -> None:
        """
        Register a callback function for an input action.

        Args:
            action: The InputAction to listen for
            callback: Function to call when action occurs (receives optional data)
        """
        with self._lock:
            if action not in self.callbacks:
                self.callbacks[action] = []
            self.callbacks[action].append(callback)

        logger.debug(f"Registered callback for {action.value}")

    def clear_callbacks(self) -> None:
        """
        Clear all registered callbacks.

        Called when switching screens or cleaning up.
        """
        with self._lock:
            self.callbacks.clear()
        logger.debug("Cleared all keyboard callbacks")

    def _fire_action(self, action: InputAction, data: Optional[Any] = None) -> None:
        """
        Fire all registered callbacks for an action.

        Args:
            action: The InputAction that occurred
            data: Optional data to pass to callbacks
        """
        with self._lock:
            callbacks = self.callbacks.get(action, [])

        for callback in callbacks:
            try:
                callback(data)
            except Exception as e:
                logger.error(f"Error in callback for {action.value}: {e}")

    def _on_press(self, key):
        """
        Handle key press events from pynput.

        Args:
            key: Key object from pynput
        """
        action = None

        try:
            # Check for special keys
            if hasattr(key, 'name'):
                key_name = key.name
                if key_name == 'enter':
                    action = InputAction.SELECT
                elif key_name == 'esc':
                    action = InputAction.BACK
                elif key_name == 'backspace':
                    action = InputAction.BACK
                elif key_name == 'up':
                    action = InputAction.UP
                elif key_name == 'down':
                    action = InputAction.DOWN
                elif key_name == 'space':
                    action = InputAction.SELECT

            # Check for character keys
            elif hasattr(key, 'char'):
                char = key.char
                if char == 'k' or char == 'K':
                    action = InputAction.UP
                elif char == 'j' or char == 'J':
                    action = InputAction.DOWN

        except AttributeError:
            pass

        # Fire callbacks if action matched
        if action:
            logger.debug(f"Keyboard input: {action.value}")
            self._fire_action(action)

    def start(self) -> None:
        """
        Start keyboard input processing.

        Starts the pynput keyboard listener in a background thread.
        """
        if not HAS_PYNPUT:
            logger.error("Cannot start keyboard adapter: pynput not available")
            return

        if self.running:
            logger.warning("Keyboard adapter already running")
            return

        self.running = True

        # Create and start keyboard listener
        self.listener = keyboard.Listener(on_press=self._on_press)
        self.listener.start()

        logger.info("Keyboard input adapter started")
        logger.info("Keyboard shortcuts:")
        logger.info("  Enter/Space → SELECT")
        logger.info("  Esc/Backspace → BACK")
        logger.info("  ↑/K → UP")
        logger.info("  ↓/J → DOWN")

    def stop(self) -> None:
        """
        Stop keyboard input processing.

        Stops the pynput listener and cleans up resources.
        """
        if not self.running:
            return

        self.running = False

        if self.listener:
            self.listener.stop()
            self.listener = None

        logger.info("Keyboard input adapter stopped")


# Fallback adapter if pynput is not available
class DummyKeyboardAdapter(InputHAL):
    """
    Dummy keyboard adapter when pynput is not available.

    This adapter does nothing but satisfies the InputHAL interface,
    allowing the system to run without keyboard support.
    """

    def __init__(self):
        """Initialize dummy adapter."""
        logger.warning("Using dummy keyboard adapter (no pynput)")

    def get_capabilities(self) -> List[InputAction]:
        """Return empty list (no actions supported)."""
        return []

    def on_action(
        self,
        action: InputAction,
        callback: Callable[[Optional[Any]], None]
    ) -> None:
        """No-op callback registration."""
        pass

    def clear_callbacks(self) -> None:
        """No-op clear callbacks."""
        pass

    def start(self) -> None:
        """No-op start."""
        logger.warning("Keyboard input not available (install pynput)")

    def stop(self) -> None:
        """No-op stop."""
        pass


def get_keyboard_adapter() -> InputHAL:
    """
    Get keyboard input adapter (real or dummy based on pynput availability).

    Returns:
        KeyboardInputAdapter if pynput available, else DummyKeyboardAdapter

    Example:
        >>> adapter = get_keyboard_adapter()
        >>> adapter.start()
    """
    if HAS_PYNPUT:
        return KeyboardInputAdapter()
    else:
        return DummyKeyboardAdapter()
