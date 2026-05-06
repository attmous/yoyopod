"""Canonical VoIP backend adapters."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod_cli.pi.support.voip_backend.mock_backend import MockVoIPBackend
    from yoyopod_cli.pi.support.voip_backend.protocol import VoIPBackend, VoIPIterateMetrics
    from yoyopod_cli.pi.support.voip_backend.rust_host import RustHostBackend


_EXPORTS = {
    "MockVoIPBackend": ("yoyopod_cli.pi.support.voip_backend.mock_backend", "MockVoIPBackend"),
    "RustHostBackend": ("yoyopod_cli.pi.support.voip_backend.rust_host", "RustHostBackend"),
    "VoIPBackend": ("yoyopod_cli.pi.support.voip_backend.protocol", "VoIPBackend"),
    "VoIPIterateMetrics": ("yoyopod_cli.pi.support.voip_backend.protocol", "VoIPIterateMetrics"),
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
    "MockVoIPBackend",
    "RustHostBackend",
    "VoIPBackend",
    "VoIPIterateMetrics",
]
