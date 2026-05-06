"""CLI-owned input contracts for Pi validation helpers."""

from __future__ import annotations

from enum import Enum


class InteractionProfile(Enum):
    """High-level interaction profiles derived from available hardware."""

    STANDARD = "standard"
    ONE_BUTTON = "one_button"


class InputAction(Enum):
    """Semantic input actions independent of hardware."""

    ADVANCE = "advance"
    SELECT = "select"
    BACK = "back"
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"

    MENU = "menu"
    HOME = "home"

    PLAY_PAUSE = "play_pause"
    NEXT_TRACK = "next_track"
    PREV_TRACK = "prev_track"
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"

    CALL_ANSWER = "call_answer"
    CALL_REJECT = "call_reject"
    CALL_HANGUP = "call_hangup"

    PTT_PRESS = "ptt_press"
    PTT_RELEASE = "ptt_release"

    VOICE_COMMAND = "voice_command"


__all__ = ["InputAction", "InteractionProfile"]
