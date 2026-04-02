"""
Input Hardware Abstraction Layer (HAL) for YoyoPod.

Defines the abstract interface for all input adapters and semantic input actions.
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Callable, List, Optional, Any
from loguru import logger


class InteractionProfile(Enum):
    """
    High-level interaction profiles derived from available hardware.

    STANDARD covers multi-button devices and simulation, while ONE_BUTTON is
    the Whisplay-native single-button navigation model.
    """

    STANDARD = "standard"
    ONE_BUTTON = "one_button"


class InputAction(Enum):
    """
    Semantic input actions independent of hardware.

    These represent user intent rather than physical input methods,
    allowing the same screen code to work with buttons, voice, touch, etc.
    """

    # Navigation actions
    ADVANCE = "advance"         # Move to the next item in a one-button flow
    SELECT = "select"           # Select/Confirm current item
    BACK = "back"               # Go back/Cancel
    UP = "up"                   # Navigate up in lists
    DOWN = "down"               # Navigate down in lists
    LEFT = "left"               # Navigate left / Previous
    RIGHT = "right"             # Navigate right / Next

    # Application actions
    MENU = "menu"               # Open menu
    HOME = "home"               # Go to home screen

    # Playback actions
    PLAY_PAUSE = "play_pause"   # Toggle playback
    NEXT_TRACK = "next_track"   # Skip to next track
    PREV_TRACK = "prev_track"   # Go to previous track
    VOLUME_UP = "volume_up"     # Increase volume
    VOLUME_DOWN = "volume_down" # Decrease volume

    # VoIP actions
    CALL_ANSWER = "call_answer"     # Answer incoming call
    CALL_REJECT = "call_reject"     # Reject incoming call
    CALL_HANGUP = "call_hangup"     # End active call

    # PTT (Push-to-Talk) actions
    PTT_PRESS = "ptt_press"         # PTT button pressed
    PTT_RELEASE = "ptt_release"     # PTT button released

    # Voice actions
    VOICE_COMMAND = "voice_command"  # Voice command received (with data)


class InputHAL(ABC):
    """
    Abstract base class for all input adapters.

    Each input method (buttons, voice, touch, etc.) implements this interface
    to provide a consistent API for the InputManager.
    """

    @abstractmethod
    def start(self) -> None:
        """
        Start input processing.

        This should initialize hardware, start polling threads,
        or register event listeners as needed.
        """
        pass

    @abstractmethod
    def stop(self) -> None:
        """
        Stop input processing.

        This should clean up resources, stop threads, and
        unregister event listeners.
        """
        pass

    @abstractmethod
    def on_action(
        self,
        action: InputAction,
        callback: Callable[[Optional[Any]], None]
    ) -> None:
        """
        Register a callback for an input action.

        Args:
            action: Semantic action to listen for
            callback: Function to call when action occurs.
                     Receives optional data dict with action-specific information.

        Example:
            def on_select(data):
                print(f"Item selected: {data}")

            adapter.on_action(InputAction.SELECT, on_select)
        """
        pass

    @abstractmethod
    def clear_callbacks(self) -> None:
        """
        Clear all registered callbacks.

        Called when switching screens or cleaning up.
        """
        pass

    def get_capabilities(self) -> List[InputAction]:
        """
        Return list of supported actions.

        Override this to indicate which actions this adapter can generate.
        Default implementation returns empty list (unknown capabilities).

        Returns:
            List of InputAction values this adapter supports

        Example:
            return [
                InputAction.SELECT,
                InputAction.BACK,
                InputAction.UP,
                InputAction.DOWN,
            ]
        """
        return []

    def _fire_action(self, action: InputAction, data: Optional[Any] = None) -> None:
        """
        Fire callbacks for an action (internal helper).

        This is typically called by adapter implementations when they
        detect an input event and need to notify registered callbacks.

        Args:
            action: Action that occurred
            data: Optional data dict with action-specific information
        """
        # Subclasses should implement callback storage and firing
        raise NotImplementedError("Subclass must implement _fire_action")
