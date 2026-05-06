"""Unit tests for retained LVGL Python-view lifecycle helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from yoyopod.ui.screens.lvgl_lifecycle import (
    current_retained_view,
    mark_retained_view_built,
    mark_retained_view_destroyed,
    should_build_retained_view,
    view_is_ready,
)


class FakeBackend:
    """Minimal backend stub for retained-scene ownership tests."""

    def __init__(self) -> None:
        self.binding = object()
        self.initialized = True
        self.scene_generation = 0


@dataclass(slots=True)
class SharedSceneView:
    """Small retained-view double that shares one native scene key."""

    scene_key: ClassVar[str] = "shared"
    backend: FakeBackend
    _built: bool = False
    _build_generation: int = -1

    def build(self) -> None:
        mark_retained_view_built(self)

    def destroy(self) -> None:
        mark_retained_view_destroyed(self)


class MissingInitializedBackend:
    """Backend stub that intentionally omits the initialized flag."""

    def __init__(self) -> None:
        self.binding = object()
        self.scene_generation = 0


def test_current_retained_view_rejects_stale_shared_scene_owner() -> None:
    """Only the latest wrapper for one native scene key should stay reusable."""

    backend = FakeBackend()
    first = SharedSceneView(backend)
    second = SharedSceneView(backend)

    mark_retained_view_built(first)
    assert current_retained_view(first, backend) is first

    mark_retained_view_built(second)

    assert current_retained_view(first, backend) is None
    assert current_retained_view(second, backend) is second


def test_view_is_ready_requires_explicit_backend_initialization() -> None:
    """Retained-scene helpers should fail closed on incomplete backend doubles."""

    backend = MissingInitializedBackend()
    view = SharedSceneView(backend)  # type: ignore[arg-type]

    mark_retained_view_built(view)

    assert view_is_ready(view) is False
    assert current_retained_view(view, backend) is None


def test_destroyed_retained_view_releases_scene_claim_and_requires_rebuild() -> None:
    """Explicit cleanup should drop retained-scene ownership until the next build."""

    backend = FakeBackend()
    view = SharedSceneView(backend)

    mark_retained_view_built(view)
    assert current_retained_view(view, backend) is view

    view.destroy()

    assert current_retained_view(view, backend) is None
    assert should_build_retained_view(view) is True

    view.build()

    assert current_retained_view(view, backend) is view
