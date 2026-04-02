"""
Input HAL for YoyoPod.

Provides hardware abstraction for various input methods:
- 4-button interface (Pimoroni Display HAT Mini)
- PTT button (Whisplay HAT)
- Voice commands (future)
- Touch screen (future)
"""

from yoyopy.ui.input.factory import get_input_manager
from yoyopy.ui.input.hal import InputAction, InputHAL, InteractionProfile
from yoyopy.ui.input.manager import InputManager

__all__ = [
    'InputHAL',
    'InputAction',
    'InteractionProfile',
    'InputManager',
    'get_input_manager',
]
