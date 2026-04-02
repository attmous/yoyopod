"""
Screens module for YoyoPod UI.

Provides screen implementations organized by feature:
- base: Screen base class
- manager: ScreenManager for navigation
- navigation: Home and Menu screens
- music: Now Playing and Playlist screens
- voip: Call-related screens
"""

# Base screen class
from yoyopy.ui.screens.base import Screen

# Screen manager
from yoyopy.ui.screens.manager import ScreenManager
from yoyopy.ui.screens.router import NavigationRequest, ScreenRouter

# Navigation screens
from yoyopy.ui.screens.navigation import HubScreen, HomeScreen, MenuScreen

# Music screens
from yoyopy.ui.screens.music import NowPlayingScreen, PlaylistScreen

# VoIP screens
from yoyopy.ui.screens.voip import (
    CallScreen,
    IncomingCallScreen,
    OutgoingCallScreen,
    InCallScreen,
    ContactListScreen,
)

__all__ = [
    # Base & Manager
    'Screen',
    'ScreenManager',
    'NavigationRequest',
    'ScreenRouter',
    # Navigation
    'HubScreen',
    'HomeScreen',
    'MenuScreen',
    # Music
    'NowPlayingScreen',
    'PlaylistScreen',
    # VoIP
    'CallScreen',
    'IncomingCallScreen',
    'OutgoingCallScreen',
    'InCallScreen',
    'ContactListScreen',
]
