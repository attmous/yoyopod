"""
Screen and stack coordination helpers for YoyoPod.
"""

from __future__ import annotations

from loguru import logger

from yoyopy.coordinators.runtime import CoordinatorRuntime


class ScreenCoordinator:
    """Own small screen-stack and refresh operations for the app."""

    def __init__(self, runtime: CoordinatorRuntime) -> None:
        self.runtime = runtime

    def pop_call_screens(self) -> None:
        """Pop all call-related screens from the stack."""
        call_screens = [
            self.runtime.in_call_screen,
            self.runtime.incoming_call_screen,
            self.runtime.outgoing_call_screen,
        ]

        while self.runtime.screen_manager.current_screen in call_screens:
            self.runtime.screen_manager.pop_screen()
            if not self.runtime.screen_manager.screen_stack:
                break

        logger.debug("Call screens cleared from stack")

    def update_now_playing_if_needed(self) -> None:
        """Refresh the now playing screen for periodic progress updates."""
        if (
            self.runtime.screen_manager is None
            or self.runtime.now_playing_screen is None
            or self.runtime.screen_manager.current_screen != self.runtime.now_playing_screen
        ):
            return

        if self.runtime.music_backend and self.runtime.music_backend.is_connected:
            playback_state = self.runtime.music_backend.get_playback_state()
            if playback_state == "playing":
                self.runtime.now_playing_screen.render()

    def update_in_call_if_needed(self) -> None:
        """Refresh the in-call screen for live duration and mute updates."""
        if (
            self.runtime.screen_manager is not None
            and self.runtime.in_call_screen is not None
            and self.runtime.screen_manager.current_screen == self.runtime.in_call_screen
        ):
            self.runtime.in_call_screen.render()

    def update_power_screen_if_needed(self) -> None:
        """Refresh the power screen for live runtime metrics when visible."""
        if (
            self.runtime.screen_manager is not None
            and self.runtime.power_screen is not None
            and self.runtime.screen_manager.current_screen == self.runtime.power_screen
        ):
            self.runtime.power_screen.render()

    def refresh_current_screen(self) -> None:
        """Refresh whichever screen is currently visible."""
        if self.runtime.screen_manager is None:
            return

        current_screen = self.runtime.screen_manager.get_current_screen()
        if current_screen is None:
            return

        current_screen.render()
        logger.debug("  -> Current screen refreshed")

    def refresh_now_playing_screen(self) -> None:
        """Refresh the now playing screen if it is currently visible."""
        if self.runtime.screen_manager.current_screen == self.runtime.now_playing_screen:
            self.runtime.now_playing_screen.render()
            logger.debug("  → Now playing screen refreshed")

    def refresh_call_screen_if_visible(self) -> None:
        """Refresh the VoIP status screen if it is currently visible."""
        if self.runtime.screen_manager.current_screen == self.runtime.call_screen:
            self.runtime.call_screen.render()
            logger.debug("  → Call screen refreshed")

    def show_incoming_call(self, caller_address: str, caller_name: str) -> None:
        """Update and show the incoming call screen."""
        self.runtime.incoming_call_screen.caller_address = caller_address
        self.runtime.incoming_call_screen.caller_name = caller_name
        self.runtime.incoming_call_screen.ring_animation_frame = 0

        if self.runtime.screen_manager.current_screen != self.runtime.incoming_call_screen:
            self.runtime.screen_manager.push_screen("incoming_call")
            logger.info("  → Pushed incoming call screen")

    def show_in_call(self) -> None:
        """Show the active in-call screen if it is not already visible."""
        if self.runtime.screen_manager.current_screen != self.runtime.in_call_screen:
            self.runtime.screen_manager.push_screen("in_call")
            logger.info("  → Pushed in-call screen")
