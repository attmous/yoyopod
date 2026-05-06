"""Tests for scaffold test-support helpers."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests.fixtures.app import assert_events_contain, build_test_app, drain_all
from yoyopod.core.application import YoyoPodApp


@dataclass(frozen=True, slots=True)
class DemoEvent:
    value: str


def test_build_test_app_returns_shell() -> None:
    app = build_test_app()
    assert isinstance(app, YoyoPodApp)


def test_drain_all_advances_scheduler_and_bus() -> None:
    app = build_test_app()
    seen: list[str] = []
    app.bus.subscribe(DemoEvent, lambda event: seen.append(event.value))
    app.scheduler.run_on_main(lambda: app.bus.publish(DemoEvent(value="from-callback")))

    assert drain_all(app) == 1
    assert seen == ["from-callback"]


def test_assert_events_contain_returns_matching_event() -> None:
    events = [DemoEvent(value="first"), DemoEvent(value="second")]

    matched = assert_events_contain(events, DemoEvent, value="second")

    assert matched == DemoEvent(value="second")


def test_assert_events_contain_raises_for_missing_match() -> None:
    with pytest.raises(AssertionError, match="DemoEvent"):
        assert_events_contain([DemoEvent(value="first")], DemoEvent, value="missing")
