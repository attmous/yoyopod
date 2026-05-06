"""
Input adapter implementations.

Each adapter translates hardware-specific input (buttons, voice, touch)
into semantic InputActions.
"""

from yoyopod.ui.input.adapters.four_button import FourButtonInputAdapter
from yoyopod.ui.input.adapters.ptt_button import PTTInputAdapter
from yoyopod.ui.input.adapters.ptt_button_state import PTTButtonState, PTTButtonStateMachine
from yoyopod.ui.input.adapters.keyboard import KeyboardInputAdapter, get_keyboard_adapter

__all__ = [
    "FourButtonInputAdapter",
    "PTTInputAdapter",
    "PTTButtonState",
    "PTTButtonStateMachine",
    "KeyboardInputAdapter",
    "get_keyboard_adapter",
]
