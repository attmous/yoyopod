# Cubie-Native Pimoroni Display Driver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive the Pimoroni Display HAT Mini (ST7789, 320x240, 4 buttons, RGB LED) on the Radxa Cubie A7Z using spidev + gpiod, without the Pi-specific `displayhatmini` library.

**Architecture:** Three new modules behind existing HAL interfaces. An `ST7789SpiDriver` handles raw SPI commands and GPIO control. A `CubiePimoroniAdapter` wraps it as a `DisplayHAL`. A `GpiodButtonAdapter` implements `InputHAL` for 4-button input via gpiod. Factory fallback logic selects these when `displayhatmini` is unavailable but board GPIO config exists.

**Tech Stack:** Python 3.12, spidev, gpiod (libgpiod 1.x), PIL/Pillow, existing YoyoPod HAL interfaces

**Spec:** `docs/superpowers/specs/2026-04-13-cubie-pimoroni-driver-design.md`

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/yoyopod/ui/display/adapters/st7789_spi.py` | Create | Low-level ST7789 SPI + GPIO driver |
| `src/yoyopod/ui/display/adapters/cubie_pimoroni.py` | Create | DisplayHAL adapter for Pimoroni on non-Pi boards |
| `src/yoyopod/ui/input/adapters/gpiod_buttons.py` | Create | InputHAL adapter for 4-button input via gpiod |
| `src/yoyopod/config/models.py` | Modify | Add GpioPin, PimoroniGpioConfig, PimoroniGpioInputConfig dataclasses |
| `src/yoyopod/ui/display/factory.py` | Modify | Add Cubie Pimoroni fallback path |
| `src/yoyopod/ui/input/factory.py` | Modify | Add gpiod button fallback path |
| `config/boards/radxa-cubie-a7z/yoyopod_config.yaml` | Modify | Add pimoroni_gpio display and input pin config |
| `tests/test_st7789_spi.py` | Create | Unit tests for ST7789 driver |
| `tests/test_cubie_pimoroni.py` | Create | Unit tests for Cubie Pimoroni adapter |
| `tests/test_gpiod_buttons.py` | Create | Unit tests for gpiod button adapter |
| `tests/test_factory_fallback.py` | Create | Tests for display/input factory fallback logic |

---

### Task 1: Config Models for GPIO Pin Mapping

**Files:**
- Modify: `src/yoyopod/config/models.py`
- Test: `tests/test_config_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config_models.py`:

```python
def test_gpio_pin_config_from_yaml_dict():
    """GpioPin and PimoroniGpioConfig should load from nested YAML dicts."""
    from yoyopod.config.models import (
        AppDisplayConfig,
        GpioPin,
        PimoroniGpioConfig,
        build_config_model,
    )

    data = {
        "pimoroni_gpio": {
            "spi_bus": 1,
            "spi_device": 0,
            "spi_speed_hz": 60000000,
            "dc": {"chip": "gpiochip0", "line": 109},
            "cs": {"chip": "gpiochip0", "line": 110},
            "backlight": {"chip": "gpiochip1", "line": 35},
            "led_r": {"chip": "gpiochip0", "line": 33},
            "led_g": {"chip": "gpiochip1", "line": 6},
            "led_b": {"chip": "gpiochip1", "line": 7},
        }
    }
    config = build_config_model(AppDisplayConfig, data)
    assert config.pimoroni_gpio is not None
    assert config.pimoroni_gpio.spi_bus == 1
    assert config.pimoroni_gpio.dc == GpioPin(chip="gpiochip0", line=109)
    assert config.pimoroni_gpio.cs == GpioPin(chip="gpiochip0", line=110)
    assert config.pimoroni_gpio.backlight == GpioPin(chip="gpiochip1", line=35)
    assert config.pimoroni_gpio.led_r == GpioPin(chip="gpiochip0", line=33)


def test_gpio_input_config_from_yaml_dict():
    """PimoroniGpioInputConfig should load from nested YAML dicts."""
    from yoyopod.config.models import (
        AppInputConfig,
        GpioPin,
        PimoroniGpioInputConfig,
        build_config_model,
    )

    data = {
        "pimoroni_gpio": {
            "button_a": {"chip": "gpiochip0", "line": 34},
            "button_b": {"chip": "gpiochip0", "line": 35},
            "button_x": {"chip": "gpiochip0", "line": 36},
            "button_y": {"chip": "gpiochip0", "line": 313},
        }
    }
    config = build_config_model(AppInputConfig, data)
    assert config.pimoroni_gpio is not None
    assert config.pimoroni_gpio.button_a == GpioPin(chip="gpiochip0", line=34)
    assert config.pimoroni_gpio.button_y == GpioPin(chip="gpiochip0", line=313)


def test_display_config_defaults_pimoroni_gpio_to_none():
    """When no pimoroni_gpio section exists, it should default to None."""
    from yoyopod.config.models import AppDisplayConfig, build_config_model

    config = build_config_model(AppDisplayConfig, {})
    assert config.pimoroni_gpio is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config_models.py::test_gpio_pin_config_from_yaml_dict tests/test_config_models.py::test_gpio_input_config_from_yaml_dict tests/test_config_models.py::test_display_config_defaults_pimoroni_gpio_to_none -v`
Expected: FAIL — `GpioPin` and `PimoroniGpioConfig` do not exist yet.

- [ ] **Step 3: Add the config dataclasses**

In `src/yoyopod/config/models.py`, add above `AppDisplayConfig`:

```python
@dataclass(slots=True)
class GpioPin:
    """A single GPIO pin reference: chip name and line number."""

    chip: str = ""
    line: int = 0


@dataclass(slots=True)
class PimoroniGpioConfig:
    """GPIO pin mapping for driving the Pimoroni Display HAT Mini via spidev + gpiod."""

    spi_bus: int = 1
    spi_device: int = 0
    spi_speed_hz: int = 60_000_000
    dc: GpioPin | None = None
    cs: GpioPin | None = None
    backlight: GpioPin | None = None
    led_r: GpioPin | None = None
    led_g: GpioPin | None = None
    led_b: GpioPin | None = None


