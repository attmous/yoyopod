"""
Screen management and navigation for YoyoPod.

Handles screen transitions, route resolution, and the navigation stack.
"""

from typing import Optional, Dict, TYPE_CHECKING
from loguru import logger

from yoyopy.ui.display import Display
from yoyopy.ui.screens.base import Screen
from yoyopy.ui.screens.router import NavigationRequest, ScreenRouter

# Import InputManager from new input HAL
if TYPE_CHECKING:
    from yoyopy.ui.input import InputManager, InputAction
else:
    try:
        from yoyopy.ui.input import InputManager, InputAction
    except ImportError:
        # Fallback for gradual migration
        InputManager = None
        InputAction = None


class ScreenManager:
    """
    Manages screen navigation and transitions.

    Maintains a stack of screens for back navigation and
    handles screen lifecycle (enter/exit).
    """

    def __init__(
        self,
        display: Display,
        input_manager: Optional['InputManager'] = None,
        router: Optional[ScreenRouter] = None,
    ) -> None:
        """
        Initialize the screen manager.

        Args:
            display: Display controller instance
            input_manager: Input manager for handling user input (optional)
        """
        self.display = display
        self.input_manager = input_manager
        self.current_screen: Optional[Screen] = None
        self.screen_stack: list[Screen] = []
        self.screens: Dict[str, Screen] = {}
        self.router = router or ScreenRouter()

        logger.info("ScreenManager initialized")

    def register_screen(self, name: str, screen: Screen) -> None:
        """
        Register a screen with the manager.

        Args:
            name: Unique name for the screen
            screen: Screen instance
        """
        self.screens[name] = screen
        screen.set_screen_manager(self)
        screen.set_route_name(name)
        logger.debug(f"Registered screen: {name}")

    def push_screen(self, screen_name: str) -> None:
        """
        Push a new screen onto the stack and display it.

        Args:
            screen_name: Name of the registered screen to display
        """
        if screen_name not in self.screens:
            logger.error(f"Screen not found: {screen_name}")
            return

        # Exit current screen and remove button handlers
        if self.current_screen:
            self._disconnect_buttons()
            self.current_screen.exit()
            self.screen_stack.append(self.current_screen)

        # Enter new screen and set up button handlers
        self.current_screen = self.screens[screen_name]
        self.current_screen.enter()
        self._connect_buttons()
        self.current_screen.render()

        logger.info(f"Pushed screen: {screen_name} (stack depth: {len(self.screen_stack)})")

    def pop_screen(self) -> bool:
        """
        Pop the current screen and return to the previous one.

        Returns:
            True if successful, False if stack is empty
        """
        if not self.screen_stack:
            logger.warning("Cannot pop: screen stack is empty")
            return False

        # Exit current screen and remove button handlers
        if self.current_screen:
            self._disconnect_buttons()
            self.current_screen.exit()

        # Return to previous screen and reconnect button handlers
        self.current_screen = self.screen_stack.pop()
        self.current_screen.enter()
        self._connect_buttons()
        self.current_screen.render()

        logger.info(f"Popped screen (stack depth: {len(self.screen_stack)})")
        return True

    def replace_screen(self, screen_name: str) -> None:
        """
        Replace the current screen without adding to stack.

        Args:
            screen_name: Name of the registered screen to display
        """
        if screen_name not in self.screens:
            logger.error(f"Screen not found: {screen_name}")
            return

        # Exit current screen and remove button handlers
        if self.current_screen:
            self._disconnect_buttons()
            self.current_screen.exit()

        # Enter new screen and connect button handlers (don't push old one to stack)
        self.current_screen = self.screens[screen_name]
        self.current_screen.enter()
        self._connect_buttons()
        self.current_screen.render()

        logger.info(f"Replaced screen with: {screen_name}")

    def clear_stack(self) -> None:
        """Clear the screen stack."""
        self.screen_stack.clear()
        logger.debug("Screen stack cleared")

    def get_current_screen(self) -> Optional[Screen]:
        """Get the currently displayed screen."""
        return self.current_screen

    def refresh_current_screen(self) -> None:
        """Re-render the current screen."""
        if self.current_screen:
            self.current_screen.render()

    def apply_navigation_request(
        self,
        request: NavigationRequest,
        source_screen: Optional[Screen] = None,
    ) -> bool:
        """Apply a direct or routed navigation request."""
        resolved_request = request
        if request.operation == "route":
            if source_screen is None or source_screen.route_name is None:
                logger.warning("Cannot resolve route without a source screen")
                return False
            resolved_request = self.router.resolve(
                source_screen.route_name,
                request.route_name or "",
                payload=request.payload,
            )
            if resolved_request is None:
                return False

        if resolved_request.operation == "push" and resolved_request.target:
            self.push_screen(resolved_request.target)
            return True
        if resolved_request.operation == "replace" and resolved_request.target:
            self.replace_screen(resolved_request.target)
            return True
        if resolved_request.operation == "pop":
            return self.pop_screen()

        logger.warning(f"Unsupported navigation request: {resolved_request}")
        return False

    def _connect_inputs(self) -> None:
        """Connect input action handlers for the current screen."""
        if not self.current_screen:
            return

        # Skip if no input manager
        if not self.input_manager:
            logger.debug("No input manager available - skipping input connection")
            return

        # Import InputAction if available
        if InputAction is None:
            logger.warning("InputAction not available - cannot connect inputs")
            return

        # Helper function to dispatch an action and then refresh or route
        def wrap_with_refresh(action: "InputAction"):
            """Wrap action handler to automatically refresh display after execution."""
            def wrapper(data=None):
                previous_screen = self.current_screen
                if previous_screen is None:
                    return

                previous_screen.handle_action(action, data)
                navigation_request = previous_screen.consume_navigation_request()
                if navigation_request is not None:
                    self.apply_navigation_request(navigation_request, source_screen=previous_screen)
                if self.current_screen is previous_screen:
                    self.refresh_current_screen()
            return wrapper

        for action in InputAction:
            self.input_manager.on_action(action, wrap_with_refresh(action))

        logger.debug(f"Connected input actions for {self.current_screen.name}")

    def _disconnect_inputs(self) -> None:
        """Disconnect input action handlers for the current screen."""
        if not self.current_screen:
            return

        # Skip if no input manager
        if not self.input_manager:
            logger.debug("No input manager available - skipping input disconnection")
            return

        # Clear all action callbacks
        self.input_manager.clear_callbacks()

        logger.debug(f"Disconnected input actions for {self.current_screen.name}")

    # Legacy method names for backward compatibility
    def _connect_buttons(self) -> None:
        """Legacy method - redirects to _connect_inputs()."""
        self._connect_inputs()

    def _disconnect_buttons(self) -> None:
        """Legacy method - redirects to _disconnect_inputs()."""
        self._disconnect_inputs()
