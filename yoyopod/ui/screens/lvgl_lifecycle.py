"""Helpers for retained LVGL views that must survive backend resets."""

from __future__ import annotations

from typing import Protocol, TypeVar

from yoyopod.ui.lvgl_binding import LvglDisplayBackend


class RetainedLvglView(Protocol):
    """Structural type shared by retained Python LVGL views."""

    backend: LvglDisplayBackend
    scene_key: str
    _built: bool
    _build_generation: int

    def build(self) -> None:
        """Rebuild the native LVGL scene for this retained view."""


RetainedLvglViewT = TypeVar("RetainedLvglViewT", bound=RetainedLvglView)


def current_scene_generation(backend: LvglDisplayBackend) -> int:
    """Return the backend scene generation with a backwards-safe default."""

    return int(getattr(backend, "scene_generation", 0))


def _retained_scene_claims(backend: LvglDisplayBackend) -> dict[str, int]:
    """Return the per-backend scene-ownership registry."""

    claims = getattr(backend, "_retained_scene_claims", None)
    if claims is None:
        claims = {}
        setattr(backend, "_retained_scene_claims", claims)
    return claims


def retained_scene_claimed_by(view: RetainedLvglView) -> bool:
    """Return True when this view still owns its retained native scene type."""

    return _retained_scene_claims(view.backend).get(view.scene_key) == id(view)


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
    if not retained_scene_claimed_by(view):
        return None
    if not view_is_ready(view):
        return None
    return view


def view_is_ready(view: RetainedLvglView) -> bool:
    """Return True when the backend can safely build or sync a native scene."""

    return view.backend.binding is not None and bool(getattr(view.backend, "initialized", False))


def should_build_retained_view(view: RetainedLvglView) -> bool:
    """Return True when the retained Python view must rebuild its native scene."""

    if not view_is_ready(view):
        return False
    return (
        not view._built
        or view._build_generation != current_scene_generation(view.backend)
        or not retained_scene_claimed_by(view)
    )


def ensure_retained_view_built(view: RetainedLvglView) -> bool:
    """Rebuild the retained native scene when the backend cleared it underneath us."""

    if not view_is_ready(view):
        return False
    if (
        view._build_generation != current_scene_generation(view.backend)
        or not retained_scene_claimed_by(view)
    ):
        view._built = False
    if not view._built:
        view.build()
    return view._built and view_is_ready(view)


def mark_retained_view_built(view: RetainedLvglView) -> None:
    """Record that this view is the current owner of its pooled retained scene."""

    view._built = True
    view._build_generation = current_scene_generation(view.backend)
    _retained_scene_claims(view.backend)[view.scene_key] = id(view)


def mark_retained_view_destroyed(view: RetainedLvglView) -> None:
    """Record that the retained view no longer has a live native scene."""

    view._built = False
    view._build_generation = -1
    claims = _retained_scene_claims(view.backend)
    if claims.get(view.scene_key) == id(view):
        claims.pop(view.scene_key, None)
