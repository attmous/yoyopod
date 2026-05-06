"""Shared theme tokens for YoYoPod screen rendering."""

from __future__ import annotations

from dataclasses import dataclass

Color = tuple[int, int, int]

BACKGROUND: Color = (42, 45, 53)
SURFACE: Color = (49, 52, 60)
SURFACE_RAISED: Color = (54, 58, 68)
SURFACE_BORDER: Color = (80, 85, 97)
FOOTER_BAR: Color = (31, 33, 39)
INK: Color = (255, 255, 255)
MUTED: Color = (180, 183, 190)
MUTED_DIM: Color = (122, 125, 132)
SUCCESS: Color = (61, 221, 83)
WARNING: Color = (255, 208, 0)
ERROR: Color = (255, 103, 93)
NEUTRAL: Color = (156, 163, 175)
FOOTER_SAFE_HEIGHT_PORTRAIT = 32
FOOTER_SAFE_HEIGHT_LANDSCAPE = 28
STATUS_SIDE_INSET_PORTRAIT = 16
STATUS_SIDE_INSET_LANDSCAPE = 10
STATUS_CLOCK_TOP_PORTRAIT = 7
STATUS_CLOCK_TOP_LANDSCAPE = 6
STATUS_TIME_FONT_SIZE = 11
STATUS_BATTERY_TOP_PORTRAIT = 9
STATUS_BATTERY_TOP_LANDSCAPE = 8
STATUS_ICON_BOTTOM_PORTRAIT = 20
STATUS_ICON_BOTTOM_LANDSCAPE = 16
STATUS_CLUSTER_GAP_PORTRAIT = 6
STATUS_CLUSTER_GAP_LANDSCAPE = 5
STATUS_BATTERY_SIDE_INSET_PORTRAIT = 18
STATUS_BATTERY_SIDE_INSET_LANDSCAPE = 10
STATUS_BATTERY_GAP_PORTRAIT = 28
STATUS_BATTERY_GAP_LANDSCAPE = 24
STATUS_SIGNAL_BAR_WIDTH = 3
STATUS_SIGNAL_BAR_GAP = 1
STATUS_SIGNAL_BAR_HEIGHTS = (4, 7, 10, 13)
STATUS_WIFI_ICON_WIDTH = 11
STATUS_WIFI_ICON_HEIGHT = 11
STATUS_WIFI_DOT_RADIUS = 1
STATUS_GPS_ICON_WIDTH = 8
STATUS_GPS_ICON_HEIGHT = 12
STATUS_GPS_RING_RADIUS = 3
STATUS_GPS_CENTER_RADIUS = 1
STATUS_VOIP_ICON_RADIUS = 3
HEADER_SIDE_INSET_PORTRAIT = 18
HEADER_SIDE_INSET_LANDSCAPE = 16


@dataclass(frozen=True, slots=True)
class ModeTheme:
    """Palette for one product mode."""

    key: str
    label: str
    accent: Color
    hero_end: Color
    accent_soft: Color
    accent_dim: Color


LISTEN = ModeTheme(
    key="listen",
    label="Listen",
    accent=(0, 255, 136),
    hero_end=(0, 204, 106),
    accent_soft=(0, 204, 106),
    accent_dim=(0, 108, 63),
)
TALK = ModeTheme(
    key="talk",
    label="Talk",
    accent=(0, 212, 255),
    hero_end=(0, 153, 255),
    accent_soft=(0, 153, 255),
    accent_dim=(0, 102, 158),
)
ASK = ModeTheme(
    key="ask",
    label="Ask",
    accent=(255, 208, 0),
    hero_end=(255, 170, 0),
    accent_soft=(255, 170, 0),
    accent_dim=(145, 102, 0),
)
SETUP = ModeTheme(
    key="setup",
    label="Setup",
    accent=(156, 163, 175),
    hero_end=(107, 114, 128),
    accent_soft=(107, 114, 128),
    accent_dim=(84, 90, 102),
)

THEMES = {
    "listen": LISTEN,
    "music": LISTEN,
    "playlists": LISTEN,
    "now_playing": LISTEN,
    "talk": TALK,
    "call": TALK,
    "contacts": TALK,
    "incoming": TALK,
    "outgoing": TALK,
    "in_call": TALK,
    "ask": ASK,
    "setup": SETUP,
    "power": SETUP,
    "menu": SETUP,
    "home": SETUP,
}


def theme_for(mode: str) -> ModeTheme:
    """Return the palette for a mode key."""

    return THEMES.get(mode, SETUP)
