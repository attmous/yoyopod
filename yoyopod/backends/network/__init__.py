"""Canonical cellular backend adapters for the modem stack."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yoyopod.backends.network.at_commands import AtCommandSet
    from yoyopod.backends.network.modem import (
        ModemBackend,
        ModemStatus,
        NetworkBackend,
        Sim7600Backend,
    )
    from yoyopod.backends.network.ppp import PPPBackend, PppProcess
    from yoyopod.backends.network.transport import SerialTransport, TransportError


_EXPORTS = {
    "AtCommandSet": ("yoyopod.backends.network.at_commands", "AtCommandSet"),
    "ModemBackend": ("yoyopod.backends.network.modem", "ModemBackend"),
    "ModemStatus": ("yoyopod.backends.network.modem", "ModemStatus"),
    "NetworkBackend": ("yoyopod.backends.network.modem", "NetworkBackend"),
    "PPPBackend": ("yoyopod.backends.network.ppp", "PPPBackend"),
    "PppProcess": ("yoyopod.backends.network.ppp", "PppProcess"),
    "SerialTransport": ("yoyopod.backends.network.transport", "SerialTransport"),
    "Sim7600Backend": ("yoyopod.backends.network.modem", "Sim7600Backend"),
    "TransportError": ("yoyopod.backends.network.transport", "TransportError"),
}


def __getattr__(name: str) -> Any:
    """Load backend exports lazily so low-level modules can import each other safely."""

    try:
        module_name, attribute = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc

    module = __import__(module_name, fromlist=[attribute])
    return getattr(module, attribute)

__all__ = [
    "AtCommandSet",
    "ModemBackend",
    "ModemStatus",
    "NetworkBackend",
    "PPPBackend",
    "PppProcess",
    "SerialTransport",
    "Sim7600Backend",
    "TransportError",
]