@dataclass(slots=True)
class PimoroniGpioInputConfig:
    """GPIO pin mapping for the Pimoroni Display HAT Mini 4-button input via gpiod."""

    button_a: GpioPin | None = None
    button_b: GpioPin | None = None
    button_x: GpioPin | None = None
    button_y: GpioPin | None = None
```

Add `pimoroni_gpio` field to `AppDisplayConfig`:

```python
@dataclass(slots=True)
class AppDisplayConfig:
    """Display hardware configuration."""

    hardware: str = config_value(default="auto", env="YOYOPOD_DISPLAY")
    whisplay_renderer: str = config_value(default="lvgl", env="YOYOPOD_WHISPLAY_RENDERER")
    lvgl_buffer_lines: int = config_value(default=40, env="YOYOPOD_LVGL_BUFFER_LINES")
    brightness: int = 80
    rotation: int = 0
    backlight_timeout_seconds: int = 60
    pimoroni_gpio: PimoroniGpioConfig | None = None
```

Add `pimoroni_gpio` field to `AppInputConfig`:

```python
@dataclass(slots=True)
class AppInputConfig:
    # ... existing fields unchanged ...
    pimoroni_gpio: PimoroniGpioInputConfig | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_config_models.py -v`
Expected: ALL PASS (new tests plus all existing).

- [ ] **Step 5: Commit**

```bash
git add src/yoyopod/config/models.py tests/test_config_models.py
git commit -m "feat: add GPIO pin config models for Cubie Pimoroni driver"
```

---

### Task 2: ST7789 SPI Driver

**Files:**
- Create: `src/yoyopod/ui/display/adapters/st7789_spi.py`
- Create: `tests/test_st7789_spi.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_st7789_spi.py`:

```python
"""Unit tests for the ST7789 SPI driver (mocked hardware)."""

from unittest.mock import MagicMock, patch, call
import pytest


@pytest.fixture
def mock_spidev():
    """Provide a mock spidev.SpiDev instance."""
    with patch("yoyopod.ui.display.adapters.st7789_spi.spidev") as mock_mod:
        device = MagicMock()
        mock_mod.SpiDev.return_value = device
        yield device


@pytest.fixture
def mock_gpiod():
    """Provide a mock gpiod module with Chip/Line stubs."""
    with patch("yoyopod.ui.display.adapters.st7789_spi.gpiod") as mock_mod:
        chip_instances = {}

        def make_chip(name):
            if name not in chip_instances:
                chip = MagicMock()
                chip.get_line.return_value = MagicMock()
                chip_instances[name] = chip
            return chip_instances[name]

        mock_mod.Chip.side_effect = make_chip
        mock_mod.LINE_REQ_DIR_OUT = 3
        mock_mod.LINE_REQ_DIR_IN = 2
        mock_mod.LINE_REQ_FLAG_BIAS_DISABLE = 8
        yield mock_mod, chip_instances


def test_driver_opens_spi_device(mock_spidev, mock_gpiod):
    from yoyopod.ui.display.adapters.st7789_spi import ST7789SpiDriver

    driver = ST7789SpiDriver(
        spi_bus=1, spi_device=0, spi_speed_hz=60_000_000,
        dc_chip="gpiochip0", dc_line=109,
        cs_chip="gpiochip0", cs_line=110,
        backlight_chip="gpiochip1", backlight_line=35,
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
        spi_bus=1, spi_device=0, spi_speed_hz=60_000_000,
        dc_chip="gpiochip0", dc_line=109,
        cs_chip="gpiochip0", cs_line=110,
        backlight_chip="gpiochip1", backlight_line=35,
    )
    # DC and CS are on the same chip
    chips["gpiochip0"].get_line.assert_any_call(109)
    chips["gpiochip0"].get_line.assert_any_call(110)
    chips["gpiochip1"].get_line.assert_any_call(35)
    driver.cleanup()


def test_command_toggles_dc_low(mock_spidev, mock_gpiod):
    from yoyopod.ui.display.adapters.st7789_spi import ST7789SpiDriver

    driver = ST7789SpiDriver(
        spi_bus=1, spi_device=0, spi_speed_hz=60_000_000,
        dc_chip="gpiochip0", dc_line=109,
        cs_chip="gpiochip0", cs_line=110,
        backlight_chip="gpiochip1", backlight_line=35,
    )
    driver.command(0x01)  # SWRESET

    # DC should have been set low for command
    dc_line = driver._dc_line
    cs_line = driver._cs_line
    dc_line.set_value.assert_any_call(0)
    cs_line.set_value.assert_any_call(0)
    driver.cleanup()


def test_draw_image_sends_caset_raset_ramwr(mock_spidev, mock_gpiod):
    from yoyopod.ui.display.adapters.st7789_spi import ST7789SpiDriver

    driver = ST7789SpiDriver(
        spi_bus=1, spi_device=0, spi_speed_hz=60_000_000,
        dc_chip="gpiochip0", dc_line=109,
        cs_chip="gpiochip0", cs_line=110,
        backlight_chip="gpiochip1", backlight_line=35,
    )
    pixel_data = bytes([0xFF, 0x00] * 4)  # 4 pixels of RGB565
    driver.draw_image(0, 0, 2, 2, pixel_data)

    # Should have sent SPI data (commands + pixel data)
    assert mock_spidev.writebytes2.call_count > 0 or mock_spidev.xfer2.call_count > 0
    driver.cleanup()


def test_set_backlight(mock_spidev, mock_gpiod):
    from yoyopod.ui.display.adapters.st7789_spi import ST7789SpiDriver

    driver = ST7789SpiDriver(
        spi_bus=1, spi_device=0, spi_speed_hz=60_000_000,
        dc_chip="gpiochip0", dc_line=109,
        cs_chip="gpiochip0", cs_line=110,
        backlight_chip="gpiochip1", backlight_line=35,
    )
    driver.set_backlight(True)
    driver._backlight_line.set_value.assert_called_with(1)

    driver.set_backlight(False)
    driver._backlight_line.set_value.assert_called_with(0)
    driver.cleanup()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_st7789_spi.py -v`
Expected: FAIL — module `yoyopod.ui.display.adapters.st7789_spi` does not exist.

- [ ] **Step 3: Implement the ST7789 SPI driver**

Create `src/yoyopod/ui/display/adapters/st7789_spi.py`:

```python
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

