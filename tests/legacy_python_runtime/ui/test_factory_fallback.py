"""Tests for LVGL display/input factory behavior."""

from unittest.mock import MagicMock


def test_display_factory_uses_simulation_adapter_for_simulation(monkeypatch):
    """Simulation should build the simulation adapter and start browser preview."""
    from yoyopod.ui.display.factory import get_display

    fake_server = MagicMock()
    import yoyopod.ui.display.adapters.simulation_web.server as web_server

    monkeypatch.setattr(web_server, "get_server", lambda *args, **kwargs: fake_server)

    display = get_display(hardware="simulation", simulate=False)
    try:
        assert display.DISPLAY_TYPE == "simulation"
        assert display.SIMULATED_HARDWARE == "whisplay"
        assert display.WIDTH == 240
        assert display.HEIGHT == 280
        assert display.simulate is True
        fake_server.start.assert_called_once()
    finally:
        display.cleanup()


def test_simulate_flag_overrides_hardware_to_simulation_adapter(monkeypatch):
    """The simulate flag should ignore the requested hardware and build simulation."""

    from yoyopod.ui.display.factory import get_display

    fake_server = MagicMock()
    import yoyopod.ui.display.adapters.simulation_web.server as web_server

    monkeypatch.setattr(web_server, "get_server", lambda *args, **kwargs: fake_server)

    display = get_display(hardware="whisplay", simulate=True)
    try:
        assert display.DISPLAY_TYPE == "simulation"
        assert display.SIMULATED_HARDWARE == "whisplay"
        assert display.simulate is True
    finally:
        display.cleanup()


def test_pimoroni_factory_keeps_adapter_surface_when_hardware_config_is_missing(monkeypatch):
    """Pimoroni should retain its adapter identity even when falling back to simulation."""
    from yoyopod.ui.display.factory import get_display

    fake_server = MagicMock()
    import yoyopod.ui.display.adapters.simulation_web.server as web_server
    import yoyopod.ui.display.factory as factory

    monkeypatch.setattr(web_server, "get_server", lambda *args, **kwargs: fake_server)
    monkeypatch.setattr(factory, "_get_pimoroni_gpio_config", lambda: None)

    display = get_display(hardware="pimoroni", simulate=False)
    try:
        assert display.DISPLAY_TYPE == "pimoroni"
        assert display.SIMULATED_HARDWARE == "pimoroni"
        assert display.simulate is True
        fake_server.start.assert_called_once()
    finally:
        display.cleanup()
