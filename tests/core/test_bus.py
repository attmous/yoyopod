"""Tests for the scaffold event bus."""

from __future__ import annotations

import threading
from dataclasses import dataclass

import pytest

import yoyopod.core.bus as bus_module
from yoyopod.core import Bus


@dataclass(frozen=True, slots=True)
class DemoEvent:
    value: str


def test_bus_publish_requires_main_thread() -> None:
    bus = Bus()
    errors: list[str] = []

    worker = threading.Thread(
        target=lambda: _capture_publish_error(bus=bus, errors=errors),
        name="bus-worker",
    )
    worker.start()
    worker.join()

    assert errors == ["Bus.publish() must be called on the main thread"]


def test_bus_subscribe_requires_main_thread() -> None:
    bus = Bus()
    errors: list[str] = []

    worker = threading.Thread(
        target=lambda: _capture_subscribe_error(bus=bus, errors=errors),
        name="bus-subscriber",
    )
    worker.start()
    worker.join()

    assert errors == ["Bus.subscribe() must be called on the main thread"]


def test_bus_drain_requires_main_thread() -> None:
    bus = Bus()
    bus.publish(DemoEvent(value="queued"))
    errors: list[str] = []

    worker = threading.Thread(
        target=lambda: _capture_drain_error(bus=bus, errors=errors),
        name="bus-drain-worker",
    )
    worker.start()
    worker.join()

    assert errors == ["Bus.drain() must be called on the main thread"]
    assert bus.pending_count() == 1


def test_bus_publish_queues_until_drain() -> None:
    bus = Bus()
    seen: list[str] = []
    bus.subscribe(DemoEvent, lambda event: seen.append(event.value))

    bus.publish(DemoEvent(value="queued"))

    assert seen == []
    assert bus.pending_count() == 1
    assert bus.drain() == 1
    assert seen == ["queued"]


def test_bus_non_strict_mode_logs_and_continues() -> None:
    bus = Bus()
    seen: list[str] = []

    def boom(event: DemoEvent) -> None:
        raise RuntimeError(f"bad event: {event.value}")

    bus.subscribe(DemoEvent, boom)
    bus.subscribe(DemoEvent, lambda event: seen.append(event.value))

    bus.publish(DemoEvent(value="still-runs"))

    assert bus.drain() == 1
    assert seen == ["still-runs"]


def test_bus_reports_subscription_counts_by_event_type() -> None:
    bus = Bus()
    bus.subscribe(DemoEvent, lambda event: None)
    bus.subscribe(DemoEvent, lambda event: None)
    bus.subscribe(object, lambda event: None)

    assert bus.subscription_counts() == {"DemoEvent": 2, "object": 1}


def test_bus_hot_path_logs_subscriptions_with_deferred_formatting(monkeypatch) -> None:
    trace_calls: list[tuple[str, tuple[object, ...]]] = []
    debug_calls: list[tuple[str, tuple[object, ...]]] = []

    monkeypatch.setattr(
        bus_module.logger,
        "trace",
        lambda message, *args: trace_calls.append((message, args)),
    )
    monkeypatch.setattr(
        bus_module.logger,
        "debug",
        lambda message, *args: debug_calls.append((message, args)),
    )

    bus = Bus()
    bus.subscribe(DemoEvent, lambda event: None)

    assert trace_calls == [("Subscribed scaffold bus handler for {}", ("DemoEvent",))]
    assert debug_calls == []


def test_bus_strict_mode_reraises_handler_errors() -> None:
    bus = Bus(strict=True)
    bus.subscribe(DemoEvent, lambda event: (_ for _ in ()).throw(RuntimeError("boom")))
    bus.publish(DemoEvent(value="strict"))

    with pytest.raises(RuntimeError, match="boom"):
        bus.drain()


def _capture_publish_error(*, bus: Bus, errors: list[str]) -> None:
    try:
        bus.publish(DemoEvent(value="off-main"))
    except RuntimeError as exc:
        errors.append(str(exc))


def _capture_subscribe_error(*, bus: Bus, errors: list[str]) -> None:
    try:
        bus.subscribe(DemoEvent, lambda event: None)
    except RuntimeError as exc:
        errors.append(str(exc))


def _capture_drain_error(*, bus: Bus, errors: list[str]) -> None:
    try:
        bus.drain()
    except RuntimeError as exc:
        errors.append(str(exc))
