"""
Thread-safe typed event bus for YoyoPod orchestration.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from queue import Empty, Queue
from typing import Any, Callable, DefaultDict

from loguru import logger


EventHandler = Callable[[Any], None]


class EventBus:
    """
    Dispatch typed events on the coordinator thread.

    Background threads enqueue events, while the main loop drains and dispatches
    them to subscribed handlers in publish order.
    """

    def __init__(self, main_thread_id: int | None = None, strict: bool = False) -> None:
        self.main_thread_id = main_thread_id or threading.get_ident()
        self._strict = strict
        self._subscribers: DefaultDict[type[Any], list[EventHandler]] = defaultdict(list)
        self._queue: Queue[Any] = Queue()

    def subscribe(self, event_type: type[Any], handler: EventHandler) -> None:
        """Register a handler for a specific event type."""
        self._subscribers[event_type].append(handler)
        logger.trace("Subscribed handler for {}", event_type.__name__)

    def publish(self, event: Any) -> None:
        """Publish an event, queueing it if called off the main thread."""
        if threading.get_ident() == self.main_thread_id:
            self._dispatch(event)
            return

        self._queue.put(event)
        logger.trace("Queued event: {}", event.__class__.__name__)

    def drain(self, limit: int | None = None) -> int:
        """
        Drain queued events on the main thread.

        Args:
            limit: Optional maximum number of events to process.

        Returns:
            Number of drained events.
        """
        processed = 0

        while limit is None or processed < limit:
            try:
                event = self._queue.get_nowait()
            except Empty:
                break

            self._dispatch(event)
            processed += 1

        return processed

    def pending_count(self) -> int:
        """Return the number of queued events waiting for the coordinator thread."""
        return self._queue.qsize()

    def _dispatch(self, event: Any) -> None:
        """Dispatch an event to all compatible subscribers."""
        handlers: list[EventHandler] = []
        for event_type, subscribers in self._subscribers.items():
            if isinstance(event, event_type):
                handlers.extend(subscribers)

        for handler in handlers:
            try:
                handler(event)
            except Exception as exc:
                if self._strict:
                    raise
                logger.error(f"Error handling {event.__class__.__name__}: {exc}")
