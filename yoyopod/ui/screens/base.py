"""
Screen management for YoyoPod UI.

Provides base Screen class and concrete screen implementations
for different application states.
"""

from abc import ABC, abstractmethod
from typing import Optional, Any, TYPE_CHECKING
from loguru import logger

from yoyopod.ui.display import Display
from yoyopod.ui.input.hal import InteractionProfile
from yoyopod.ui.screens.router import NavigationRequest

if TYPE_CHECKING:
    from yoyopod.ui.screens.manager import ScreenManager
    from yoyopod.core import AppContext
    from yoyopod.ui.input import InputAction


class Screen(ABC):
    """
    Base class for all UI screens.

    Screens are responsible for rendering their content to the display
    and handling any screen-specific logic.
    """

    def __init__(
        self,
        display: Display,
        context: Optional["AppContext"] = None,
        name: str = "Screen",
        *,
        app: Any | None = None,
    ) -> None:
        """
        Initialize the screen.

        Args:
            display: Display controller instance
            context: Application context (optional)
            name: Screen name for logging
            app: Owning application shell or compatibility app (optional)
        """
        self.display = display
        self.app = app
        self.context = context if context is not None else getattr(app, "context", None)
        self.name = name
        self.screen_manager: Optional["ScreenManager"] = None
        self.route_name: Optional[str] = None
        self._pending_navigation: Optional[NavigationRequest] = None
        logger.debug(f"Screen '{name}' initialized")

    def set_screen_manager(self, manager: "ScreenManager") -> None:
        """Set the screen manager for navigation."""
        self.screen_manager = manager

    def set_route_name(self, route_name: str) -> None:
        """Set the registered route name for this screen."""
        self.route_name = route_name

    def set_context(self, context: "AppContext") -> None:
        """Set the application context."""
        self.context = context

    def set_app(self, app: Any) -> None:
        """Set the owning app and adopt its context when needed."""

        self.app = app
        if self.context is None:
            self.context = getattr(app, "context", None)

    def request_navigation(self, request: NavigationRequest) -> None:
        """Queue a navigation request for the screen manager to resolve."""
        self._pending_navigation = request

    def request_route(self, route_name: str, payload: Optional[Any] = None) -> None:
        """Request navigation via the declarative router."""
        self.request_navigation(NavigationRequest.route(route_name, payload=payload))

    def request_push(self, target: str) -> None:
        """Request a direct push transition."""
        self.request_navigation(NavigationRequest.push(target))

    def request_pop(self) -> None:
        """Request a stack pop."""
        self.request_navigation(NavigationRequest.pop())

    def consume_navigation_request(self) -> Optional[NavigationRequest]:
        """Return and clear the current pending navigation request."""
        request = self._pending_navigation
        self._pending_navigation = None
        return request

    def get_interaction_profile(self) -> InteractionProfile:
        """Return the current interaction profile for the active device."""
        if self.context is None:
            return InteractionProfile.STANDARD
        return getattr(self.context, "interaction_profile", InteractionProfile.STANDARD)

    def is_one_button_mode(self) -> bool:
        """Return True when the screen should render Whisplay-first hints."""
        return self.get_interaction_profile() == InteractionProfile.ONE_BUTTON

    def prefers_simple_one_button_navigation(self) -> bool:
        """Return True when one-button navigation should skip double-tap select."""
        return False

    def handle_action(self, action: "InputAction", data: Optional[Any] = None) -> None:
        """Dispatch a semantic input action to the matching handler method."""
        handler = getattr(self, f"on_{action.value}", None)
        if handler is None:
            logger.debug(f"Screen '{self.name}' does not handle {action.value}")
            return
        handler(data)

    @abstractmethod
    def render(self) -> None:
        """
        Render the screen content.

        This method should draw all screen elements to the display buffer.
        Call display.update() to show the rendered content.
        """
        pass

    def enter(self) -> None:
        """
        Called when screen becomes active.

        Override to perform screen initialization and set up button handlers.
        """
        logger.info(f"Entering screen: {self.name}")

    def exit(self) -> None:
        """
        Called when screen becomes inactive.

        Override to perform cleanup and remove button handlers.
        """
        logger.info(f"Exiting screen: {self.name}")

    # ===== SEMANTIC ACTION HANDLERS =====
    # These are hardware-independent input actions that screens can respond to.
    # Screens override these methods based on their functionality.

    def on_advance(self, data: Optional[Any] = None) -> None:
        """Handle ADVANCE action for one-button navigation flows."""
        pass

    def on_select(self, data: Optional[Any] = None) -> None:
        """Handle SELECT action (confirm/accept current item)."""
        pass

    def on_back(self, data: Optional[Any] = None) -> None:
        """Handle BACK action (cancel/return to previous screen)."""
        pass

    def on_up(self, data: Optional[Any] = None) -> None:
        """Handle UP action (navigate up in lists/menus)."""
        pass

    def on_down(self, data: Optional[Any] = None) -> None:
        """Handle DOWN action (navigate down in lists/menus)."""
        pass

    def on_left(self, data: Optional[Any] = None) -> None:
        """Handle LEFT action (navigate left/previous)."""
        pass

    def on_right(self, data: Optional[Any] = None) -> None:
        """Handle RIGHT action (navigate right/next)."""
        pass

    def on_menu(self, data: Optional[Any] = None) -> None:
        """Handle MENU action (open menu)."""
        pass

    def on_home(self, data: Optional[Any] = None) -> None:
        """Handle HOME action (return to home screen)."""
        pass

    # Playback actions
    def on_play_pause(self, data: Optional[Any] = None) -> None:
        """Handle PLAY_PAUSE action (toggle playback)."""
        pass

    def on_next_track(self, data: Optional[Any] = None) -> None:
        """Handle NEXT_TRACK action (skip to next track)."""
        pass

    def on_prev_track(self, data: Optional[Any] = None) -> None:
        """Handle PREV_TRACK action (go to previous track)."""
        pass

    # VoIP actions
    def on_call_answer(self, data: Optional[Any] = None) -> None:
        """Handle CALL_ANSWER action (answer incoming call)."""
        pass

    def on_call_reject(self, data: Optional[Any] = None) -> None:
        """Handle CALL_REJECT action (reject incoming call)."""
        pass

    def on_call_hangup(self, data: Optional[Any] = None) -> None:
        """Handle CALL_HANGUP action (end active call)."""
        pass

    # PTT (Push-to-Talk) actions
    def on_ptt_press(self, data: Optional[Any] = None) -> None:
        """Handle PTT_PRESS action (PTT button pressed)."""
        pass

    def on_ptt_release(self, data: Optional[Any] = None) -> None:
        """Handle PTT_RELEASE action (PTT button released)."""
        pass

    # Voice actions
    def on_voice_command(self, data: Optional[Any] = None) -> None:
        """
        Handle VOICE_COMMAND action (voice command received).

        Args:
            data: Dict containing voice command information:
                  {'command': str, 'confidence': float, ...}
        """
        pass
