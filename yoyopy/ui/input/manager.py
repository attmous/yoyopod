"""
Input Manager for coordinating multiple input sources.

The InputManager acts as a central coordinator that can combine
multiple input adapters (e.g., buttons + voice) and dispatch
semantic actions to registered callbacks.
"""

from collections import defaultdict
from typing import List, Callable, Optional, Any, Dict
from loguru import logger

from yoyopy.ui.input.hal import InputAction, InputHAL, InteractionProfile


class InputManager:
    """
    Manages multiple input sources and dispatches semantic actions.

    The InputManager can coordinate multiple input adapters simultaneously,
    allowing for hybrid input methods (e.g., physical buttons + voice commands).
    It provides a unified interface for screens to register action callbacks.

    Example:
        manager = InputManager()
        manager.add_adapter(FourButtonInputAdapter(device))
        manager.add_adapter(VoiceInputAdapter(recognizer))

        def on_select(data):
            print("Item selected!")

        manager.on_action(InputAction.SELECT, on_select)
        manager.start()
    """

    def __init__(
        self,
        interaction_profile: InteractionProfile = InteractionProfile.STANDARD,
    ) -> None:
        """Initialize the input manager."""
        self.adapters: List[InputHAL] = []
        self.callbacks: Dict[InputAction, List[Callable]] = defaultdict(list)
        self.interaction_profile = interaction_profile
        self.running = False
        logger.debug("InputManager initialized")

    def set_interaction_profile(self, profile: InteractionProfile) -> None:
        """Store the active interaction profile for the current hardware setup."""
        self.interaction_profile = profile

    def add_adapter(self, adapter: InputHAL) -> None:
        """
        Add an input adapter to the manager.

        The adapter will be started when the manager starts, and its
        actions will be forwarded to the manager's callbacks.

        Args:
            adapter: InputHAL implementation to add

        Example:
            button_adapter = FourButtonInputAdapter(device)
            manager.add_adapter(button_adapter)
        """
        self.adapters.append(adapter)

        # Register forwarding callbacks for all possible actions
        # When adapter fires an action, it gets forwarded to manager callbacks
        for action in InputAction:
            adapter.on_action(
                action,
                lambda data, a=action: self._fire_action(a, data)
            )

        adapter_name = adapter.__class__.__name__
        capabilities = adapter.get_capabilities()
        if capabilities:
            logger.info(f"Added input adapter: {adapter_name} (supports {len(capabilities)} actions)")
        else:
            logger.info(f"Added input adapter: {adapter_name}")

    def on_action(
        self,
        action: InputAction,
        callback: Callable[[Optional[Any]], None]
    ) -> None:
        """
        Register a callback for a semantic action.

        Args:
            action: Semantic action to listen for
            callback: Function to call when action occurs.
                     Receives optional data dict.

        Example:
            def handle_select(data):
                print(f"Selected with data: {data}")

            manager.on_action(InputAction.SELECT, handle_select)
        """
        self.callbacks[action].append(callback)
        logger.debug(f"Registered callback for action: {action.value}")

    def clear_callbacks(self) -> None:
        """
        Clear all registered callbacks.

        This is typically called when switching screens to ensure
        old screen callbacks don't fire.

        Note: This does NOT clear adapter-level callbacks (the forwarding
        callbacks remain intact).
        """
        self.callbacks.clear()
        logger.debug("Cleared all input callbacks")

    def start(self) -> None:
        """
        Start all input adapters.

        This initializes hardware and starts input processing for
        all registered adapters.
        """
        if self.running:
            logger.warning("InputManager already running")
            return

        self.running = True

        for adapter in self.adapters:
            try:
                adapter.start()
                adapter_name = adapter.__class__.__name__
                logger.debug(f"Started adapter: {adapter_name}")
            except Exception as e:
                adapter_name = adapter.__class__.__name__
                logger.error(f"Failed to start adapter {adapter_name}: {e}")

        logger.info(f"InputManager started with {len(self.adapters)} adapter(s)")

    def stop(self) -> None:
        """
        Stop all input adapters.

        This cleans up resources and stops input processing for
        all registered adapters.
        """
        if not self.running:
            return

        self.running = False

        for adapter in self.adapters:
            try:
                adapter.stop()
                adapter_name = adapter.__class__.__name__
                logger.debug(f"Stopped adapter: {adapter_name}")
            except Exception as e:
                adapter_name = adapter.__class__.__name__
                logger.error(f"Failed to stop adapter {adapter_name}: {e}")

        logger.info("InputManager stopped")

    def get_capabilities(self) -> List[InputAction]:
        """
        Get combined capabilities from all adapters.

        Returns:
            List of all unique actions supported by any adapter

        Example:
            capabilities = manager.get_capabilities()
            if InputAction.VOICE_COMMAND in capabilities:
                print("Voice commands are available!")
        """
        capabilities = set()
        for adapter in self.adapters:
            capabilities.update(adapter.get_capabilities())
        return list(capabilities)

    def _fire_action(self, action: InputAction, data: Optional[Any] = None) -> None:
        """
        Fire all registered callbacks for an action.

        This is called internally when an adapter detects an input event.

        Args:
            action: Action that occurred
            data: Optional data dict with action-specific information
        """
        callbacks = self.callbacks.get(action, [])
        if callbacks:
            logger.debug(f"Action fired: {action.value} (data: {data})")
            for callback in callbacks:
                try:
                    callback(data)
                except Exception as e:
                    logger.error(f"Error in action callback for {action.value}: {e}")
        else:
            # No callbacks registered - this is normal during screen transitions
            logger.trace(f"Action {action.value} fired but no callbacks registered")

    def simulate_action(
        self,
        action: InputAction,
        data: Optional[Any] = None
    ) -> None:
        """
        Simulate an input action (for testing).

        This allows testing screen behavior without physical hardware.

        Args:
            action: Action to simulate
            data: Optional data to pass to callbacks

        Example:
            manager.simulate_action(InputAction.SELECT)
            manager.simulate_action(
                InputAction.VOICE_COMMAND,
                {"command": "play music"}
            )
        """
        logger.info(f"Simulating action: {action.value} (data: {data})")
        self._fire_action(action, data)
