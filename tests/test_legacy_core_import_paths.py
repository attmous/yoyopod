"""Regression coverage for relocated core module compatibility shims."""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

from yoyopod.audio.music.models import Track as MusicTrack
from yoyopod.app_context import (
    AppContext,
    InteractionProfile as AppContextInteractionProfile,
    PlaybackQueue as AppContextPlaybackQueue,
    Track as AppContextTrack,
)
from yoyopod.core import AppContext as CoreAppContext
from yoyopod.communication import CallState as CommunicationCallState
from yoyopod.communication import RegistrationState as CommunicationRegistrationState
from yoyopod.core.event_bus import EventBus as CoreEventBus
from yoyopod.core.event_bus import EventHandler as CoreEventHandler
from yoyopod.core.events import TrackChangedEvent as CoreTrackChangedEvent
from yoyopod.core.fsm import CallFSM as CoreCallFSM
from yoyopod.core.fsm import CallInterruptionPolicy as CoreCallInterruptionPolicy
from yoyopod.core.fsm import MusicFSM as CoreMusicFSM
from yoyopod.core.runtime_state import VoiceState as CoreVoiceState
from yoyopod.core.setup_contract import (
    RUNTIME_REQUIRED_CONFIG_FILES as CORE_RUNTIME_REQUIRED_CONFIG_FILES,
)
from yoyopod.runtime_state import PlaybackQueue as RuntimeStatePlaybackQueue
from yoyopod.runtime_state import Track as RuntimeStateTrack
from yoyopod.event_bus import EventBus, EventHandler
from yoyopod.events import CallState, RegistrationState, Track, TrackChangedEvent
from yoyopod.fsm import MusicFSM
from yoyopod.runtime_state import VoiceState
from yoyopod.setup_contract import Path as SetupContractPath
from yoyopod.setup_contract import RUNTIME_REQUIRED_CONFIG_FILES
from yoyopod.ui.input.hal import InteractionProfile
from yoyopod import EventBus as RootEventBus
from yoyopod import CallFSM as RootCallFSM
from yoyopod import MusicFSM as RootMusicFSM


def test_legacy_core_import_paths_resolve_to_relocated_symbols() -> None:
    """Legacy top-level imports should remain valid after the core package split."""

    assert AppContext is CoreAppContext
    assert EventBus is CoreEventBus
    assert EventHandler is CoreEventHandler
    assert CallState is CommunicationCallState
    assert RegistrationState is CommunicationRegistrationState
    assert Track is MusicTrack
    assert TrackChangedEvent is CoreTrackChangedEvent
    assert MusicFSM is CoreMusicFSM
    assert VoiceState is CoreVoiceState
    assert RUNTIME_REQUIRED_CONFIG_FILES == CORE_RUNTIME_REQUIRED_CONFIG_FILES
    assert AppContextPlaybackQueue is RuntimeStatePlaybackQueue
    assert AppContextTrack is RuntimeStateTrack
    assert AppContextInteractionProfile is InteractionProfile
    assert SetupContractPath is Path
    assert RootEventBus is EventBus
    assert RootMusicFSM is MusicFSM
    assert RootCallFSM is CoreCallFSM


def test_demo_entrypoints_keep_importing_legacy_shims(monkeypatch) -> None:
    """Demo modules that still import legacy paths should remain importable."""

    class DummyMopidyClient:
        pass

    class DummyRegistrationState:
        pass

    class DummyVoIPConfig:
        pass

    class DummyVoIPManager:
        pass

    mopidy_module = types.ModuleType("yoyopod.audio.mopidy_client")
    mopidy_module.MopidyClient = DummyMopidyClient
    monkeypatch.setitem(sys.modules, "yoyopod.audio.mopidy_client", mopidy_module)

    voip_module = types.ModuleType("yoyopod.voip")
    voip_module.RegistrationState = DummyRegistrationState
    voip_module.VoIPConfig = DummyVoIPConfig
    voip_module.VoIPManager = DummyVoIPManager
    monkeypatch.setitem(sys.modules, "yoyopod.voip", voip_module)

    for module_name in (
        "demos.demo_runtime_state",
        "demos.demo_interactive",
        "demos.demo_mopidy",
        "demos.demo_playlists",
        "demos.demo_voip",
    ):
        sys.modules.pop(module_name, None)

    runtime_demo = importlib.import_module("demos.demo_runtime_state")
    interactive_demo = importlib.import_module("demos.demo_interactive")
    mopidy_demo = importlib.import_module("demos.demo_mopidy")
    playlist_demo = importlib.import_module("demos.demo_playlists")
    voip_demo = importlib.import_module("demos.demo_voip")

    assert runtime_demo.AppContext is AppContext
    assert runtime_demo.CallFSM is CoreCallFSM
    assert runtime_demo.CallInterruptionPolicy is CoreCallInterruptionPolicy
    assert runtime_demo.MusicFSM is MusicFSM
    assert interactive_demo.AppContext is AppContext
    assert mopidy_demo.AppContext is AppContext
    assert playlist_demo.AppContext is AppContext
    assert voip_demo.AppContext is AppContext
