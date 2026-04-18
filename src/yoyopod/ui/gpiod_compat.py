"""
gpiod API compatibility layer for the legacy Python bindings used by YoyoPod.

The project primarily targets the historical Python gpiod layouts that expose
``chip()/line_request`` or ``Chip()/LINE_REQ_*`` with line-level requests.
Some environments also provide the official libgpiod Python bindings, so this
module keeps the interface narrow and feature-detects when edge-event requests
are available.
"""

from __future__ import annotations

import select
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


def request_input_events(chip: Any, line_offset: int, consumer: str) -> Any:
    """Request a GPIO line for both-edge events when the runtime supports it."""
    if not HAS_GPIOD:
        raise RuntimeError("gpiod module is required but not installed")

    line = chip.get_line(line_offset)

    if _is_v1():
        config = _gpiod.line_request()
        config.consumer = consumer
        config.request_type = _gpiod.line_request.EVENT_BOTH_EDGES
        config.flags = _gpiod.line_request.FLAG_BIAS_DISABLE
        line.request(config)
        return line

    if hasattr(_gpiod, "LINE_REQ_EV_BOTH_EDGES"):
        line.request(
            consumer=consumer,
            type=_gpiod.LINE_REQ_EV_BOTH_EDGES,
            flags=_gpiod.LINE_REQ_FLAG_BIAS_DISABLE,
        )
        return line

    raise RuntimeError("gpiod edge-event requests are unavailable")


def _normalize_event_fd(candidate: Any) -> int | None:
    """Return a waitable GPIO event fd or ``None`` when the runtime reports none."""
    try:
        event_fd = int(candidate)
    except Exception as exc:
        logger.debug("Failed to normalize GPIO event fd: {}", exc)
        return None

    if event_fd < 0:
        logger.debug("Ignoring invalid negative GPIO event fd: {}", event_fd)
        return None

    return event_fd


def get_event_fd(line: Any) -> int | None:
    """Return the file descriptor used for waiting on GPIO edge events."""
    getter = getattr(line, "event_get_fd", None)
    if callable(getter):
        try:
            return _normalize_event_fd(getter())
        except Exception as exc:
            logger.debug("Failed to read GPIO event fd: {}", exc)
            return None

    fd = getattr(line, "fd", None)
    return _normalize_event_fd(fd)


def read_edge_events(line: Any) -> list[Any]:
    """Drain the currently queued edge events for one requested line."""
    reader = getattr(line, "read_edge_events", None)
    if callable(reader):
        events = reader()
        return list(events) if events is not None else []

    reader = getattr(line, "event_read", None)
    if callable(reader):
        events: list[Any] = []
        event_fd = get_event_fd(line)

        while True:
            event = reader()
            if event is None:
                break

            events.append(event)

            if event_fd is None:
                break

            try:
                ready, _, _ = select.select([event_fd], [], [], 0.0)
            except (OSError, ValueError) as exc:
                logger.debug(
                    "Failed to drain legacy GPIO edge queue from fd {}: {}",
                    event_fd,
                    exc,
                )
                break

            if not ready:
                break

        return events

    raise RuntimeError("Requested line does not expose edge-event reads")