try:
    import gpiod

    HAS_GPIOD = True
except ImportError:
    gpiod = None  # type: ignore[assignment]
    HAS_GPIOD = False

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
_MADCTL_LANDSCAPE = 0x60  # MV=1, MX=1 -> 90° CW rotation

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
        self._spi.no_cs = True
        self._spi.bits_per_word = 8
        logger.info(
            "ST7789 SPI opened: bus={}, device={}, speed={}MHz",
            spi_bus, spi_device, spi_speed_hz // 1_000_000,
        )

        # Open GPIO lines
        if not HAS_GPIOD:
            raise RuntimeError("gpiod module is required but not installed")

        self._dc_line = self._request_output_line(dc_chip, dc_line, "st7789-dc")
        self._cs_line = self._request_output_line(cs_chip, cs_line, "st7789-cs")
        self._backlight_line = self._request_output_line(
            backlight_chip, backlight_line, "st7789-bl",
        )

        # CS idle high
        self._cs_line.set_value(1)

        logger.info("ST7789 GPIO lines acquired (DC, CS, backlight)")

    def _request_output_line(self, chip_name: str, line_offset: int, consumer: str) -> object:
        """Request a GPIO line as output via gpiod."""
        chip = gpiod.Chip(chip_name)
        self._gpio_chips.append(chip)
        line = chip.get_line(line_offset)
        line.request(consumer=consumer, type=gpiod.LINE_REQ_DIR_OUT, default_val=0)
        return line

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
        self._cs_line.set_value(0)

        # Command phase: DC low
        self._dc_line.set_value(0)
        self._spi.writebytes2([cmd])

        # Data phase: DC high
        if data:
            self._dc_line.set_value(1)
            self._spi.writebytes2(list(data))

        self._cs_line.set_value(1)

    def draw_image(self, x: int, y: int, width: int, height: int, pixel_data: bytes) -> None:
        """Write RGB565 pixel data to a display region."""
        x_end = x + width - 1
        y_end = y + height - 1

        # Set column address (CASET)
        self.command(_CASET, bytes([
            (x >> 8) & 0xFF, x & 0xFF,
            (x_end >> 8) & 0xFF, x_end & 0xFF,
        ]))

        # Set row address (RASET)
        self.command(_RASET, bytes([
            (y >> 8) & 0xFF, y & 0xFF,
            (y_end >> 8) & 0xFF, y_end & 0xFF,
        ]))

        # Write pixel data (RAMWR)
        self._cs_line.set_value(0)
        self._dc_line.set_value(0)
        self._spi.writebytes2([_RAMWR])
        self._dc_line.set_value(1)

        # Send pixel data in chunks to avoid kernel buffer limits
        for offset in range(0, len(pixel_data), _SPI_CHUNK_SIZE):
            chunk = pixel_data[offset : offset + _SPI_CHUNK_SIZE]
            self._spi.writebytes2(chunk)

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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_st7789_spi.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yoyopod/ui/display/adapters/st7789_spi.py tests/test_st7789_spi.py
git commit -m "feat: add ST7789 SPI driver using spidev + gpiod"
```

---

### Task 3: Cubie Pimoroni Display Adapter

**Files:**
- Create: `src/yoyopod/ui/display/adapters/cubie_pimoroni.py`
- Create: `tests/test_cubie_pimoroni.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_cubie_pimoroni.py`:

```python
"""Unit tests for the Cubie Pimoroni display adapter."""

from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture
def mock_driver():
    """Provide a mock ST7789SpiDriver."""
    with patch(
        "yoyopod.ui.display.adapters.cubie_pimoroni.ST7789SpiDriver"
    ) as mock_cls:
        driver = MagicMock()
        mock_cls.return_value = driver
        yield driver


def test_adapter_constants():
    from yoyopod.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

    assert CubiePimoroniAdapter.DISPLAY_TYPE == "pimoroni"
    assert CubiePimoroniAdapter.WIDTH == 320
    assert CubiePimoroniAdapter.HEIGHT == 240
    assert CubiePimoroniAdapter.ORIENTATION == "landscape"
    assert CubiePimoroniAdapter.STATUS_BAR_HEIGHT == 20


def test_adapter_simulate_mode():
    from yoyopod.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

    adapter = CubiePimoroniAdapter(simulate=True)
    assert adapter.simulate is True
    assert adapter.buffer is not None
    assert adapter.buffer.size == (320, 240)
    adapter.cleanup()


def test_clear_fills_buffer(mock_driver):
    from yoyopod.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

    adapter = CubiePimoroniAdapter(simulate=True)
    adapter.clear((255, 0, 0))
    # Check a pixel in the buffer
    assert adapter.buffer.getpixel((0, 0)) == (255, 0, 0)
    adapter.cleanup()


def test_update_converts_to_rgb565_and_sends(mock_driver):
    from yoyopod.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter
    from yoyopod.config.models import GpioPin, PimoroniGpioConfig

    gpio_config = PimoroniGpioConfig(
        dc=GpioPin("gpiochip0", 109),
        cs=GpioPin("gpiochip0", 110),
        backlight=GpioPin("gpiochip1", 35),
    )
    adapter = CubiePimoroniAdapter(simulate=False, gpio_config=gpio_config)
    adapter.clear((255, 255, 255))
    adapter.update()

    mock_driver.draw_image.assert_called_once()
    args = mock_driver.draw_image.call_args
    assert args[0][0] == 0  # x
    assert args[0][1] == 0  # y
    assert args[0][2] == 320  # width
    assert args[0][3] == 240  # height
    assert len(args[0][4]) == 320 * 240 * 2  # RGB565 = 2 bytes/pixel
    adapter.cleanup()


def test_rgb565_conversion():
    from yoyopod.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

    adapter = CubiePimoroniAdapter(simulate=True)

    # Pure white (255, 255, 255) -> 0xFFFF in RGB565
    from PIL import Image
    img = Image.new("RGB", (1, 1), (255, 255, 255))
    result = adapter._pil_to_rgb565(img)
    assert result == bytes([0xFF, 0xFF])

    # Pure black (0, 0, 0) -> 0x0000
    img = Image.new("RGB", (1, 1), (0, 0, 0))
    result = adapter._pil_to_rgb565(img)
    assert result == bytes([0x00, 0x00])

    adapter.cleanup()


