"""
gpiod API compatibility layer for gpiod 1.x and 2.x.

gpiod 1.x (Debian Bullseye): lowercase ``gpiod.chip()``, ``gpiod.line_request``
gpiod 2.x (newer distros): uppercase ``gpiod.Chip()``, ``gpiod.LINE_REQ_DIR_OUT``

This module normalizes both APIs behind a minimal interface used by the
ST7789 SPI driver and gpiod button adapter.
"""

from __future__ import annotations

from typing import Any

from loguru import logger

try:
    import gpiod as _gpiod

    HAS_GPIOD = True
except ImportError:
    _gpiod = None  # type: ignore[assignment]
    HAS_GPIOD = False


def _is_v1() -> bool:
    """Return True if gpiod is the 1.x API (lowercase ``chip``)."""
    return HAS_GPIOD and hasattr(_gpiod, "chip") and not hasattr(_gpiod, "Chip")


def open_chip(name: str) -> Any:
    """Open a GPIO chip by name, normalizing between gpiod 1.x and 2.x."""
    if not HAS_GPIOD:
        raise RuntimeError("gpiod module is required but not installed")

    # Both gpiod 1.x and some 2.x builds expect /dev/ paths
    if not name.startswith("/dev/"):
        name = f"/dev/{name}"

    if _is_v1():
        return _gpiod.chip(name)
    else:
        return _gpiod.Chip(name)


def request_output(chip: Any, line_offset: int, consumer: str, default_val: int = 0) -> Any:
    """Request a GPIO line as output."""
    line = chip.get_line(line_offset)

    if _is_v1():
        config = _gpiod.line_request()
        config.consumer = consumer
        config.request_type = _gpiod.line_request.DIRECTION_OUTPUT
        line.request(config, default_val)
    else:
        line.request(
            consumer=consumer,
            type=_gpiod.LINE_REQ_DIR_OUT,
            default_val=default_val,
        )

    return line


def request_input(chip: Any, line_offset: int, consumer: str) -> Any:
    """Request a GPIO line as input with bias disabled."""
    line = chip.get_line(line_offset)

    if _is_v1():
        config = _gpiod.line_request()
        config.consumer = consumer
        config.request_type = _gpiod.line_request.DIRECTION_INPUT
        config.flags = _gpiod.line_request.FLAG_BIAS_DISABLE
        line.request(config)
    else:
        line.request(
            consumer=consumer,
            type=_gpiod.LINE_REQ_DIR_IN,
            flags=_gpiod.LINE_REQ_FLAG_BIAS_DISABLE,
        )

    return line
