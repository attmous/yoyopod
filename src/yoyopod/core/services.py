"""Typed service registry for the Phase A spine scaffold."""

from __future__ import annotations

import threading
from typing import Any, Callable, Protocol

from yoyopod.core.bus import Bus

Handler = Callable[[Any], Any]


class _LogSink(Protocol):
    def append(self, entry: Any) -> None:
        """Append one diagnostics entry."""


class Services:
    """Synchronous main-thread command registry."""

    def __init__(self, bus: Bus, diagnostics_log: _LogSink | None = None) -> None:
        self._main_thread_id = bus.main_thread_id
        self._diagnostics_log = diagnostics_log
        self._handlers: dict[tuple[str, str], Handler] = {}

    def register(self, domain: str, service: str, handler: Handler) -> None:
        """Register one service handler."""

        key = (domain, service)
        if key in self._handlers:
            raise ValueError(f"Service already registered: {domain}.{service}")
        self._handlers[key] = handler

    def set_diagnostics_log(self, diagnostics_log: _LogSink | None) -> None:
        """Attach or clear the diagnostics sink used for command entries."""

        self._diagnostics_log = diagnostics_log

    def call(self, domain: str, service: str, data: Any = None) -> Any:
        """Invoke one registered service on the main thread."""

        if threading.get_ident() != self._main_thread_id:
            raise RuntimeError("Services.call() must run on the main thread")

        key = (domain, service)
        if key not in self._handlers:
            raise KeyError(f"Unknown service: {domain}.{service}")

        self._record({"kind": "command", "domain": domain, "service": service, "data": data})
        try:
            return self._handlers[key](data)
        except Exception as exc:
            self._record(
                {
                    "kind": "error",
                    "handler": f"{domain}.{service}",
                    "exc": f"{exc.__class__.__name__}: {exc}",
                }
            )
            raise

    def registered(self) -> list[tuple[str, str]]:
        """Return all registered service names."""

        return sorted(self._handlers)

    def _record(self, entry: dict[str, Any]) -> None:
        if self._diagnostics_log is not None:
            self._diagnostics_log.append(entry)