def test_get_backend_kind():
    from yoyopod.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

    adapter = CubiePimoroniAdapter(simulate=True)
    assert adapter.get_backend_kind() == "pil"
    adapter.cleanup()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cubie_pimoroni.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the Cubie Pimoroni adapter**

Create `src/yoyopod/ui/display/adapters/cubie_pimoroni.py`:

```python
"""
Pimoroni Display HAT Mini adapter for non-Pi boards (Cubie A7Z, etc.).

Uses the ST7789SpiDriver for display output and gpiod for RGB LED control.
Implements the same DisplayHAL interface as the Pi-native PimoroniDisplayAdapter
but without any dependency on displayhatmini or RPi.GPIO.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Tuple

from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from yoyopod.config.models import GpioPin, PimoroniGpioConfig
from yoyopod.ui.display.hal import DisplayHAL

try:
    import gpiod

    HAS_GPIOD = True
except ImportError:
    gpiod = None  # type: ignore[assignment]
    HAS_GPIOD = False


class CubiePimoroniAdapter(DisplayHAL):
    """DisplayHAL adapter for the Pimoroni Display HAT Mini on non-Pi boards."""

    DISPLAY_TYPE = "pimoroni"
    WIDTH = 320
    HEIGHT = 240
    ORIENTATION = "landscape"
    STATUS_BAR_HEIGHT = 20

    def __init__(
        self,
        simulate: bool = False,
        gpio_config: PimoroniGpioConfig | None = None,
    ) -> None:
        self.simulate = simulate
        self.buffer: Optional[Image.Image] = None
        self.draw: Optional[ImageDraw.ImageDraw] = None
        self._driver = None
        self._led_lines: dict[str, object] = {}
        self._led_chips: list[object] = []

        self._create_buffer()

        if not self.simulate:
            cfg = gpio_config or PimoroniGpioConfig()
            try:
                from yoyopod.ui.display.adapters.st7789_spi import ST7789SpiDriver

                self._driver = ST7789SpiDriver(
                    spi_bus=cfg.spi_bus,
                    spi_device=cfg.spi_device,
                    spi_speed_hz=cfg.spi_speed_hz,
                    dc_chip=cfg.dc.chip if cfg.dc else "gpiochip0",
                    dc_line=cfg.dc.line if cfg.dc else 109,
                    cs_chip=cfg.cs.chip if cfg.cs else "gpiochip0",
                    cs_line=cfg.cs.line if cfg.cs else 110,
                    backlight_chip=cfg.backlight.chip if cfg.backlight else "gpiochip1",
                    backlight_line=cfg.backlight.line if cfg.backlight else 35,
                )
                self._driver.init()
                self._driver.set_backlight(True)
                self._init_led(cfg)
                logger.info("Cubie Pimoroni adapter initialized (320x240 landscape)")
            except Exception as e:
                logger.error("Failed to initialize Cubie Pimoroni display: {}", e)
                logger.info("Falling back to simulation mode")
                self.simulate = True
                self._driver = None
        else:
            logger.info("Cubie Pimoroni adapter running in simulation mode")

    def _init_led(self, cfg: PimoroniGpioConfig) -> None:
        """Initialize RGB LED GPIO lines."""
        if not HAS_GPIOD:
            return
        for name, pin in [("r", cfg.led_r), ("g", cfg.led_g), ("b", cfg.led_b)]:
            if pin is None:
                continue
            try:
                chip = gpiod.Chip(pin.chip)
                self._led_chips.append(chip)
                line = chip.get_line(pin.line)
                line.request(consumer=f"pimoroni-led-{name}", type=gpiod.LINE_REQ_DIR_OUT, default_val=0)
                self._led_lines[name] = line
            except Exception as e:
                logger.warning("Failed to acquire LED {} GPIO: {}", name, e)

    def set_led(self, r: float, g: float, b: float) -> None:
        """Set RGB LED state (on/off per channel, 0.0 = off, >0.0 = on)."""
        for name, value in [("r", r), ("g", g), ("b", b)]:
            line = self._led_lines.get(name)
            if line is not None:
                try:
                    line.set_value(1 if value > 0 else 0)
                except Exception as e:
                    logger.warning("Failed to set LED {}: {}", name, e)

    def _create_buffer(self) -> None:
        """Create a new PIL drawing buffer."""
        self.buffer = Image.new("RGB", (self.WIDTH, self.HEIGHT), self.COLOR_BLACK)
        self.draw = ImageDraw.Draw(self.buffer)

    def _pil_to_rgb565(self, image: Image.Image) -> bytes:
        """Convert PIL RGB image to RGB565 bytes for SPI."""
        raw = image.tobytes()
        width, height = image.size
        rgb565 = bytearray(width * height * 2)
        for i in range(0, len(raw), 3):
            r, g, b = raw[i], raw[i + 1], raw[i + 2]
            val = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            j = (i // 3) * 2
            rgb565[j] = (val >> 8) & 0xFF
            rgb565[j + 1] = val & 0xFF
        return bytes(rgb565)

    def clear(self, color: Optional[Tuple[int, int, int]] = None) -> None:
        if color is None:
            color = self.COLOR_BLACK
        self.draw.rectangle([(0, 0), (self.WIDTH, self.HEIGHT)], fill=color)

    def text(
        self, text: str, x: int, y: int,
        color: Optional[Tuple[int, int, int]] = None,
        font_size: int = 16, font_path: Optional[Path] = None,
    ) -> None:
        if color is None:
            color = self.COLOR_WHITE
        try:
            if font_path and font_path.exists():
                font = ImageFont.truetype(str(font_path), font_size)
            else:
                try:
                    font = ImageFont.truetype(
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size,
                    )
                except Exception:
                    font = ImageFont.load_default()
        except Exception:
            font = ImageFont.load_default()
        self.draw.text((x, y), text, fill=color, font=font)

    def rectangle(
        self, x1: int, y1: int, x2: int, y2: int,
        fill: Optional[Tuple[int, int, int]] = None,
        outline: Optional[Tuple[int, int, int]] = None, width: int = 1,
    ) -> None:
        self.draw.rectangle([(x1, y1), (x2, y2)], fill=fill, outline=outline, width=width)

    def circle(
        self, x: int, y: int, radius: int,
        fill: Optional[Tuple[int, int, int]] = None,
        outline: Optional[Tuple[int, int, int]] = None, width: int = 1,
    ) -> None:
        bbox = [x - radius, y - radius, x + radius, y + radius]
        self.draw.ellipse(bbox, fill=fill, outline=outline, width=width)

    def line(
        self, x1: int, y1: int, x2: int, y2: int,
        color: Optional[Tuple[int, int, int]] = None, width: int = 1,
    ) -> None:
        if color is None:
            color = self.COLOR_WHITE
        self.draw.line([(x1, y1), (x2, y2)], fill=color, width=width)

    def image(
        self, image_path: Path, x: int, y: int,
        width: Optional[int] = None, height: Optional[int] = None,
    ) -> None:
        try:
            img = Image.open(image_path)
            if width and height:
                img = img.resize((width, height), Image.Resampling.LANCZOS)
            self.buffer.paste(img, (x, y))
        except Exception as e:
            logger.error("Failed to load image {}: {}", image_path, e)

    def status_bar(
        self, time_str: str = "--:--", battery_percent: int = 100,
        signal_strength: int = 4, charging: bool = False,
        external_power: bool = False, power_available: bool = True,
    ) -> None:
        self.rectangle(0, 0, self.WIDTH, self.STATUS_BAR_HEIGHT, fill=self.COLOR_DARK_GRAY)
        time_x = (self.WIDTH - len(time_str) * 8) // 2
        self.text(time_str, time_x, 2, color=self.COLOR_WHITE, font_size=14)

        battery_x = self.WIDTH - 50
        battery_y = 4
        battery_width = 40
        battery_height = 12
        self.rectangle(battery_x, battery_y, battery_x + battery_width,
                       battery_y + battery_height, outline=self.COLOR_WHITE, width=1)
        self.rectangle(battery_x + battery_width, battery_y + 3,
                       battery_x + battery_width + 3, battery_y + battery_height - 3,
                       fill=self.COLOR_WHITE)
        fill_width = int((battery_width - 4) * (battery_percent / 100))
        if fill_width > 0:
            battery_color = self.COLOR_GREEN if battery_percent > 20 else self.COLOR_RED
            self.rectangle(battery_x + 2, battery_y + 2,
                           battery_x + 2 + fill_width, battery_y + battery_height - 2,
                           fill=battery_color)

        indicator = ""
        if not power_available:
            indicator = "?"
        elif charging:
            indicator = "C"
        elif external_power:
            indicator = "P"
        if indicator:
            self.text(indicator, battery_x - 14, battery_y - 1,
                      color=self.COLOR_YELLOW if indicator == "?" else self.COLOR_WHITE,
                      font_size=12)

        signal_x = 5
        signal_y = 8
        bar_width = 3
        bar_spacing = 2
        for i in range(4):
            bar_height = 4 + (i * 2)
            bar_color = self.COLOR_WHITE if i < signal_strength else self.COLOR_DARK_GRAY
            self.rectangle(signal_x + (i * (bar_width + bar_spacing)),
                           signal_y + (12 - bar_height),
                           signal_x + (i * (bar_width + bar_spacing)) + bar_width,
                           signal_y + 12, fill=bar_color)

    def update(self) -> None:
        if self.buffer is None:
            return
        if not self.simulate and self._driver:
            try:
                pixel_data = self._pil_to_rgb565(self.buffer)
                self._driver.draw_image(0, 0, self.WIDTH, self.HEIGHT, pixel_data)
            except Exception as e:
                logger.error("Failed to update Cubie Pimoroni display: {}", e)

    def set_backlight(self, brightness: float) -> None:
        if not self.simulate and self._driver:
            self._driver.set_backlight(brightness > 0)

    def get_text_size(self, text: str, font_size: int = 16) -> Tuple[int, int]:
        try:
            font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size,
            )
        except Exception:
            font = ImageFont.load_default()
        bbox = self.draw.textbbox((0, 0), text, font=font)
        return (bbox[2] - bbox[0], bbox[3] - bbox[1])

    def cleanup(self) -> None:
        for line in self._led_lines.values():
            try:
                line.set_value(0)
                line.release()
            except Exception:
                pass
        for chip in self._led_chips:
            try:
                chip.close()
            except Exception:
                pass
        self._led_lines.clear()
        self._led_chips.clear()

        if self._driver:
            self._driver.cleanup()
            self._driver = None

        logger.info("Cubie Pimoroni adapter cleaned up")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cubie_pimoroni.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yoyopod/ui/display/adapters/cubie_pimoroni.py tests/test_cubie_pimoroni.py
git commit -m "feat: add Cubie Pimoroni display adapter (DisplayHAL over ST7789)"
```

