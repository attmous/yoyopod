"""Shared coordinator registry state for YoyoPod."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from loguru import logger

from yoyopod.integrations.call import (
    CallFSM,
    CallInterruptionPolicy,
    CallSessionState,
)
from yoyopod.integrations.music import MusicFSM, MusicState

if TYPE_CHECKING:
    from yoyopod.backends.music import MusicBackend
    from yoyopod.config import ConfigManager
    from yoyopod.core import AppContext
    from yoyopod.integrations.power import PowerManager
    from yoyopod.integrations.power.models import PowerSnapshot
    from yoyopod.ui.screens.manager import ScreenManager
    from yoyopod.ui.screens.music.now_playing import NowPlayingScreen
    from yoyopod.ui.screens.system.power import PowerScreen
    from yoyopod.ui.screens.voip.in_call import InCallScreen
    from yoyopod.ui.screens.voip.incoming_call import IncomingCallScreen
    from yoyopod.ui.screens.voip.outgoing_call import OutgoingCallScreen
    from yoyopod.ui.screens.voip.quick_call import CallScreen


class AppRuntimeState(Enum):
    """Derived application state used by the production coordinator path."""

    IDLE = "idle"
    HUB = "hub"
    MENU = "menu"
    PLAYING = "playing"
    PAUSED = "paused"
    SETTINGS = "settings"
    PLAYLIST = "playlist"
    PLAYLIST_BROWSER = "playlist_browser"
    POWER = "power"
    CALL_IDLE = "call_idle"
    CALL_INCOMING = "call_incoming"
    CALL_OUTGOING = "call_outgoing"
    CALL_ACTIVE = "call_active"
    CONNECTING = "connecting"
    ERROR = "error"
    PLAYING_WITH_VOIP = "playing_with_voip"
    PAUSED_BY_CALL = "paused_by_call"
    CALL_ACTIVE_MUSIC_PAUSED = "call_active_music_paused"


@dataclass(frozen=True, slots=True)
class AppStateChange:
    """Describe a derived app-state refresh."""

    previous_state: AppRuntimeState
    current_state: AppRuntimeState
    trigger: str

    @property
    def changed(self) -> bool:
        """Return True when the derived app state changed."""
        return self.previous_state != self.current_state

    def entered(self, state: AppRuntimeState) -> bool:
        """Return True when this refresh entered the provided state."""
        return self.changed and self.current_state == state


@dataclass(slots=True)
class CoordinatorRuntime:
    """Shared app runtime references used by coordinator modules."""

    music_fsm: MusicFSM
    call_fsm: CallFSM
    call_interruption_policy: CallInterruptionPolicy
    screen_manager: ScreenManager | None
    power_manager: PowerManager | None
    now_playing_screen: NowPlayingScreen | None
    call_screen: CallScreen | None
    power_screen: PowerScreen | None
    incoming_call_screen: IncomingCallScreen | None
    outgoing_call_screen: OutgoingCallScreen | None
    in_call_screen: InCallScreen | None
    config_manager: ConfigManager | None
    music_backend: MusicBackend | None = None
    context: AppContext | None = None
    ui_state: AppRuntimeState = AppRuntimeState.IDLE
    voip_ready: bool = False
    power_available: bool = False
    power_snapshot: PowerSnapshot | None = None
    current_app_state: AppRuntimeState = field(init=False)
    previous_app_state: AppRuntimeState | None = field(init=False, default=None)
    state_history: list[AppRuntimeState] = field(init=False, default_factory=list)

    _UI_STATES = {
        AppRuntimeState.IDLE,
        AppRuntimeState.HUB,
        AppRuntimeState.MENU,
        AppRuntimeState.SETTINGS,
        AppRuntimeState.PLAYLIST,
        AppRuntimeState.PLAYLIST_BROWSER,
        AppRuntimeState.POWER,
        AppRuntimeState.CALL_IDLE,
        AppRuntimeState.CONNECTING,
        AppRuntimeState.ERROR,
    }
    _STATE_BY_SCREEN_NAME = {
        "home": AppRuntimeState.IDLE,
        "hub": AppRuntimeState.HUB,
        "menu": AppRuntimeState.MENU,
        "listen": AppRuntimeState.PLAYLIST_BROWSER,
        "ask": AppRuntimeState.SETTINGS,
        "playlists": AppRuntimeState.PLAYLIST_BROWSER,
        "power": AppRuntimeState.POWER,
        "call": AppRuntimeState.CALL_IDLE,
        "contacts": AppRuntimeState.CALL_IDLE,
    }

    def __post_init__(self) -> None:
        self.current_app_state = self._derive_state()
        self.state_history = [self.current_app_state]

    def _derive_state(self) -> AppRuntimeState:
        """Derive the current application state from the split FSMs."""
        if self.call_fsm.state == CallSessionState.INCOMING:
            return AppRuntimeState.CALL_INCOMING

        if self.call_fsm.state == CallSessionState.OUTGOING:
            return AppRuntimeState.CALL_OUTGOING

        if self.call_fsm.state == CallSessionState.ACTIVE:
            if self.call_interruption_policy.music_interrupted_by_call:
                return AppRuntimeState.CALL_ACTIVE_MUSIC_PAUSED
            return AppRuntimeState.CALL_ACTIVE

        if (
            self.call_interruption_policy.music_interrupted_by_call
            and self.music_fsm.state == MusicState.PAUSED
        ):
            return AppRuntimeState.PAUSED_BY_CALL

        if self.music_fsm.state == MusicState.PLAYING:
            if self.voip_ready:
                return AppRuntimeState.PLAYING_WITH_VOIP
            return AppRuntimeState.PLAYING

        if self.music_fsm.state == MusicState.PAUSED:
            return AppRuntimeState.PAUSED

        return self.ui_state

    def sync_app_state(self, trigger: str = "sync") -> AppStateChange:
        """Refresh the derived app state after coordinator mutations."""
        previous_state = self.current_app_state
        current_state = self._derive_state()

        if current_state != previous_state:
            self.previous_app_state = previous_state
            self.current_app_state = current_state
            self.state_history.append(current_state)
            if len(self.state_history) > 50:
                self.state_history = self.state_history[-50:]

            logger.info(
                "Coordinator state: {} -> {} (trigger: {})",
                previous_state.value,
                current_state.value,
                trigger,
            )

        return AppStateChange(
            previous_state=previous_state,
            current_state=self.current_app_state,
            trigger=trigger,
        )

    def set_ui_state(
        self,
        state: AppRuntimeState,
        trigger: str = "ui_state",
    ) -> AppStateChange:
        """Update the base UI state used when music and calls are idle."""
        if state not in self._UI_STATES:
            raise ValueError(f"{state.value} is not a base UI state")

        self.ui_state = state
        return self.sync_app_state(trigger)

    def set_voip_ready(self, ready: bool, trigger: str = "voip_ready") -> AppStateChange:
        """Store whether VoIP is ready and refresh the derived state."""
        self.voip_ready = ready
        actual_trigger = trigger if ready else "voip_unavailable"
        return self.sync_app_state(actual_trigger)

    def set_power_snapshot(self, snapshot: PowerSnapshot) -> None:
        """Retain the latest power snapshot for coordinator consumers."""
        self.power_snapshot = snapshot
        self.power_available = snapshot.available

    def set_power_available(self, available: bool) -> None:
        """Retain current power backend availability."""
        self.power_available = available

    def sync_ui_state_for_screen(self, screen_name: str | None) -> AppStateChange | None:
        """Update the base UI state for non-call overlay screens."""
        resolved_state = self.ui_state_for_screen_name(screen_name)
        if resolved_state is None:
            return None

        return self.set_ui_state(resolved_state, trigger=f"screen:{screen_name}")

    @classmethod
    def ui_state_for_screen_name(cls, screen_name: str | None) -> AppRuntimeState | None:
        """Return the base UI state mapped to one concrete route name."""

        if screen_name is None:
            return None
        return cls._STATE_BY_SCREEN_NAME.get(screen_name)

    def current_voip_manager(self) -> object | None:
        """Return the shared VoIP manager exposed by any registered call screen."""

        for screen in (
            self.call_screen,
            self.outgoing_call_screen,
            self.incoming_call_screen,
            self.in_call_screen,
        ):
            voip_manager = getattr(screen, "voip_manager", None)
            if voip_manager is not None:
                return voip_manager
        return None

    def current_caller_info(self) -> dict[str, str]:
        """Return the current caller/callee metadata from the shared VoIP manager."""

        voip_manager = self.current_voip_manager()
        if voip_manager is None:
            return {}
        return dict(voip_manager.get_caller_info())

    def current_call_duration_seconds(self) -> int:
        """Return the current call duration reported by the shared VoIP manager."""

        voip_manager = self.current_voip_manager()
        if voip_manager is None:
            return 0
        return int(voip_manager.get_call_duration())

    def get_state_name(self) -> str:
        """Return the current derived app-state name."""
        return self.current_app_state.value
