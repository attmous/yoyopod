"""Rust-backed network integration exports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.integrations.network.rust_host import RustNetworkFacade


_PUBLIC_EXPORTS = {
    "RustNetworkFacade": ("yoyopod.integrations.network.rust_host", "RustNetworkFacade"),
}


def __getattr__(name: str) -> Any:
    """Load the supported Rust-backed network facade lazily."""

    try:
        module_name, attribute = _PUBLIC_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = __import__(module_name, fromlist=[attribute])
    return getattr(module, attribute)


__all__ = ["RustNetworkFacade"]