---

### Task 4: gpiod Button Adapter

**Files:**
- Create: `src/yoyopod/ui/input/adapters/gpiod_buttons.py`
- Create: `tests/test_gpiod_buttons.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_gpiod_buttons.py`:

```python
"""Unit tests for the gpiod-based 4-button input adapter."""

from unittest.mock import MagicMock, patch
import time
import pytest

from yoyopod.ui.input.hal import InputAction


def test_adapter_capabilities():
    from yoyopod.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    caps = adapter.get_capabilities()
    assert InputAction.SELECT in caps
    assert InputAction.BACK in caps
    assert InputAction.UP in caps
    assert InputAction.DOWN in caps
    assert InputAction.HOME in caps


def test_adapter_fires_callback_on_simulate():
    from yoyopod.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    received = []
    adapter.on_action(InputAction.SELECT, lambda data: received.append(("select", data)))
    adapter._fire_action(InputAction.SELECT, {"button": "A"})
    assert len(received) == 1
    assert received[0] == ("select", {"button": "A"})


def test_clear_callbacks():
    from yoyopod.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    adapter.on_action(InputAction.SELECT, lambda data: None)
    assert len(adapter.callbacks) > 0
    adapter.clear_callbacks()
    assert len(adapter.callbacks) == 0


def test_adapter_start_stop_lifecycle():
    from yoyopod.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

    adapter = GpiodButtonAdapter(pin_config={}, simulate=True)
    adapter.start()
    assert adapter.running is True
    adapter.stop()
    assert adapter.running is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_gpiod_buttons.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the gpiod button adapter**

Create `src/yoyopod/ui/input/adapters/gpiod_buttons.py`:

```python
"""
Four-button input adapter using gpiod (libgpiod).

Reads physical buttons via Linux GPIO character device instead of
RPi.GPIO or displayhatmini. Designed for non-Pi boards where the
Pimoroni Display HAT Mini is connected.

Button mapping matches FourButtonInputAdapter:
  A -> SELECT, B -> BACK (long: HOME), X -> UP, Y -> DOWN
"""

