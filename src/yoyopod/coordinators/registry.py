"""Shared coordinator registry state for YoyoPod."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

from loguru import logger

from yoyopod.core import (
    CallFSM,
    CallInterruptionPolicy,
    CallSessionState,
    MusicFSM,
    MusicState,
)

if TYPE_CHECKING:
    from yoyopod.audio.music.backend import MusicBackend
    from yoyopod.config import ConfigManager
    from yoyopod.core import AppContext
    from yoyopod.power.manager import PowerManager
    from yoyopod.power.models import PowerSnapshot
    from yoyopod.ui.screens.manager import ScreenManager


class AppRuntimeState(Enum):
    """Derived application state used by the production coordinator path."""

    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    CALL_INCOMING = "call_incoming"
    CALL_OUTGOING = "call_outgoing"
    CALL_ACTIVE = "call_active"


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
    config_manager: ConfigManager | None
    music_backend: MusicBackend | None = None
    context: AppContext | None = None
    ui_state: str = AppRuntimeState.IDLE.value
    voip_ready: bool = False
    power_available: bool = False
    power_snapshot: PowerSnapshot | None = None
    current_app_state: AppRuntimeState = field(init=False)
    previous_app_state: AppRuntimeState | None = field(init=False, default=None)
    state_history: list[AppRuntimeState] = field(init=False, default_factory=list)

    _KNOWN_UI_ROUTES = {
        "home",
        "hub",
        "menu",
        "ask",
        "call",
        "contacts",
        "listen",
        "playlists",
        "playlist",
        "recent_tracks",
        "power",
        "now_playing",
        "incoming_call",
        "outgoing_call",
        "in_call",
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
            return AppRuntimeState.CALL_ACTIVE

        if self.music_fsm.state == MusicState.PLAYING:
            return AppRuntimeState.PLAYING

        if self.music_fsm.state == MusicState.PAUSED:
            return AppRuntimeState.PAUSED

        return AppRuntimeState.IDLE

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
        state: str | AppRuntimeState,
        trigger: str = "ui_state",
    ) -> AppStateChange:
        """Record the active UI route used when music/call FSMs are idle."""
        ui_state = state.value if isinstance(state, AppRuntimeState) else str(state)
        if ui_state not in self._KNOWN_UI_ROUTES:
            raise ValueError(f"{ui_state} is not a base UI route")

        self.ui_state = ui_state
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
        """Update the active UI route for non-overlay navigation events."""
        if not screen_name:
            return None

        screen_name = str(screen_name)
        if screen_name not in self._KNOWN_UI_ROUTES:
            return None

        return self.set_ui_state(screen_name, trigger=f"screen:{screen_name}")

    def get_state_name(self) -> str:
        """Return the current derived app-state name."""
        if self.current_app_state == AppRuntimeState.IDLE:
            return self.ui_state
        return self.current_app_state.value
