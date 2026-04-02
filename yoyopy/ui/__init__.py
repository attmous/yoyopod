"""
UI module for YoyoPod.

Provides display management, input handling, and screen navigation.
"""

# Display module
from yoyopy.ui.display import Display, DisplayHAL

# Input module
from yoyopy.ui.input import InputManager, InputAction, InteractionProfile

# Screens module
from yoyopy.ui.screens import (
    Screen,
    ScreenManager,
    HomeScreen,
    MenuScreen,
    NowPlayingScreen,
    PlaylistScreen,
    CallScreen,
    IncomingCallScreen,
    OutgoingCallScreen,
    InCallScreen,
    ContactListScreen,
)

__all__ = [
    # Display
    'Display',
    'DisplayHAL',
    # Input
    'InputManager',
    'InputAction',
    'InteractionProfile',
    # Screens
    'Screen',
    'ScreenManager',
    'HomeScreen',
    'MenuScreen',
    'NowPlayingScreen',
    'PlaylistScreen',
    'CallScreen',
    'IncomingCallScreen',
    'OutgoingCallScreen',
    'InCallScreen',
    'ContactListScreen',
]
