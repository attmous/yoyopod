"""Shared scaffold app builders and queue helpers for tests."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, TypeVar

from yoyopod.core.application import YoyoPodApp

_T = TypeVar("_T")


def build_test_app(*, strict_bus: bool = True, log_buffer_size: int = 64) -> YoyoPodApp:
    """Build a scaffold application suitable for unit tests."""

    return YoyoPodApp(strict_bus=strict_bus, log_buffer_size=log_buffer_size)


def drain_all(app: YoyoPodApp, *, max_rounds: int = 100) -> int:
    """Drain scheduler and bus work until the scaffold app goes idle."""

    total_processed = 0
    for _ in range(max_rounds):
        processed = app.scheduler.drain()
        processed += app.bus.drain()
        total_processed += processed
        if processed == 0:
            return total_processed
    raise RuntimeError("drain_all() exceeded max_rounds; scaffold queues never went idle")


def assert_events_contain(
    events: Iterable[object],
    event_type: type[_T],
    /,
    **expected_attrs: Any,
) -> _T:
    """Return the first matching event or raise an AssertionError."""

    for event in events:
        if not isinstance(event, event_type):
            continue
        if all(getattr(event, name) == value for name, value in expected_attrs.items()):
            return event
    raise AssertionError(
        f"No {event_type.__name__} matched expected attrs {expected_attrs!r} in {list(events)!r}"
    )
