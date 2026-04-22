"""
Input HAL for YoyoPod.

Provides hardware abstraction for various input methods:
- PTT button (Whisplay HAT)
- Simulation keyboard/web controls
- Voice commands (future)
- Touch screen (future)
"""

from yoyopod.ui.input.factory import get_input_manager
from yoyopod.ui.input.hal import InputAction, InputHAL, InteractionProfile
from yoyopod.ui.input.manager import InputManager

__all__ = [
    'InputHAL',
    'InputAction',
    'InteractionProfile',
    'InputManager',
    'get_input_manager',
]
