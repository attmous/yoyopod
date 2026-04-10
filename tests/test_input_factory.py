"""Tests for profile-aware input-manager creation."""

from __future__ import annotations

from yoyopy.ui.input.hal import InputAction
from yoyopy.ui.input import InteractionProfile, get_input_manager
from yoyopy.ui.input.adapters.ptt_button import PTTInputAdapter


class WhisplayDisplayAdapter:
    """Minimal Whisplay display-adapter double for factory tests."""

    DISPLAY_TYPE = "whisplay"

    def __init__(self) -> None:
        self.device = None


class SimulationDisplayAdapter:
    """Minimal simulation display-adapter double mirroring Whisplay."""

    DISPLAY_TYPE = "simulation"
    SIMULATED_HARDWARE = "whisplay"


def test_whisplay_factory_applies_one_button_profile_and_custom_timings() -> None:
    """Whisplay factory wiring should pass typed timing settings into the adapter."""
    manager = get_input_manager(
        WhisplayDisplayAdapter(),
        config={
            "input": {
                "ptt_navigation": True,
                "whisplay_debounce_ms": 80,
                "whisplay_double_tap_ms": 240,
                "whisplay_long_hold_ms": 950,
            }
        },
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


def test_simulation_factory_uses_whisplay_profile_and_browser_buttons(monkeypatch) -> None:
    """Simulation should expose the same one-button browser controls as Whisplay."""

    class FakeServer:
        def __init__(self) -> None:
            self.callback = None

        def set_input_callback(self, callback) -> None:
            self.callback = callback

    server = FakeServer()

    import yoyopy.ui.web_server as web_server

    monkeypatch.setattr(web_server, "get_server", lambda *args, **kwargs: server)

    manager = get_input_manager(
        SimulationDisplayAdapter(),
        config={"input": {"ptt_navigation": True}},
        simulate=False,
    )

    observed: list[InputAction] = []
    assert manager is not None
    assert manager.interaction_profile == InteractionProfile.ONE_BUTTON
    manager.on_action(InputAction.ADVANCE, lambda data=None: observed.append(InputAction.ADVANCE))
    manager.on_action(InputAction.SELECT, lambda data=None: observed.append(InputAction.SELECT))
    manager.on_action(InputAction.BACK, lambda data=None: observed.append(InputAction.BACK))

    assert server.callback is not None
    server.callback("DOWN")
    server.callback("SELECT")
    server.callback("BACK")

    assert observed == [
        InputAction.ADVANCE,
        InputAction.SELECT,
        InputAction.BACK,
    ]
