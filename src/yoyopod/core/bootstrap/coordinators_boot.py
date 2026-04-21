"""Coordinator-runtime construction during startup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yoyopod.coordinators import (
    AppRuntimeState,
    CallCoordinator,
    CoordinatorRuntime,
    PlaybackCoordinator,
    PowerCoordinator,
    ScreenCoordinator,
)
from yoyopod.core import ScreenChangedEvent

if TYPE_CHECKING:
    from yoyopod.core.application import YoyoPodApp


class CoordinatorsBoot:
    """Build coordinator helpers around the initialized runtime."""

    def __init__(self, app: "YoyoPodApp") -> None:
        self.app = app

    def ensure_coordinators(self) -> None:
        """Create the coordinator runtime once the screens and managers exist."""

        if self.app.coordinator_runtime is not None:
            return

        assert self.app.music_fsm is not None
        assert self.app.call_fsm is not None
        assert self.app.call_interruption_policy is not None
        assert self.app.context is not None
        current_screen = (
            self.app.screen_manager.get_current_screen()
            if self.app.screen_manager is not None
            else None
        )
        current_route_name = current_screen.route_name if current_screen is not None else None
        initial_ui_state = (
            CoordinatorRuntime.ui_state_for_screen_name(current_route_name)
            or AppRuntimeState.IDLE
        )
        self.app.coordinator_runtime = CoordinatorRuntime(
            music_fsm=self.app.music_fsm,
            call_fsm=self.app.call_fsm,
            call_interruption_policy=self.app.call_interruption_policy,
            screen_manager=self.app.screen_manager,
            music_backend=self.app.music_backend,
            power_manager=self.app.power_manager,
            now_playing_screen=self.app.now_playing_screen,
            call_screen=self.app.call_screen,
            power_screen=self.app.power_screen,
            incoming_call_screen=self.app.incoming_call_screen,
            outgoing_call_screen=self.app.outgoing_call_screen,
            in_call_screen=self.app.in_call_screen,
            config_manager=self.app.config_manager,
            context=self.app.context,
            ui_state=initial_ui_state,
            voip_ready=self.app._voip_registered,
        )
        self.app.screen_coordinator = ScreenCoordinator(self.app.coordinator_runtime)
        self.app.call_coordinator = CallCoordinator(
            runtime=self.app.coordinator_runtime,
            screen_coordinator=self.app.screen_coordinator,
            auto_resume_after_call=self.app.auto_resume_after_call,
            call_history_store=self.app.call_history_store,
            initial_voip_registered=self.app._voip_registered,
        )
        self.app.playback_coordinator = PlaybackCoordinator(
            runtime=self.app.coordinator_runtime,
            screen_coordinator=self.app.screen_coordinator,
            local_music_service=self.app.local_music_service,
        )
        self.app.power_coordinator = PowerCoordinator(
            runtime=self.app.coordinator_runtime,
            screen_coordinator=self.app.screen_coordinator,
            context=self.app.context,
            cloud_manager=self.app.cloud_manager,
        )
        if self.app.screen_manager is not None:
            self.app.screen_manager.on_screen_changed = (
                lambda screen_name: self.app.event_bus.publish(
                    ScreenChangedEvent(screen_name=screen_name)
                )
            )
            self.app.event_bus.publish(ScreenChangedEvent(screen_name=current_route_name))
