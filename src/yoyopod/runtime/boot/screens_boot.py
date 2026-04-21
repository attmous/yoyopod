"""Screen construction and registration during startup."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from yoyopod.coordinators import AppRuntimeState
from yoyopod.ui.input import InteractionProfile

if TYPE_CHECKING:
    from yoyopod.app import YoyoPodApp


class ScreensBoot:
    """Build screen objects and resolve initial navigation state."""

    def __init__(self, app: "YoyoPodApp", *, logger: Any) -> None:
        self.app = app
        self.logger = logger

    def setup_screens(self) -> bool:
        """Create and register all screens."""
        self.logger.info("Setting up screens...")

        try:
            from yoyopod.ui.bootstrap import build_and_register_screens

            build_and_register_screens(self.app, logger=self.logger)
            assert self.app.screen_manager is not None
            screen_manager = self.app.screen_manager
            initial_screen = self.get_initial_screen_name()
            screen_manager.push_screen(initial_screen)
            self.app._ui_state = self.get_initial_ui_state()
            self.logger.info(f"  Initial route resolved to {initial_screen}")
            self.logger.info(f"  Initial screen confirmed as {initial_screen}")
            self.logger.info("  Initial screen set")
            return True
        except Exception:
            self.logger.exception("Failed to setup screens")
            return False

    def get_interaction_profile(self) -> InteractionProfile:
        """Return the active hardware interaction profile."""
        if self.app.input_manager is not None:
            return self.app.input_manager.interaction_profile
        if self.app.context is not None:
            return self.app.context.interaction_profile
        return InteractionProfile.STANDARD

    def get_initial_screen_name(self) -> str:
        """Return the root screen for the active interaction profile."""
        if self.get_interaction_profile() == InteractionProfile.ONE_BUTTON:
            return "hub"
        return "menu"

    def get_initial_ui_state(self) -> AppRuntimeState:
        """Return the base runtime state for the active interaction profile."""
        if self.get_interaction_profile() == InteractionProfile.ONE_BUTTON:
            return AppRuntimeState.HUB
        return AppRuntimeState.MENU
