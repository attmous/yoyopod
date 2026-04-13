"""Unit tests for the gpiod-based 4-button input adapter."""

import pytest

from yoyopy.ui.input.hal import InputAction


def test_adapter_capabilities():
    from yoyopy.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    caps = adapter.get_capabilities()
    assert InputAction.SELECT in caps
    assert InputAction.BACK in caps
    assert InputAction.UP in caps
    assert InputAction.DOWN in caps
    assert InputAction.HOME in caps


def test_adapter_fires_callback_on_simulate():
    from yoyopy.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    received = []
    adapter.on_action(InputAction.SELECT, lambda data: received.append(("select", data)))
    adapter._fire_action(InputAction.SELECT, {"button": "A"})
    assert len(received) == 1
    assert received[0] == ("select", {"button": "A"})


def test_clear_callbacks():
    from yoyopy.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    adapter.on_action(InputAction.SELECT, lambda data: None)
    assert len(adapter.callbacks) > 0
    adapter.clear_callbacks()
    assert len(adapter.callbacks) == 0


def test_adapter_start_stop_lifecycle():
    from yoyopy.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    adapter.start()
    assert adapter.running is True
    adapter.stop()
    assert adapter.running is False
