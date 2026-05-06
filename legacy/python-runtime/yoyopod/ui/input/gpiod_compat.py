"""
gpiod API compatibility layer for the Python bindings used by YoYoPod.

The project targets the historical Python gpiod layouts that expose
``chip()/line_request`` or ``Chip()/LINE_REQ_*`` with line-level requests.
Some environments also provide the official libgpiod Python bindings, so this
module keeps the interface narrow and feature-detects when edge-event requests
are available.
"""

from __future__ import annotations

import inspect
import select
from typing import Any

from loguru import logger

try:
    import gpiod as _gpiod

    HAS_GPIOD = True
except ImportError:
    _gpiod = None  # type: ignore[assignment]
    HAS_GPIOD = False


class _ChipHandle:
    """Carry the normalized chip path alongside the runtime chip object."""

    def __init__(self, chip: Any, path: str) -> None:
        self._chip = chip
        self._path = path

    def __getattr__(self, name: str) -> Any:
        return getattr(self._chip, name)


class _RequestedLineHandle:
    """Expose a line-like API over libgpiod v2 multi-line request objects."""

    def __init__(self, request: Any, line_offset: int) -> None:
        self._request = request
        self._line_offset = line_offset

    def get_value(self) -> Any:
        getter = getattr(self._request, "get_value", None)
        if callable(getter):
            try:
                return _normalize_input_value(getter(self._line_offset))
            except TypeError:
                return _normalize_input_value(getter())

        getter = getattr(self._request, "get_values", None)
        if callable(getter):
            values = getter([self._line_offset])
            return _normalize_input_value(list(values)[0])

        raise RuntimeError("Requested line does not expose get_value()")

    def set_value(self, value: Any) -> None:
        coerced_value = _coerce_output_value(value)
        setter = getattr(self._request, "set_value", None)
        if callable(setter):
            try:
                setter(self._line_offset, coerced_value)
                return
            except TypeError:
                setter(coerced_value)
                return

        setter = getattr(self._request, "set_values", None)
        if callable(setter):
            try:
                setter({self._line_offset: coerced_value})
            except TypeError:
                setter([coerced_value])
            return

        raise RuntimeError("Requested line does not expose set_value()")

    def release(self) -> None:
        releaser = getattr(self._request, "release", None)
        if callable(releaser):
            releaser()
            return

        closer = getattr(self._request, "close", None)
        if callable(closer):
            closer()

    def read_edge_events(self) -> list[Any]:
        reader = getattr(self._request, "read_edge_events", None)
        if not callable(reader):
            raise RuntimeError("Requested line does not expose edge-event reads")

        events = reader()
        if events is None:
            return []

        filtered: list[Any] = []
        for event in events:
            event_offset = getattr(event, "line_offset", getattr(event, "offset", None))
            if event_offset is None or event_offset == self._line_offset:
                filtered.append(event)
        return filtered

    @property
    def fd(self) -> Any:
        return getattr(self._request, "fd", None)

    def fileno(self) -> Any:
        fileno = getattr(self._request, "fileno", None)
        if callable(fileno):
            return fileno()
        return self.fd


def _is_v1() -> bool:
    return HAS_GPIOD and hasattr(_gpiod, "chip") and not hasattr(_gpiod, "Chip")


def _resolve_gpiod_attr(*paths: str) -> Any:
    if not HAS_GPIOD:
        return None

    for path in paths:
        target = _gpiod
        resolved = True
        for part in path.split("."):
            if not hasattr(target, part):
                resolved = False
                break
            target = getattr(target, part)
        if resolved:
            return target

    return None


def _supports_v2_requests(chip: Any) -> bool:
    raw_chip = getattr(chip, "_chip", chip)
    return hasattr(_gpiod, "LineSettings") and (
        callable(getattr(raw_chip, "request_lines", None))
        or callable(getattr(_gpiod, "request_lines", None))
    )


def _make_line_settings(
    *,
    direction: Any = None,
    bias: Any = None,
    edge_detection: Any = None,
    output_value: Any = None,
) -> Any:
    line_settings_cls = getattr(_gpiod, "LineSettings", None)
    if line_settings_cls is None:
        raise RuntimeError("gpiod LineSettings is unavailable")

    kwargs = {}
    if direction is not None:
        kwargs["direction"] = direction
    if bias is not None:
        kwargs["bias"] = bias
    if edge_detection is not None:
        kwargs["edge_detection"] = edge_detection
    if output_value is not None:
        kwargs["output_value"] = output_value

    try:
        return line_settings_cls(**kwargs)
    except TypeError:
        settings = line_settings_cls()
        for name, value in kwargs.items():
            setattr(settings, name, value)
        return settings


def _call_with_first_supported_signature(
    func: Any,
    candidates: tuple[tuple[tuple[Any, ...], dict[str, Any]], ...],
) -> Any:
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        signature = None

    if signature is not None:
        for args, kwargs in candidates:
            try:
                signature.bind(*args, **kwargs)
            except TypeError:
                continue
            return func(*args, **kwargs)
        raise TypeError("No compatible request_lines signature matched")

    signature_errors: list[TypeError] = []
    for args, kwargs in candidates:
        try:
            return func(*args, **kwargs)
        except TypeError as exc:
            message = str(exc)
            if "keyword" not in message and "positional" not in message:
                raise
            signature_errors.append(exc)

    if signature_errors:
        raise signature_errors[-1]

    raise TypeError("No compatible request_lines signature matched")