from __future__ import annotations

import time
from collections import defaultdict
from enum import Enum
from threading import Event, Thread
from typing import Any, Callable, Dict, List, Optional

from loguru import logger

from yoyopod.ui.input.hal import InputAction, InputHAL

try:
    import gpiod

    HAS_GPIOD = True
except ImportError:
    gpiod = None  # type: ignore[assignment]
    HAS_GPIOD = False


class Button(Enum):
    """Physical button identifiers."""

    A = "A"
    B = "B"
    X = "X"
    Y = "Y"


# Button-to-action mapping
_PRESS_MAPPING: dict[Button, InputAction] = {
    Button.A: InputAction.SELECT,
    Button.B: InputAction.BACK,
    Button.X: InputAction.UP,
    Button.Y: InputAction.DOWN,
}

_LONG_PRESS_MAPPING: dict[Button, InputAction] = {
    Button.B: InputAction.HOME,
}

# Timing constants (seconds)
_DEBOUNCE_TIME = 0.05
_LONG_PRESS_TIME = 1.0


class GpiodButtonAdapter(InputHAL):
    """Four-button input via gpiod with debounce and long-press detection."""

    def __init__(
        self,
        pin_config: dict[str, Any],
        simulate: bool = False,
    ) -> None:
        self.simulate = simulate or not HAS_GPIOD
        self.callbacks: Dict[InputAction, List[Callable]] = defaultdict(list)
        self.running = False
        self._poll_thread: Optional[Thread] = None
        self._stop_event = Event()

        # GPIO line handles keyed by Button
        self._lines: dict[Button, object] = {}
        self._chips: list[object] = []

        # Button state tracking
        self._button_states: dict[Button, bool] = {b: False for b in Button}
        self._press_times: dict[Button, Optional[float]] = {b: None for b in Button}
        self._long_fired: dict[Button, bool] = {b: False for b in Button}

        if not self.simulate:
            self._open_gpio_lines(pin_config)
        else:
            logger.debug("GpiodButtonAdapter running in simulation mode")

    def _open_gpio_lines(self, pin_config: dict[str, Any]) -> None:
        """Request GPIO lines for each button."""
        button_keys = [("button_a", Button.A), ("button_b", Button.B),
                       ("button_x", Button.X), ("button_y", Button.Y)]

        for key, button in button_keys:
            pin = pin_config.get(key)
            if pin is None:
                logger.warning("No GPIO config for button {} (key={}), skipping", button.value, key)
                continue

            chip_name = pin.get("chip") if isinstance(pin, dict) else getattr(pin, "chip", None)
            line_offset = pin.get("line") if isinstance(pin, dict) else getattr(pin, "line", None)
            if chip_name is None or line_offset is None:
                logger.warning("Incomplete GPIO config for button {}, skipping", button.value)
                continue

            try:
                chip = gpiod.Chip(chip_name)
                self._chips.append(chip)
                line = chip.get_line(line_offset)
                line.request(
                    consumer=f"pimoroni-btn-{button.value}",
                    type=gpiod.LINE_REQ_DIR_IN,
                    flags=gpiod.LINE_REQ_FLAG_BIAS_DISABLE,
                )
                self._lines[button] = line
                logger.debug("Button {} on {}:{}", button.value, chip_name, line_offset)
            except Exception as e:
                logger.warning("Failed to acquire GPIO for button {}: {}", button.value, e)

        logger.info("GpiodButtonAdapter: {} of 4 buttons acquired", len(self._lines))

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._stop_event.clear()
        self._poll_thread = Thread(target=self._poll_loop, daemon=True)
        self._poll_thread.start()
        logger.info("GpiodButtonAdapter started")

    def stop(self) -> None:
        if not self.running:
            return
        self.running = False
        self._stop_event.set()
        if self._poll_thread:
            self._poll_thread.join(timeout=1.0)
        # Release GPIO lines
        for line in self._lines.values():
            try:
                line.release()
            except Exception:
                pass
        for chip in self._chips:
            try:
                chip.close()
            except Exception:
                pass
        self._lines.clear()
        self._chips.clear()
        logger.info("GpiodButtonAdapter stopped")

    def on_action(self, action: InputAction, callback: Callable[[Optional[Any]], None]) -> None:
        self.callbacks[action].append(callback)

    def clear_callbacks(self) -> None:
        self.callbacks.clear()

    def get_capabilities(self) -> List[InputAction]:
        caps = list(_PRESS_MAPPING.values())
        caps.extend(_LONG_PRESS_MAPPING.values())
        return list(set(caps))

    def _fire_action(self, action: InputAction, data: Optional[Any] = None) -> None:
        for cb in self.callbacks.get(action, []):
            try:
                cb(data)
            except Exception as e:
                logger.error("Error in button callback: {}", e)

    def _read_button(self, button: Button) -> bool:
        """Read a button GPIO line. Active-low: pressed = 0."""
        line = self._lines.get(button)
        if line is None:
            return False
        try:
            return line.get_value() == 0
        except Exception:
            return False

    def _poll_loop(self) -> None:
        """Poll button states at 10ms intervals with debounce and long-press."""
        while not self._stop_event.is_set():
            now = time.time()

            for button in Button:
                if self.simulate and button not in self._lines:
                    continue

                current = self._read_button(button)
                previous = self._button_states[button]

                # Press detected
                if current and not previous:
                    time.sleep(_DEBOUNCE_TIME)
                    current = self._read_button(button)
                    if current:
                        self._button_states[button] = True
                        self._press_times[button] = now
                        self._long_fired[button] = False

                # Release detected
                elif not current and previous:
                    self._button_states[button] = False
                    if self._press_times[button] is not None and not self._long_fired[button]:
                        action = _PRESS_MAPPING.get(button)
                        if action:
                            self._fire_action(action, {"button": button.value})
                    self._press_times[button] = None

                # Held — check long press
                elif current and previous:
                    pt = self._press_times[button]
                    if pt is not None and not self._long_fired[button]:
                        if now - pt >= _LONG_PRESS_TIME:
                            long_action = _LONG_PRESS_MAPPING.get(button)
                            if long_action:
                                self._fire_action(long_action, {"button": button.value, "long_press": True})
                            self._long_fired[button] = True

            time.sleep(0.01)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_gpiod_buttons.py -v`
Expected: ALL PASS.

- [ ] **Step 5: Commit**

```bash
git add src/yoyopod/ui/input/adapters/gpiod_buttons.py tests/test_gpiod_buttons.py
git commit -m "feat: add gpiod-based 4-button input adapter"
```

---

### Task 5: Factory Fallback Integration

**Files:**
- Modify: `src/yoyopod/ui/display/factory.py`
- Modify: `src/yoyopod/ui/input/factory.py`
- Create: `tests/test_factory_fallback.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_factory_fallback.py`:

```python
"""Tests for display and input factory fallback to Cubie adapters."""

