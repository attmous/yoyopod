"""Helpers for retained LVGL views that must survive backend resets."""

from __future__ import annotations

from typing import Protocol, TypeVar

from yoyopod.ui.lvgl_binding import LvglDisplayBackend


class RetainedLvglView(Protocol):
    """Structural type shared by retained Python LVGL views."""

    backend: LvglDisplayBackend
    _built: bool
    _build_generation: int

    def build(self) -> None:
        """Rebuild the native LVGL scene for this retained view."""


RetainedLvglViewT = TypeVar("RetainedLvglViewT", bound=RetainedLvglView)


def current_scene_generation(backend: LvglDisplayBackend) -> int:
    """Return the backend scene generation with a backwards-safe default."""

    return int(getattr(backend, "scene_generation", 0))


def current_retained_view(
    view: RetainedLvglViewT | None,
    backend: LvglDisplayBackend | None,
) -> RetainedLvglViewT | None:
    """Return the cached retained view only when it still matches the backend."""

    if view is None or backend is None:
        return None
    if getattr(view, "backend", None) is not backend:
        return None
    if view._build_generation != current_scene_generation(backend):
        return None
    if not view_is_ready(view):
        return None
    return view


def view_is_ready(view: RetainedLvglView) -> bool:
    """Return True when the backend can safely build or sync a native scene."""

    return view.backend.binding is not None and bool(getattr(view.backend, "initialized", True))


def should_build_retained_view(view: RetainedLvglView) -> bool:
    """Return True when the retained Python view must rebuild its native scene."""

    if not view_is_ready(view):
        return False
    return (
        not view._built
        or view._build_generation != current_scene_generation(view.backend)
    )


def ensure_retained_view_built(view: RetainedLvglView) -> bool:
    """Rebuild the retained native scene when the backend cleared it underneath us."""

    if not view_is_ready(view):
        return False
    if view._build_generation != current_scene_generation(view.backend):
        view._built = False
    if not view._built:
        view.build()
    return view._built and view_is_ready(view)


def mark_retained_view_built(view: RetainedLvglView) -> None:
    """Record that the retained view matches the current backend scene generation."""

    view._built = True
    view._build_generation = current_scene_generation(view.backend)


def mark_retained_view_destroyed(view: RetainedLvglView) -> None:
    """Record that the retained view no longer has a live native scene."""

    view._built = False
    view._build_generation = -1
