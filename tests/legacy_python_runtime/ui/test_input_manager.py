"""Tests for input-manager activity callbacks."""

from __future__ import annotations

import yoyopod.ui.input.manager as input_manager_module
from yoyopod.ui.input import InputAction, InputManager


class FakeActivityAdapter:
    """Minimal adapter exposing raw activity callbacks for wake testing."""

    def __init__(self) -> None:
        self.activity_callbacks = []

    def start(self) -> None:
        return None

    def stop(self) -> None:
        return None

    def on_action(self, action, callback) -> None:
        return None

    def clear_callbacks(self) -> None:
        return None

    def get_capabilities(self) -> list[InputAction]:
        return []

    def on_activity(self, callback) -> None:
        self.activity_callbacks.append(callback)

    def emit_activity(self, data=None) -> None:
        for callback in self.activity_callbacks:
            callback(data)


def test_input_manager_notifies_activity_callbacks_for_each_action() -> None:
    """Every semantic action should also trigger registered activity listeners."""

    manager = InputManager()
    events: list[tuple[str, object | None]] = []

    manager.on_activity(lambda action, data: events.append((action.value, data)))

    manager.simulate_action(InputAction.SELECT, {"source": "test"})
    manager.simulate_action(InputAction.BACK)

    assert events == [
        ("select", {"source": "test"}),
        ("back", None),
    ]


def test_input_manager_forwards_raw_adapter_activity() -> None:
    """Raw adapter activity should wake the app even before a semantic action resolves."""

    manager = InputManager()
    adapter = FakeActivityAdapter()
    events: list[tuple[str | None, object | None]] = []

    manager.on_activity(lambda action, data: events.append((None if action is None else action.value, data)))
    manager.add_adapter(adapter)
    adapter.emit_activity({"pressed": True})

    assert events == [
        (None, {"pressed": True}),
    ]


def test_input_manager_action_logs_trace_with_deferred_formatting(monkeypatch) -> None:
    """Action dispatch logging should stay at TRACE and pass format args lazily."""
    manager = InputManager()
    seen_data: list[object | None] = []
    trace_calls: list[tuple[str, tuple[object, ...]]] = []
    debug_calls: list[tuple[str, tuple[object, ...]]] = []

    manager.on_action(InputAction.SELECT, lambda data: seen_data.append(data))

    monkeypatch.setattr(
        input_manager_module.logger,
        "trace",
        lambda message, *args: trace_calls.append((message, args)),
    )
    monkeypatch.setattr(
        input_manager_module.logger,
        "debug",
        lambda message, *args: debug_calls.append((message, args)),
    )

    manager._fire_action(InputAction.SELECT, {"source": "test"})
    manager._fire_action(InputAction.BACK)

    assert seen_data == [{"source": "test"}]
    assert trace_calls == [
        ("Action fired: {} (data: {})", ("select", {"source": "test"})),
        ("Action {} fired but no callbacks registered", ("back",)),
    ]
    assert debug_calls == []
