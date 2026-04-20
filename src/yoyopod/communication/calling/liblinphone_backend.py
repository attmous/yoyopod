"""Compatibility alias for callers still importing calling.liblinphone_backend."""

from __future__ import annotations

from typing import Any

from yoyopod.communication.integrations.liblinphone import backend as _backend_impl

LiblinphoneBackend = _backend_impl.LiblinphoneBackend


def __getattr__(name: str) -> Any:
    return getattr(_backend_impl, name)


__all__ = ["LiblinphoneBackend"]