from unittest.mock import MagicMock, patch
import pytest


def test_display_factory_falls_back_to_cubie_pimoroni():
    """When displayhatmini is unavailable but gpio config exists, use CubiePimoroniAdapter."""
    from yoyopod.config.models import GpioPin, PimoroniGpioConfig

    gpio_config = PimoroniGpioConfig(
        dc=GpioPin("gpiochip0", 109),
        cs=GpioPin("gpiochip0", 110),
        backlight=GpioPin("gpiochip1", 35),
    )

    with patch("yoyopod.ui.display.factory.detect_hardware", return_value="pimoroni"):
        with patch(
            "yoyopod.ui.display.factory._get_pimoroni_gpio_config",
            return_value=gpio_config,
        ):
            from yoyopod.ui.display.factory import get_display

            display = get_display(hardware="pimoroni", simulate=False)
            try:
                # Should have fallen back to CubiePimoroniAdapter in simulate mode
                # because actual hardware (spidev/gpiod) isn't available in CI
                assert display.DISPLAY_TYPE == "pimoroni"
                assert display.WIDTH == 320
                assert display.HEIGHT == 240
            finally:
                display.cleanup()


def test_input_factory_falls_back_to_gpiod_buttons():
    """When displayhatmini is unavailable, use GpiodButtonAdapter for pimoroni display."""
    from yoyopod.ui.input.factory import get_input_manager

    mock_display = MagicMock()
    mock_display.DISPLAY_TYPE = "pimoroni"
    mock_display.__class__.__name__ = "CubiePimoroniAdapter"
    mock_display.device = None  # No displayhatmini device

    config = {
        "input": {
            "pimoroni_gpio": {
                "button_a": {"chip": "gpiochip0", "line": 34},
                "button_b": {"chip": "gpiochip0", "line": 35},
                "button_x": {"chip": "gpiochip0", "line": 36},
                "button_y": {"chip": "gpiochip0", "line": 313},
            },
        },
    }

    manager = get_input_manager(mock_display, config=config, simulate=True)
    assert manager is not None
    assert len(manager.adapters) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_factory_fallback.py -v`
Expected: FAIL — `_get_pimoroni_gpio_config` does not exist, input factory doesn't handle gpiod fallback.

- [ ] **Step 3: Update display factory**

In `src/yoyopod/ui/display/factory.py`, add a helper and modify the pimoroni branch:

Add this import near the top:

```python
from yoyopod.config.models import PimoroniGpioConfig
```

Add this helper function after `_normalize_display_hardware`:

```python
def _get_pimoroni_gpio_config() -> PimoroniGpioConfig | None:
    """Return PimoroniGpioConfig from the active board config, or None."""
    try:
        from yoyopod.config.manager import ConfigManager

        mgr = ConfigManager()
        return mgr.config.display.pimoroni_gpio
    except Exception:
        return None
```

Replace the `if hardware == "pimoroni":` block in `get_display()`:

```python
    if hardware == "pimoroni":
        # Try Pi-native displayhatmini first
        try:
            import displayhatmini  # noqa: F401

            logger.info("Creating Pimoroni display adapter (320x240 landscape, displayhatmini)")
            from yoyopod.ui.display.adapters.pimoroni import PimoroniDisplayAdapter

            return PimoroniDisplayAdapter(simulate=False)
        except Exception:
            pass

        # Fallback: Cubie-native spidev + gpiod adapter
        gpio_config = _get_pimoroni_gpio_config()
        if gpio_config is not None and (gpio_config.dc is not None or gpio_config.cs is not None):
            logger.info("Creating Cubie Pimoroni display adapter (320x240 landscape, spidev + gpiod)")
            from yoyopod.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

            return CubiePimoroniAdapter(simulate=False, gpio_config=gpio_config)

        logger.warning("Pimoroni requested but no displayhatmini or GPIO config available")
        logger.info("Falling back to Pimoroni simulation mode")
        from yoyopod.ui.display.adapters.cubie_pimoroni import CubiePimoroniAdapter

        return CubiePimoroniAdapter(simulate=True)
