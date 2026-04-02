"""
Shared runtime references for YoyoPod coordinators.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from loguru import logger

from yoyopy.fsm import (
    CallFSM,
    CallInterruptionPolicy,
    CallSessionState,
    MusicFSM,
    MusicState,
)

if TYPE_CHECKING:
    from yoyopy.audio.mopidy_client import MopidyClient
    from yoyopy.config import ConfigManager
    from yoyopy.ui.screens import (
        CallScreen,
        InCallScreen,
        IncomingCallScreen,
        NowPlayingScreen,
        OutgoingCallScreen,
        ScreenManager,
    )


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
    mopidy_client: MopidyClient | None
    now_playing_screen: NowPlayingScreen | None
    call_screen: CallScreen | None
    incoming_call_screen: IncomingCallScreen | None
    outgoing_call_screen: OutgoingCallScreen | None
    in_call_screen: InCallScreen | None
    config: dict[str, Any]
    config_manager: ConfigManager | None
    ui_state: AppRuntimeState = AppRuntimeState.IDLE
    voip_ready: bool = False
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
        AppRuntimeState.CALL_IDLE,
        AppRuntimeState.CONNECTING,
        AppRuntimeState.ERROR,
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

    def sync_ui_state_for_screen(self, screen_name: str | None) -> AppStateChange | None:
        """Update the base UI state for non-call overlay screens."""
        state_by_screen = {
            "home": AppRuntimeState.IDLE,
            "hub": AppRuntimeState.HUB,
            "menu": AppRuntimeState.MENU,
            "playlists": AppRuntimeState.PLAYLIST_BROWSER,
            "call": AppRuntimeState.CALL_IDLE,
            "contacts": AppRuntimeState.CALL_IDLE,
        }
        if screen_name is None or screen_name not in state_by_screen:
            return None

        return self.set_ui_state(state_by_screen[screen_name], trigger=f"screen:{screen_name}")

    def get_state_name(self) -> str:
        """Return the current derived app-state name."""
        return self.current_app_state.value
