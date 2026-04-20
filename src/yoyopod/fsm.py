"""Compatibility exports for relocated FSM primitives."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from loguru import logger

from yoyopod.core.fsm import (
    CallFSM,
    CallInterruptionPolicy,
    CallSessionState,
    MusicFSM,
    MusicState,
)
