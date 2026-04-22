"""Canonical VoIP backend adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.backends.voip.binding import (
        LiblinphoneBinding,
        LiblinphoneBindingError,
        LiblinphoneNativeEvent,
    )
    from yoyopod.backends.voip.liblinphone import LiblinphoneBackend
    from yoyopod.backends.voip.mock_backend import MockVoIPBackend
    from yoyopod.backends.voip.protocol import VoIPBackend, VoIPIterateMetrics


_EXPORTS = {
    "LiblinphoneBackend": ("yoyopod.backends.voip.liblinphone", "LiblinphoneBackend"),
    "LiblinphoneBinding": ("yoyopod.backends.voip.binding", "LiblinphoneBinding"),
    "LiblinphoneBindingError": (
        "yoyopod.backends.voip.binding",
        "LiblinphoneBindingError",
    ),
    "LiblinphoneNativeEvent": (
        "yoyopod.backends.voip.binding",
        "LiblinphoneNativeEvent",
    ),
    "MockVoIPBackend": ("yoyopod.backends.voip.mock_backend", "MockVoIPBackend"),
    "VoIPBackend": ("yoyopod.backends.voip.protocol", "VoIPBackend"),
    "VoIPIterateMetrics": ("yoyopod.backends.voip.protocol", "VoIPIterateMetrics"),
}


def __getattr__(name: str) -> Any:
    """Load VoIP backend exports lazily to keep low-level modules acyclic."""

    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = __import__(module_name, fromlist=[attribute])
    return getattr(module, attribute)


__all__ = [
    "LiblinphoneBackend",
    "LiblinphoneBinding",
    "LiblinphoneBindingError",
    "LiblinphoneNativeEvent",
    "MockVoIPBackend",
    "VoIPBackend",
    "VoIPIterateMetrics",
]
