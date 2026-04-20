"""Regression coverage for relocated core module compatibility shims."""

from __future__ import annotations

from yoyopod.app_context import AppContext
from yoyopod.core import AppContext as CoreAppContext
from yoyopod.core.event_bus import EventBus as CoreEventBus
from yoyopod.core.events import TrackChangedEvent as CoreTrackChangedEvent
from yoyopod.core.fsm import MusicFSM as CoreMusicFSM
from yoyopod.core.runtime_state import VoiceState as CoreVoiceState
from yoyopod.core.setup_contract import (
    RUNTIME_REQUIRED_CONFIG_FILES as CORE_RUNTIME_REQUIRED_CONFIG_FILES,
)
from yoyopod.event_bus import EventBus
from yoyopod.events import TrackChangedEvent
from yoyopod.fsm import MusicFSM
from yoyopod.runtime_state import VoiceState
from yoyopod.setup_contract import RUNTIME_REQUIRED_CONFIG_FILES


def test_legacy_core_import_paths_resolve_to_relocated_symbols() -> None:
    """Legacy top-level imports should remain valid after the core package split."""

    assert AppContext is CoreAppContext
    assert EventBus is CoreEventBus
    assert TrackChangedEvent is CoreTrackChangedEvent
    assert MusicFSM is CoreMusicFSM
    assert VoiceState is CoreVoiceState
    assert RUNTIME_REQUIRED_CONFIG_FILES == CORE_RUNTIME_REQUIRED_CONFIG_FILES
