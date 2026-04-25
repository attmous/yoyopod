"""Focused tests for the cross-screen overlay runtime contract."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from yoyopod.core.overlays import CrossScreenOverlayRuntime


@dataclass(slots=True)
class _OverlayStub:
    """Minimal overlay double with configurable active state."""

    name: str
    priority: int
    active: bool = False
    is_active_calls: list[float] = field(default_factory=list)
    render_calls: list[float] = field(default_factory=list)

    def is_active(self, now: float) -> bool:
        self.is_active_calls.append(now)
        return self.active

    def render(self, now: float) -> None:
        self.render_calls.append(now)


def test_overlay_runtime_renders_highest_priority_active_overlay() -> None:
    """Only the highest-priority active overlay should render on each update."""

    runtime = CrossScreenOverlayRuntime()
    lower = _OverlayStub(name="lower", priority=10, active=True)
    higher = _OverlayStub(name="higher", priority=20, active=True)
    runtime.register(lower)
    runtime.register(higher)

    handled = runtime.update(now=5.0, render=True)

    assert handled is True
    assert lower.is_active_calls == [5.0]
    assert higher.is_active_calls == [5.0]
    assert lower.render_calls == []
    assert higher.render_calls == [5.0]
    assert runtime.last_active_overlay_name == "higher"


def test_overlay_runtime_can_evaluate_without_rendering() -> None:
    """State-only updates should not render even when an overlay is active."""

    runtime = CrossScreenOverlayRuntime()
    overlay = _OverlayStub(name="power", priority=100, active=True)
    runtime.register(overlay)

    handled = runtime.update(now=8.0, render=False)

    assert handled is True
    assert overlay.is_active_calls == [8.0]
    assert overlay.render_calls == []
    assert runtime.last_active_overlay_name == "power"


def test_overlay_runtime_clears_active_name_when_no_overlays_are_active() -> None:
    """The runtime should clear the active overlay marker when nothing is active."""

    runtime = CrossScreenOverlayRuntime()
    overlay = _OverlayStub(name="power", priority=100, active=True)
    runtime.register(overlay)
    runtime.update(now=1.0, render=False)

    overlay.active = False
    handled = runtime.update(now=2.0, render=False)

    assert handled is False
    assert runtime.last_active_overlay_name is None


def test_overlay_runtime_rejects_duplicate_overlay_names() -> None:
    """Overlay names must be unique so runtime diagnostics stay deterministic."""

    runtime = CrossScreenOverlayRuntime()
    runtime.register(_OverlayStub(name="power", priority=100))

    with pytest.raises(ValueError, match="Duplicate overlay registration"):
        runtime.register(_OverlayStub(name="power", priority=50))