```

- [ ] **Step 4: Update input factory**

In `src/yoyopod/ui/input/factory.py`, update the `display_type == "pimoroni"` branch. Replace the existing pimoroni block (lines 72-86):

```python
    if display_type == "pimoroni":
        logger.info("  Detected Pimoroni Display HAT Mini")
        display_device = getattr(display_adapter, "device", None)

        # Try Pi-native displayhatmini button reading first
        if display_device or simulate:
            try:
                from yoyopod.ui.input.adapters.four_button import FourButtonInputAdapter

                if not simulate:
                    from displayhatmini import DisplayHATMini  # noqa: F401

                button_adapter = FourButtonInputAdapter(
                    display_device=display_device,
                    simulate=simulate,
                )
                manager.add_adapter(button_adapter)
                logger.info("  -> Added 4-button input (A, B, X, Y) via displayhatmini")
            except ImportError:
                # Fallback: gpiod-based buttons
                gpio_input_config = input_config.get("pimoroni_gpio", {})
                if gpio_input_config:
                    from yoyopod.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

                    button_adapter = GpiodButtonAdapter(
                        pin_config=gpio_input_config,
                        simulate=simulate,
                    )
                    manager.add_adapter(button_adapter)
                    logger.info("  -> Added 4-button input (A, B, X, Y) via gpiod")
                else:
                    logger.warning("  -> No displayhatmini or GPIO config for button input")
        else:
            # No display device — check for gpiod config
            gpio_input_config = input_config.get("pimoroni_gpio", {})
            if gpio_input_config:
                from yoyopod.ui.input.adapters.gpiod_buttons import GpiodButtonAdapter

                button_adapter = GpiodButtonAdapter(
                    pin_config=gpio_input_config,
                    simulate=simulate,
                )
                manager.add_adapter(button_adapter)
                logger.info("  -> Added 4-button input (A, B, X, Y) via gpiod")
            else:
                logger.warning("  -> No display device or GPIO config for button input")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_factory_fallback.py -v`
Expected: ALL PASS.

- [ ] **Step 6: Run full test suite**

Run: `uv run pytest -q`
Expected: ALL PASS (no regressions).

- [ ] **Step 7: Commit**

```bash
git add src/yoyopod/ui/display/factory.py src/yoyopod/ui/input/factory.py tests/test_factory_fallback.py
git commit -m "feat: add factory fallback to Cubie Pimoroni adapters"
```

---

### Task 6: Board Config and Validation

**Files:**
- Modify: `config/boards/radxa-cubie-a7z/yoyopod_config.yaml`

- [ ] **Step 1: Add GPIO pin mapping to the Cubie board config**

Update `config/boards/radxa-cubie-a7z/yoyopod_config.yaml`:

```yaml
# Radxa Cubie A7Z board overrides.
#
# This board is auto-selected on known Cubie A7Z hardware, or can be forced with:
#   YOYOPOD_CONFIG_BOARD=radxa-cubie-a7z

audio:
  music_dir: "/home/radxa/Music"

power:
  watchdog_i2c_bus: 7

display:
  pimoroni_gpio:
    spi_bus: 1
    spi_device: 0
    spi_speed_hz: 60000000
    dc:
      chip: "gpiochip0"
      line: 109
    cs:
      chip: "gpiochip0"
      line: 110
    backlight:
      chip: "gpiochip1"
      line: 35
    led_r:
      chip: "gpiochip0"
      line: 33
    led_g:
      chip: "gpiochip1"
      line: 6
    led_b:
      chip: "gpiochip1"
      line: 7

input:
  pimoroni_gpio:
    button_a:
      chip: "gpiochip0"
      line: 34
    button_b:
      chip: "gpiochip0"
      line: 35
    button_x:
      chip: "gpiochip0"
      line: 36
    button_y:
      chip: "gpiochip0"
      line: 313
```

- [ ] **Step 2: Run full test suite to verify no regressions**

Run: `uv run pytest -q`
Expected: ALL PASS.

- [ ] **Step 3: Run compile check**

Run: `python -m compileall yoyopod tests`
Expected: No compilation errors.

- [ ] **Step 4: Commit**

```bash
git add config/boards/radxa-cubie-a7z/yoyopod_config.yaml
git commit -m "feat: add Pimoroni GPIO pin mapping to Cubie A7Z board config"
```

---

### Task 7: On-Device Smoke Test

This task is a manual validation on the Cubie A7Z board at 192.168.178.110. No code changes — just verification.

- [ ] **Step 1: Sync code to the Cubie**

```bash
yoyopod remote sync --host 192.168.178.110
```

Or if yoyopod isn't configured for this host:

```bash
ssh radxa@192.168.178.110 "cd ~/yoyo-py && git fetch origin && git checkout claude/hungry-bouman && git pull"
ssh radxa@192.168.178.110 "cd ~/yoyo-py && ~/.local/bin/uv sync --extra dev"
```

- [ ] **Step 2: Stop the running YoyoPod service**

```bash
ssh radxa@192.168.178.110 "sudo systemctl stop yoyopod@radxa"
```

Wait 3 seconds for Whisplay GPIO to be released.

- [ ] **Step 3: Test DC pin claim (risk mitigation)**

```bash
ssh radxa@192.168.178.110 "cd ~/yoyo-py && .venv/bin/python -c \"
import gpiod
chip = gpiod.Chip('gpiochip0')
line = chip.get_line(109)
line.request(consumer='dc-test', type=gpiod.LINE_REQ_DIR_OUT, default_val=0)
line.set_value(1)
line.set_value(0)
line.release()
chip.close()
print('DC pin (gpiochip0:109) claim OK')
\""
```

Expected: `DC pin (gpiochip0:109) claim OK`
If this fails, try SPI_3WIRE mode (see spec risk mitigation).

- [ ] **Step 4: Launch YoyoPod with Pimoroni display**

```bash
ssh radxa@192.168.178.110 "cd ~/yoyo-py && YOYOPOD_DISPLAY=pimoroni YOYOPOD_CONFIG_BOARD=radxa-cubie-a7z .venv/bin/python yoyopod.py"
```

Expected: Display initializes, home screen renders, backlight on.

- [ ] **Step 5: Test all 4 buttons**

Press each button and verify in the log output:
- A -> SELECT action fired
- B -> BACK action fired
- X -> UP action fired
- Y -> DOWN action fired
- Long press B -> HOME action fired

- [ ] **Step 6: Walk through screens**

Navigate through: Home -> Listen -> Playlists -> back, Talk -> contact -> back, Setup.
Verify all screens render and transitions work.

- [ ] **Step 7: Test RGB LED**

Check logs for LED init success. If the app sets LED during init, verify it lights up.

- [ ] **Step 8: Re-enable the service (optional)**

If validated, update the systemd unit environment to use `YOYOPOD_DISPLAY=pimoroni`:

```bash
ssh radxa@192.168.178.110 "sudo systemctl start yoyopod@radxa"
```
