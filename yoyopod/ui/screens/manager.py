"""
Screen management and navigation for YoyoPod.

Handles screen transitions, route resolution, and the navigation stack.
"""

import time
from typing import Callable, Optional, Dict, TYPE_CHECKING
from loguru import logger

from yoyopod.ui.display import Display
from yoyopod.ui.screens.base import Screen
from yoyopod.ui.screens.router import NavigationRequest, ScreenRouter

# Import InputManager from new input HAL
if TYPE_CHECKING:
    from yoyopod.ui.input import InputManager, InputAction
else:
    try:
        from yoyopod.ui.input import InputManager, InputAction
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

    _SLOW_NAVIGATION_WARNING_SECONDS = 0.2
    _SLOW_INPUT_ACTION_WARNING_SECONDS = 0.2
    _SLOW_RENDER_WARNING_SECONDS = 0.2

    def __init__(
        self,
        display: Display,
        input_manager: Optional["InputManager"] = None,
        router: Optional[ScreenRouter] = None,
        on_screen_changed: Optional[Callable[[Optional[str]], None]] = None,
        action_scheduler: Optional[Callable[[Callable[[], None]], None]] = None,
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
        self.on_screen_changed = on_screen_changed
        self.action_scheduler = action_scheduler
        self._navigation_refresh_pending = False

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
        logger.debug("Registered screen: {}", name)

    def push_screen(self, screen_name: str) -> None:
        """
        Push a new screen onto the stack and display it.

        Args:
            screen_name: Name of the registered screen to display
        """
        started_at = time.monotonic()
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
        self._refresh_after_navigation()
        self._notify_screen_changed()

        logger.info(f"Pushed screen: {screen_name} (stack depth: {len(self.screen_stack)})")
        self._warn_if_slow(
            "push_screen",
            started_at=started_at,
            threshold_seconds=self._SLOW_NAVIGATION_WARNING_SECONDS,
            detail=f"target={screen_name} stack_depth={len(self.screen_stack)}",
        )

    def pop_screen(self) -> bool:
        """
        Pop the current screen and return to the previous one.

        Returns:
            True if successful, False if stack is empty
        """
        started_at = time.monotonic()
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
        self._refresh_after_navigation()
        self._notify_screen_changed()

        logger.info(f"Popped screen (stack depth: {len(self.screen_stack)})")
        self._warn_if_slow(
            "pop_screen",
            started_at=started_at,
            threshold_seconds=self._SLOW_NAVIGATION_WARNING_SECONDS,
            detail=f"target={self.current_screen.route_name if self.current_screen else 'none'} stack_depth={len(self.screen_stack)}",
        )
        return True

    def replace_screen(self, screen_name: str) -> None:
        """
        Replace the current screen without adding to stack.

        Args:
            screen_name: Name of the registered screen to display
        """
        started_at = time.monotonic()
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
        self._refresh_after_navigation()
        self._notify_screen_changed()

        logger.info(f"Replaced screen with: {screen_name}")
        self._warn_if_slow(
            "replace_screen",
            started_at=started_at,
            threshold_seconds=self._SLOW_NAVIGATION_WARNING_SECONDS,
            detail=f"target={screen_name}",
        )

    def clear_stack(self) -> None:
        """Clear the screen stack."""
        self.screen_stack.clear()
        logger.debug("Screen stack cleared")

    def get_current_screen(self) -> Optional[Screen]:
        """Get the currently displayed screen."""
        return self.current_screen

    def refresh_current_screen(self) -> None:
        """Re-render the current screen."""
        self._navigation_refresh_pending = False
        if self.current_screen:
            started_at = time.monotonic()
            refresh_for_visible_tick = getattr(
                self.current_screen, "refresh_for_visible_tick", None
            )
            if callable(refresh_for_visible_tick):
                refresh_for_visible_tick()
            self.current_screen.render()
            self._warn_if_slow(
                "refresh_current_screen",
                started_at=started_at,
                threshold_seconds=self._SLOW_RENDER_WARNING_SECONDS,
                detail=f"screen={self.current_screen.route_name or self.current_screen.name}",
            )

    def refresh_current_screen_for_visible_tick(self) -> bool:
        """Refresh the current screen when it opts into periodic visible ticks."""

        if self.current_screen is None:
            return False

        wants_visible_tick_refresh = getattr(
            self.current_screen,
            "wants_visible_tick_refresh",
            None,
        )
        refresh_for_visible_tick = getattr(
            self.current_screen,
            "refresh_for_visible_tick",
            None,
        )
        if callable(wants_visible_tick_refresh):
            if not wants_visible_tick_refresh():
                return False
        elif not callable(refresh_for_visible_tick):
            return False

        self.refresh_current_screen()
        return True

    def pop_call_screens(self) -> None:
        """Pop all call-related screens from the stack."""

        call_route_names = {"in_call", "incoming_call", "outgoing_call"}
        while self.current_screen is not None and self.current_screen.route_name in call_route_names:
            self.pop_screen()
            if not self.screen_stack:
                break

        logger.debug("Call screens cleared from stack")

    def refresh_now_playing_screen(self) -> None:
        """Refresh the now-playing screen when it is currently visible."""

        if self.current_screen is None or self.current_screen.route_name != "now_playing":
            return
        self.current_screen.render()
        logger.debug("  -> Now playing screen refreshed")

    def refresh_call_screen_if_visible(self) -> None:
        """Refresh the Talk root screen when it is currently visible."""

        if self.current_screen is None or self.current_screen.route_name != "call":
            return
        self.current_screen.render()
        logger.debug("  -> Call screen refreshed")

    def show_incoming_call(self, caller_address: str, caller_name: str) -> None:
        """Update and show the incoming-call screen."""

        screen = self.screens.get("incoming_call")
        if screen is None:
            return

        setattr(screen, "caller_address", caller_address)
        setattr(screen, "caller_name", caller_name)
        setattr(screen, "ring_animation_frame", 0)

        if self.current_screen is not screen:
            self.push_screen("incoming_call")
            logger.info("  -> Pushed incoming call screen")

    def show_in_call(self) -> None:
        """Show the active in-call screen when it is not already visible."""

        screen = self.screens.get("in_call")
        if screen is None:
            return

        if self.current_screen is not screen:
            self.push_screen("in_call")
            logger.info("  -> Pushed in-call screen")

    def show_outgoing_call(self, callee_address: str, callee_name: str) -> None:
        """Update and show the outgoing-call screen."""

        screen = self.screens.get("outgoing_call")
        if screen is None:
            return

        setattr(screen, "callee_address", callee_address)
        setattr(screen, "callee_name", callee_name or "Unknown")
        setattr(screen, "ring_animation_frame", 0)

        if self.current_screen is not screen:
            self.push_screen("outgoing_call")
            logger.info("  -> Pushed outgoing call screen")

    def flush_pending_navigation_refresh(self) -> bool:
        """Render one deferred LVGL navigation refresh when present."""
        if not self._navigation_refresh_pending:
            return False
        self.refresh_current_screen()
        return True

    def _notify_screen_changed(self) -> None:
        """Notify listeners when the active screen changes."""
        if self.on_screen_changed is None:
            return
        route_name = self.current_screen.route_name if self.current_screen else None
        self.on_screen_changed(route_name)

    def _refresh_after_navigation(self) -> None:
        """Refresh immediately or defer to the LVGL pump after a navigation change."""
        if getattr(self.display, "backend_kind", "unavailable") == "lvgl":
            self._navigation_refresh_pending = self.current_screen is not None
            return
        self.refresh_current_screen()

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

        self._configure_screen_input_modes()

        # Helper function to dispatch an action and then refresh or route
        def dispatch_action(action: "InputAction", data=None) -> None:
            started_at = time.monotonic()
            previous_screen = self.current_screen
            if previous_screen is None:
                return

            previous_screen.handle_action(action, data)
            navigation_request = previous_screen.consume_navigation_request()
            if navigation_request is not None:
                self.apply_navigation_request(navigation_request, source_screen=previous_screen)
            if self.current_screen is previous_screen:
                self.refresh_current_screen()
            self._warn_if_slow(
                "screen action",
                started_at=started_at,
                threshold_seconds=self._SLOW_INPUT_ACTION_WARNING_SECONDS,
                detail=(
                    f"action={action.value} "
                    f"screen={previous_screen.route_name or previous_screen.name}"
                ),
            )

        def wrap_with_refresh(action: "InputAction"):
            """Wrap action handler to automatically refresh display after execution."""

            def wrapper(data=None):
                if self.action_scheduler is not None:
                    self.action_scheduler(lambda: dispatch_action(action, data))
                    return
                dispatch_action(action, data)

            return wrapper

        for action in InputAction:
            self.input_manager.on_action(action, wrap_with_refresh(action))

        logger.debug("Connected input actions for {}", self.current_screen.name)

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

        logger.debug("Disconnected input actions for {}", self.current_screen.name)

    def _configure_screen_input_modes(self) -> None:
        """Adjust adapter-specific modes based on the active screen."""
        if not self.input_manager or not self.current_screen:
            return

        wants_raw_ptt = False
        raw_ptt_hook = getattr(self.current_screen, "wants_ptt_passthrough", None)
        if callable(raw_ptt_hook):
            wants_raw_ptt = bool(raw_ptt_hook())

        prefers_simple_nav = False
        simple_nav_hook = getattr(
            self.current_screen,
            "prefers_simple_one_button_navigation",
            None,
        )
        if callable(simple_nav_hook):
            prefers_simple_nav = bool(simple_nav_hook())

        for adapter in getattr(self.input_manager, "adapters", []):
            configure_passthrough = getattr(adapter, "set_raw_ptt_passthrough", None)
            if callable(configure_passthrough):
                configure_passthrough(wants_raw_ptt)
            configure_double_tap = getattr(adapter, "set_double_tap_select_enabled", None)
            if callable(configure_double_tap):
                configure_double_tap(not prefers_simple_nav)

    def rebind_current_screen_inputs(self) -> None:
        """Re-apply input bindings for the active screen after its mode changes."""
        if self.current_screen is None:
            return
        self._disconnect_inputs()
        self._connect_inputs()

    # Legacy method names for backward compatibility
    def _connect_buttons(self) -> None:
        """Legacy method - redirects to _connect_inputs()."""
        self._connect_inputs()

    def _disconnect_buttons(self) -> None:
        """Legacy method - redirects to _disconnect_inputs()."""
        self._disconnect_inputs()

    def _warn_if_slow(
        self,
        operation: str,
        *,
        started_at: float,
        threshold_seconds: float,
        detail: str = "",
    ) -> None:
        """Emit a targeted warning when one navigation/UI step blocks unusually long."""

        elapsed_seconds = time.monotonic() - started_at
        if elapsed_seconds < threshold_seconds:
            return

        logger.warning(
            "Slow screen manager operation: {} took {:.1f} ms ({})",
            operation,
            elapsed_seconds * 1000.0,
            detail or "no extra detail",
        )
