"""
Low-level ST7789 display driver over spidev + gpiod.

Communicates with an ST7789/ST7789P3 display controller via Linux spidev
for SPI data transfer and libgpiod for DC, CS, and backlight control.
No dependency on RPi.GPIO or displayhatmini.

Designed for non-Pi boards (Radxa Cubie A7Z, etc.) where the Pimoroni
Display HAT Mini is physically connected but vendor libraries are unavailable.
"""

from __future__ import annotations

import time
from typing import Optional

from loguru import logger

try:
    import spidev

    HAS_SPIDEV = True
except ImportError:
    spidev = None  # type: ignore[assignment]
    HAS_SPIDEV = False

from yoyopod_cli.pi.support.gpiod_compat import HAS_GPIOD, open_chip, request_output

# ST7789 command constants
_SWRESET = 0x01
_SLPOUT = 0x11
_NORON = 0x13
_INVON = 0x21
_DISPON = 0x29
_CASET = 0x2A
_RASET = 0x2B
_RAMWR = 0x2C
_COLMOD = 0x3A
_MADCTL = 0x36

# MADCTL flags for landscape rotation (320x240 from native 240x320)
_MADCTL_LANDSCAPE = 0x60  # MV=1, MX=1 -> 90deg CW rotation

# SPI transfer chunk size (avoid kernel buffer limits)
_SPI_CHUNK_SIZE = 4096


class ST7789SpiDriver:
    """Drive an ST7789 display over spidev with gpiod GPIO control."""

    def __init__(
        self,
        spi_bus: int,
        spi_device: int,
        spi_speed_hz: int,
        dc_chip: str,
        dc_line: int,
        cs_chip: str,
        cs_line: int,
        backlight_chip: str,
        backlight_line: int,
    ) -> None:
        self._spi: Optional[object] = None
        self._dc_line: Optional[object] = None
        self._cs_line: Optional[object] = None
        self._backlight_line: Optional[object] = None
        self._gpio_chips: list[object] = []

        # Open SPI
        if not HAS_SPIDEV:
            raise RuntimeError("spidev module is required but not installed")
        self._spi = spidev.SpiDev()
        self._spi.open(spi_bus, spi_device)
        self._spi.max_speed_hz = spi_speed_hz
        self._spi.mode = 0
        try:
            self._spi.no_cs = True
        except OSError:
            logger.debug("SPI no_cs not supported by this driver, using hardware CS")
        self._spi.bits_per_word = 8
        logger.info(
            "ST7789 SPI opened: bus={}, device={}, speed={}MHz",
            spi_bus,
            spi_device,
            spi_speed_hz // 1_000_000,
        )

        # Open GPIO lines
        if not HAS_GPIOD:
            raise RuntimeError("gpiod module is required but not installed")

        self._dc_line = self._request_output_line(dc_chip, dc_line, "st7789-dc")
        try:
            self._cs_line = self._request_output_line(cs_chip, cs_line, "st7789-cs")
            self._cs_line.set_value(1)  # CS idle high
        except Exception as e:
            logger.warning("Software CS not available ({}), relying on hardware CS", e)
            self._cs_line = None
        self._backlight_line = self._request_output_line(
            backlight_chip,
            backlight_line,
            "st7789-bl",
        )

        logger.info("ST7789 GPIO lines acquired (DC{}, backlight)", "+CS" if self._cs_line else "")

    def _request_output_line(self, chip_name: str, line_offset: int, consumer: str) -> object:
        """Request a GPIO line as output via gpiod compat layer."""
        chip = open_chip(chip_name)
        self._gpio_chips.append(chip)
        return request_output(chip, line_offset, consumer, default_val=0)

    def init(self) -> None:
        """Send the ST7789 initialization command sequence."""
        # Software reset
        self.command(_SWRESET)
        time.sleep(0.15)

        # Exit sleep
        self.command(_SLPOUT)
        time.sleep(0.5)

        # Pixel format: 16-bit RGB565
        self.command(_COLMOD, bytes([0x55]))
        time.sleep(0.01)

        # Memory access control: landscape rotation
        self.command(_MADCTL, bytes([_MADCTL_LANDSCAPE]))

        # Inversion on (required by ST7789 for correct colors)
        self.command(_INVON)
        time.sleep(0.01)

        # Normal display mode
        self.command(_NORON)
        time.sleep(0.01)

        # Display on
        self.command(_DISPON)
        time.sleep(0.05)

        logger.info("ST7789 display initialized (landscape 320x240, RGB565)")

    def command(self, cmd: int, data: bytes = b"") -> None:
        """Send a command byte (DC=low), optionally followed by data bytes (DC=high)."""
        if self._cs_line:
            self._cs_line.set_value(0)

        # Command phase: DC low
        self._dc_line.set_value(0)
        self._spi.writebytes2([cmd])

        # Data phase: DC high
        if data:
            self._dc_line.set_value(1)
            self._spi.writebytes2(list(data))

        if self._cs_line:
            self._cs_line.set_value(1)

    def draw_image(self, x: int, y: int, width: int, height: int, pixel_data: bytes) -> None:
        """Write RGB565 pixel data to a display region."""
        x_end = x + width - 1
        y_end = y + height - 1

        # Set column address (CASET)
        self.command(
            _CASET,
            bytes(
                [
                    (x >> 8) & 0xFF,
                    x & 0xFF,
                    (x_end >> 8) & 0xFF,
                    x_end & 0xFF,
                ]
            ),
        )

        # Set row address (RASET)
        self.command(
            _RASET,
            bytes(
                [
                    (y >> 8) & 0xFF,
                    y & 0xFF,
                    (y_end >> 8) & 0xFF,
                    y_end & 0xFF,
                ]
            ),
        )

        # Write pixel data (RAMWR)
        if self._cs_line:
            self._cs_line.set_value(0)
        self._dc_line.set_value(0)
        self._spi.writebytes2([_RAMWR])
        self._dc_line.set_value(1)

        # Send pixel data in chunks to avoid kernel buffer limits
        for offset in range(0, len(pixel_data), _SPI_CHUNK_SIZE):
            chunk = pixel_data[offset : offset + _SPI_CHUNK_SIZE]
            self._spi.writebytes2(chunk)

        if self._cs_line:
            self._cs_line.set_value(1)

    def set_backlight(self, on: bool) -> None:
        """Turn backlight on or off."""
        self._backlight_line.set_value(1 if on else 0)

    def cleanup(self) -> None:
        """Release SPI and GPIO resources."""
        if self._backlight_line is not None:
            try:
                self._backlight_line.set_value(0)
                self._backlight_line.release()
            except Exception:
                pass

        if self._dc_line is not None:
            try:
                self._dc_line.release()
            except Exception:
                pass

        if self._cs_line is not None:
            try:
                self._cs_line.release()
            except Exception:
                pass

        for chip in self._gpio_chips:
            try:
                chip.close()
            except Exception:
                pass
        self._gpio_chips.clear()

        if self._spi is not None:
            try:
                self._spi.close()
            except Exception:
                pass

        logger.info("ST7789 driver cleaned up")
