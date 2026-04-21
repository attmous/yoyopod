"""Main-thread-only event bus for the Phase A spine scaffold."""

from __future__ import annotations

import threading
from collections import defaultdict, deque
from typing import Any, Callable, DefaultDict, Protocol

from loguru import logger

EventHandler = Callable[[Any], None]


class _DiagnosticsLog(Protocol):
    def append(self, entry: Any) -> None:
        """Append one diagnostics entry."""


class Bus:
    """Typed event bus that only accepts publishes from the main thread."""

    def __init__(self, main_thread_id: int | None = None, strict: bool = False) -> None:
        self.main_thread_id = main_thread_id or threading.get_ident()
        self._strict = strict
        self._subscribers: DefaultDict[type[Any], list[EventHandler]] = defaultdict(list)
        self._queue: deque[Any] = deque()
        self._diagnostics_log: _DiagnosticsLog | None = None

    def set_diagnostics_log(self, diagnostics_log: _DiagnosticsLog | None) -> None:
        """Attach or clear the diagnostics sink used for handler failures."""

        self._diagnostics_log = diagnostics_log

    def subscribe(self, event_type: type[Any], handler: EventHandler) -> None:
        """Register a handler for one event type."""

        self._subscribers[event_type].append(handler)
        logger.trace("Subscribed scaffold bus handler for {}", event_type.__name__)

    def publish(self, event: Any) -> None:
        """Queue one event for later main-thread dispatch."""

        if threading.get_ident() != self.main_thread_id:
            raise RuntimeError("Bus.publish() must be called on the main thread")
        self._queue.append(event)

    def drain(self, limit: int | None = None) -> int:
        """Dispatch queued events in FIFO order."""

        processed = 0
        while self._queue and (limit is None or processed < limit):
            event = self._queue.popleft()
            self._dispatch(event)
            processed += 1
        return processed

    def pending_count(self) -> int:
        """Return the number of queued events."""

        return len(self._queue)

    def subscription_counts(self) -> dict[str, int]:
        """Return subscriber counts keyed by event type name."""

        return {
            event_type.__name__: len(subscribers)
            for event_type, subscribers in sorted(
                self._subscribers.items(),
                key=lambda item: item[0].__name__,
            )
        }

    def _dispatch(self, event: Any) -> None:
        handlers: list[EventHandler] = []
        for event_type, subscribers in self._subscribers.items():
            if isinstance(event, event_type):
                handlers.extend(subscribers)

        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:
                if self._diagnostics_log is not None:
                    self._diagnostics_log.append(
                        {
                            "kind": "error",
                            "handler": _handler_name(handler),
                            "exc": f"{exc.__class__.__name__}: {exc}",
                        }
                    )
                if self._strict:
                    raise
                logger.exception("Error handling scaffold event {}", event.__class__.__name__)


def _handler_name(handler: EventHandler) -> str:
    module = getattr(handler, "__module__", "") or ""
    qualname = getattr(handler, "__qualname__", getattr(handler, "__name__", repr(handler)))
    return f"{module}.{qualname}".strip(".")
