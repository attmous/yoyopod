"""Tests for profile-aware input-manager creation."""

from __future__ import annotations

import sys
import types

from yoyopod_cli.config.models import AppInputConfig
from yoyopod.ui.input.hal import InputAction
from yoyopod.ui.input import InteractionProfile, get_input_manager
from yoyopod.ui.input.adapters.ptt_button import PTTInputAdapter


class WhisplayDisplayAdapter:
    """Minimal Whisplay display-adapter double for factory tests."""

    DISPLAY_TYPE = "whisplay"

    def __init__(self) -> None:
        self.device = None
        self.simulate = False


class SimulatedWhisplayDisplayAdapter(WhisplayDisplayAdapter):
    """Minimal simulation display-adapter double on the shared LVGL path."""

    DISPLAY_TYPE = "simulation"
    SIMULATED_HARDWARE = "whisplay"

    def __init__(self) -> None:
        super().__init__()
        self.simulate = True


class PimoroniDisplayAdapter:
    """Minimal Pimoroni display-adapter double for factory tests."""

    DISPLAY_TYPE = "pimoroni"

    def __init__(self) -> None:
        self.device = object()
        self.simulate = False


def test_whisplay_factory_applies_one_button_profile_and_custom_timings() -> None:
    """Whisplay factory wiring should pass typed timing settings into the adapter."""
    manager = get_input_manager(
        WhisplayDisplayAdapter(),
        input_settings=AppInputConfig(
            ptt_navigation=True,
            whisplay_debounce_ms=80,
            whisplay_double_tap_ms=240,
            whisplay_long_hold_ms=950,
        ),
        simulate=True,
    )

    assert manager is not None
    assert manager.interaction_profile == InteractionProfile.ONE_BUTTON
    assert len(manager.adapters) == 1

    adapter = manager.adapters[0]
    assert isinstance(adapter, PTTInputAdapter)
    assert adapter.enable_navigation is True
    assert adapter.debounce_time == 0.08
    assert adapter.double_click_time == 0.24
    assert adapter.long_press_time == 0.95


def test_whisplay_factory_keeps_standard_profile_when_navigation_disabled() -> None:
    """Raw PTT mode should not advertise the Whisplay one-button navigation profile."""
    manager = get_input_manager(
        WhisplayDisplayAdapter(),
        config={"input": {"ptt_navigation": False}},
        simulate=True,
    )

    assert manager is not None
    assert manager.interaction_profile == InteractionProfile.STANDARD
    assert len(manager.adapters) == 1

    adapter = manager.adapters[0]
    assert isinstance(adapter, PTTInputAdapter)
    assert adapter.enable_navigation is False


def test_simulation_factory_uses_standard_profile_keyboard_and_browser_buttons(
    monkeypatch,
) -> None:
    """Simulation should use standard keyboard/web controls on its own adapter surface."""

    class FakeServer:
        def __init__(self) -> None:
            self.callback = None

        def set_input_callback(self, callback) -> None:
            self.callback = callback

    server = FakeServer()

    fake_web_server = types.ModuleType("yoyopod.ui.display.adapters.simulation_web.server")
    fake_web_server.get_server = lambda *args, **kwargs: server
    monkeypatch.setitem(
        sys.modules,
        "yoyopod.ui.display.adapters.simulation_web.server",
        fake_web_server,
    )

    manager = get_input_manager(
        SimulatedWhisplayDisplayAdapter(),
        config={"input": {"ptt_navigation": True}},
        simulate=True,
    )

    observed: list[InputAction] = []
    assert manager is not None
    assert manager.interaction_profile == InteractionProfile.STANDARD
    assert len(manager.adapters) == 1
    assert manager.adapters[0].__class__.__name__ in {
        "KeyboardInputAdapter",
        "DummyKeyboardAdapter",
    }
    manager.on_action(InputAction.UP, lambda data=None: observed.append(InputAction.UP))
    manager.on_action(InputAction.DOWN, lambda data=None: observed.append(InputAction.DOWN))
    manager.on_action(InputAction.SELECT, lambda data=None: observed.append(InputAction.SELECT))
    manager.on_action(InputAction.BACK, lambda data=None: observed.append(InputAction.BACK))

    assert server.callback is not None
    server.callback("DOWN")
    server.callback("UP")
    server.callback("SELECT")
    server.callback("BACK")

    assert observed == [
        InputAction.DOWN,
        InputAction.UP,
        InputAction.SELECT,
        InputAction.BACK,
    ]


def test_pimoroni_factory_uses_four_button_adapter_when_displayhatmini_is_available(
    monkeypatch,
) -> None:
    """Pimoroni should still create four-button input on the Pi-native path."""

    fake_displayhatmini = types.ModuleType("displayhatmini")

    class FakeDisplayHATMini:
        pass

    fake_displayhatmini.DisplayHATMini = FakeDisplayHATMini
    monkeypatch.setitem(sys.modules, "displayhatmini", fake_displayhatmini)
    monkeypatch.delitem(sys.modules, "yoyopod.ui.input.adapters.four_button", raising=False)

    manager = get_input_manager(PimoroniDisplayAdapter())

    assert manager is not None
    assert len(manager.adapters) == 1
    adapter = manager.adapters[0]
    assert adapter.__class__.__name__ == "FourButtonInputAdapter"
    assert adapter.simulate is False
