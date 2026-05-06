"""Unit tests for the ST7789 SPI driver (mocked hardware)."""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mock_spidev():
    """Provide a mock spidev.SpiDev instance."""
    with (
        patch("yoyopod.ui.display.adapters.st7789_spi.spidev") as mock_mod,
        patch("yoyopod.ui.display.adapters.st7789_spi.HAS_SPIDEV", True),
    ):
        device = MagicMock()
        mock_mod.SpiDev.return_value = device
        yield device


@pytest.fixture
def mock_gpiod():
    """Provide a mock gpiod compat layer."""
    chip_instances: dict[str, MagicMock] = {}

    def make_chip(name: str) -> MagicMock:
        if name not in chip_instances:
            chip = MagicMock()
            chip.get_line.return_value = MagicMock()
            chip_instances[name] = chip
        return chip_instances[name]

    def make_output(chip, line_offset, consumer, default_val=0):
        line = chip.get_line(line_offset)
        return line

    with (
        patch("yoyopod.ui.display.adapters.st7789_spi.HAS_GPIOD", True),
        patch("yoyopod.ui.display.adapters.st7789_spi.open_chip", side_effect=make_chip),
        patch("yoyopod.ui.display.adapters.st7789_spi.request_output", side_effect=make_output),
    ):
        yield None, chip_instances


def test_driver_opens_spi_device(mock_spidev, mock_gpiod):
    from yoyopod.ui.display.adapters.st7789_spi import ST7789SpiDriver

    driver = ST7789SpiDriver(
        spi_bus=1,
        spi_device=0,
        spi_speed_hz=60_000_000,
        dc_chip="gpiochip0",
        dc_line=109,
        cs_chip="gpiochip0",
        cs_line=110,
        backlight_chip="gpiochip1",
        backlight_line=35,
    )
    mock_spidev.open.assert_called_once_with(1, 0)
    assert mock_spidev.max_speed_hz == 60_000_000
    assert mock_spidev.mode == 0
    assert mock_spidev.no_cs is True
    driver.cleanup()


def test_driver_requests_gpio_lines(mock_spidev, mock_gpiod):
    mock_mod, chips = mock_gpiod
    from yoyopod.ui.display.adapters.st7789_spi import ST7789SpiDriver

    driver = ST7789SpiDriver(
        spi_bus=1,
        spi_device=0,
        spi_speed_hz=60_000_000,
        dc_chip="gpiochip0",
        dc_line=109,
        cs_chip="gpiochip0",
        cs_line=110,
        backlight_chip="gpiochip1",
        backlight_line=35,
    )
    chips["gpiochip0"].get_line.assert_any_call(109)
    chips["gpiochip0"].get_line.assert_any_call(110)
    chips["gpiochip1"].get_line.assert_any_call(35)
    driver.cleanup()


def test_command_toggles_dc_low(mock_spidev, mock_gpiod):
    from yoyopod.ui.display.adapters.st7789_spi import ST7789SpiDriver

    driver = ST7789SpiDriver(
        spi_bus=1,
        spi_device=0,
        spi_speed_hz=60_000_000,
        dc_chip="gpiochip0",
        dc_line=109,
        cs_chip="gpiochip0",
        cs_line=110,
        backlight_chip="gpiochip1",
        backlight_line=35,
    )
    driver.command(0x01)  # SWRESET

    dc_line = driver._dc_line
    cs_line = driver._cs_line
    dc_line.set_value.assert_any_call(0)
    cs_line.set_value.assert_any_call(0)
    driver.cleanup()


def test_draw_image_sends_spi_data(mock_spidev, mock_gpiod):
    from yoyopod.ui.display.adapters.st7789_spi import ST7789SpiDriver

    driver = ST7789SpiDriver(
        spi_bus=1,
        spi_device=0,
        spi_speed_hz=60_000_000,
        dc_chip="gpiochip0",
        dc_line=109,
        cs_chip="gpiochip0",
        cs_line=110,
        backlight_chip="gpiochip1",
        backlight_line=35,
    )
    pixel_data = bytes([0xFF, 0x00] * 4)  # 4 pixels of RGB565
    driver.draw_image(0, 0, 2, 2, pixel_data)

    assert mock_spidev.writebytes2.call_count > 0
    driver.cleanup()


def test_set_backlight(mock_spidev, mock_gpiod):
    from yoyopod.ui.display.adapters.st7789_spi import ST7789SpiDriver

    driver = ST7789SpiDriver(
        spi_bus=1,
        spi_device=0,
        spi_speed_hz=60_000_000,
        dc_chip="gpiochip0",
        dc_line=109,
        cs_chip="gpiochip0",
        cs_line=110,
        backlight_chip="gpiochip1",
        backlight_line=35,
    )
    driver.set_backlight(True)
    driver._backlight_line.set_value.assert_called_with(1)

    driver.set_backlight(False)
    driver._backlight_line.set_value.assert_called_with(0)
    driver.cleanup()
