"""Unit tests for the Cubie Pimoroni display adapter."""

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image


def test_adapter_constants():
    from yoyopy.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

    assert CubiePimoroniAdapter.DISPLAY_TYPE == "pimoroni"
    assert CubiePimoroniAdapter.WIDTH == 320
    assert CubiePimoroniAdapter.HEIGHT == 240
    assert CubiePimoroniAdapter.ORIENTATION == "landscape"
    assert CubiePimoroniAdapter.STATUS_BAR_HEIGHT == 20


def test_adapter_simulate_mode():
    from yoyopy.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

    adapter = CubiePimoroniAdapter(simulate=True)
    assert adapter.simulate is True
    assert adapter.buffer is not None
    assert adapter.buffer.size == (320, 240)
    adapter.cleanup()


def test_clear_fills_buffer():
    from yoyopy.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

    adapter = CubiePimoroniAdapter(simulate=True)
    adapter.clear((255, 0, 0))
    assert adapter.buffer.getpixel((0, 0)) == (255, 0, 0)
    adapter.cleanup()


def test_update_converts_to_rgb565_and_sends():
    from yoyopy.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter
    from yoyopy.config.models import GpioPin, PimoroniGpioConfig

    gpio_config = PimoroniGpioConfig(
        dc=GpioPin("gpiochip0", 109),
        cs=GpioPin("gpiochip0", 110),
        backlight=GpioPin("gpiochip1", 35),
    )
    with patch(
        "yoyopy.ui.display.adapters.st7789_spi.ST7789SpiDriver"
    ) as mock_cls:
        driver = MagicMock()
        mock_cls.return_value = driver

        adapter = CubiePimoroniAdapter(simulate=False, gpio_config=gpio_config)
        adapter.clear((255, 255, 255))
        adapter.update()

        driver.draw_image.assert_called_once()
        args = driver.draw_image.call_args[0]
        assert args[0] == 0  # x
        assert args[1] == 0  # y
        assert args[2] == 320  # width
        assert args[3] == 240  # height
        assert len(args[4]) == 320 * 240 * 2  # RGB565 = 2 bytes/pixel
        adapter.cleanup()


def test_rgb565_conversion():
    from yoyopy.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

    adapter = CubiePimoroniAdapter(simulate=True)

    # Pure white (255, 255, 255) -> 0xFFFF in RGB565
    img = Image.new("RGB", (1, 1), (255, 255, 255))
    result = adapter._pil_to_rgb565(img)
    assert result == bytes([0xFF, 0xFF])

    # Pure black (0, 0, 0) -> 0x0000
    img = Image.new("RGB", (1, 1), (0, 0, 0))
    result = adapter._pil_to_rgb565(img)
    assert result == bytes([0x00, 0x00])

    adapter.cleanup()


def test_get_backend_kind():
    from yoyopy.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

    adapter = CubiePimoroniAdapter(simulate=True)
    assert adapter.get_backend_kind() == "pil"
    adapter.cleanup()


def test_status_bar_renders():
    from yoyopy.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

    adapter = CubiePimoroniAdapter(simulate=True)
    adapter.status_bar(time_str="14:30", battery_percent=75, signal_strength=3)
    # Verify status bar region is not all black (something was drawn)
    status_pixels = adapter.buffer.crop((0, 0, 320, 20))
    assert status_pixels.getbbox() is not None
    adapter.cleanup()