def _request_v2_line(
    chip: Any,
    line_offset: int,
    consumer: str,
    *,
    settings: Any,
) -> _RequestedLineHandle:
    raw_chip = getattr(chip, "_chip", chip)
    config = {line_offset: settings}

    request = None
    request_lines = getattr(raw_chip, "request_lines", None)
    if callable(request_lines):
        request = _call_with_first_supported_signature(
            request_lines,
            (
                ((), {"consumer": consumer, "config": config}),
                ((), {"config": config, "consumer": consumer}),
            ),
        )

    if request is None:
        request_lines = getattr(_gpiod, "request_lines", None)
        chip_path = getattr(chip, "_path", None)
        if not callable(request_lines) or chip_path is None:
            raise RuntimeError("gpiod v2 request_lines() is unavailable")

        request = _call_with_first_supported_signature(
            request_lines,
            (
                ((chip_path,), {"consumer": consumer, "config": config}),
                ((), {"path": chip_path, "consumer": consumer, "config": config}),
                ((chip_path, consumer, config), {}),
            ),
        )

    if request is None:
        raise RuntimeError("Failed to request libgpiod v2 line")

    return _RequestedLineHandle(request, line_offset)


def _resolve_output_value(raw_value: int) -> Any:
    if raw_value:
        active = _resolve_gpiod_attr("line.Value.ACTIVE", "Value.ACTIVE")
        return raw_value if active is None else active

    inactive = _resolve_gpiod_attr("line.Value.INACTIVE", "Value.INACTIVE")
    return raw_value if inactive is None else inactive


def _coerce_output_value(value: Any) -> Any:
    if isinstance(value, bool):
        return _resolve_output_value(int(value))
    if isinstance(value, int):
        return _resolve_output_value(value)
    return value


def _normalize_input_value(value: Any) -> Any:
    inactive = _resolve_gpiod_attr("line.Value.INACTIVE", "Value.INACTIVE")
    active = _resolve_gpiod_attr("line.Value.ACTIVE", "Value.ACTIVE")

    if inactive is not None and value == inactive:
        return 0
    if active is not None and value == active:
        return 1

    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value

    normalized = str(getattr(value, "name", value)).rsplit(".", 1)[-1].lower()
    if normalized in {"inactive", "low"}:
        return 0
    if normalized in {"active", "high"}:
        return 1

    return value


def open_chip(name: str) -> Any:
    if not HAS_GPIOD:
        raise RuntimeError("gpiod module is required but not installed")

    if not name.startswith("/dev/"):
        name = f"/dev/{name}"

    chip = _gpiod.chip(name) if _is_v1() else _gpiod.Chip(name)
    return _ChipHandle(chip, name)


def request_output(chip: Any, line_offset: int, consumer: str, default_val: int = 0) -> Any:
    raw_chip = getattr(chip, "_chip", chip)
    if _supports_v2_requests(chip):
        direction_output = _resolve_gpiod_attr("line.Direction.OUTPUT", "Direction.OUTPUT")
        settings = _make_line_settings(
            direction=direction_output,
            output_value=_resolve_output_value(default_val),
        )
        return _request_v2_line(chip, line_offset, consumer, settings=settings)

    line = raw_chip.get_line(line_offset)
    if _is_v1():
        config = _gpiod.line_request()
        config.consumer = consumer
        config.request_type = _gpiod.line_request.DIRECTION_OUTPUT
        line.request(config, default_val)
    else:
        line.request(consumer=consumer, type=_gpiod.LINE_REQ_DIR_OUT, default_val=default_val)

    return line


def request_input(chip: Any, line_offset: int, consumer: str) -> Any:
    raw_chip = getattr(chip, "_chip", chip)
    if _supports_v2_requests(chip):
        direction_input = _resolve_gpiod_attr("line.Direction.INPUT", "Direction.INPUT")
        bias_disabled = _resolve_gpiod_attr("line.Bias.DISABLED", "Bias.DISABLED")
        settings = _make_line_settings(direction=direction_input, bias=bias_disabled)
        return _request_v2_line(chip, line_offset, consumer, settings=settings)

    line = raw_chip.get_line(line_offset)
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
    if not HAS_GPIOD:
        raise RuntimeError("gpiod module is required but not installed")

    raw_chip = getattr(chip, "_chip", chip)
    if _supports_v2_requests(chip):
        direction_input = _resolve_gpiod_attr("line.Direction.INPUT", "Direction.INPUT")
        bias_disabled = _resolve_gpiod_attr("line.Bias.DISABLED", "Bias.DISABLED")
        both_edges = _resolve_gpiod_attr(
            "line.Edge.BOTH",
            "line.Edge.BOTH_EDGES",
            "Edge.BOTH",
            "Edge.BOTH_EDGES",
        )
        settings = _make_line_settings(
            direction=direction_input,
            bias=bias_disabled,
            edge_detection=both_edges,
        )
        return _request_v2_line(chip, line_offset, consumer, settings=settings)

    line = raw_chip.get_line(line_offset)
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
    getter = getattr(line, "event_get_fd", None)
    if callable(getter):
        try:
            return _normalize_event_fd(getter())
        except Exception as exc:
            logger.debug("Failed to read GPIO event fd: {}", exc)
            return None

    fileno = getattr(line, "fileno", None)
    if callable(fileno):
        try:
            return _normalize_event_fd(fileno())
        except Exception as exc:
            logger.debug("Failed to read GPIO event fileno: {}", exc)
            return None

    return _normalize_event_fd(getattr(line, "fd", None))


def read_edge_events(line: Any) -> list[Any]:
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
