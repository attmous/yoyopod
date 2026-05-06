"""CLI-owned main-thread task scheduler used by Pi validation helpers."""

from __future__ import annotations

import threading
from queue import Empty, Queue
from typing import Any, Callable, Protocol

from loguru import logger


class _DiagnosticsLog(Protocol):
    def append(self, entry: Any) -> None:
        """Append one diagnostics entry."""


class MainThreadScheduler:
    """Queue work onto the main thread without going through the event bus."""

    def __init__(self, main_thread_id: int | None = None) -> None:
        self.main_thread_id = main_thread_id or threading.get_ident()
        self._queue: Queue[Callable[[], None]] = Queue()
        self._diagnostics_log: _DiagnosticsLog | None = None

    def set_diagnostics_log(self, diagnostics_log: _DiagnosticsLog | None) -> None:
        """Attach or clear the diagnostics sink used for task failures."""

        self._diagnostics_log = diagnostics_log

    def run_on_main(self, fn: Callable[[], None]) -> None:
        """Run on the main thread now, or queue for the next drain when off-thread."""

        if threading.get_ident() == self.main_thread_id:
            fn()
            return
        self.post(fn)

    def post(self, fn: Callable[[], None]) -> None:
        """Queue one callback for the main thread to run on a later drain."""

        self._queue.put(fn)

    def drain(self, limit: int | None = None) -> int:
        """Run queued callbacks in FIFO order."""

        processed = 0
        while limit is None or processed < limit:
            try:
                fn = self._queue.get_nowait()
            except Empty:
                break
            try:
                fn()
            except Exception as exc:
                if self._diagnostics_log is not None:
                    self._diagnostics_log.append(
                        {
                            "kind": "error",
                            "handler": _callable_name(fn),
                            "exc": f"{exc.__class__.__name__}: {exc}",
                        }
                    )
                logger.exception("Error running scheduled main-thread task")
            processed += 1
        return processed

    def pending_count(self) -> int:
        """Return the number of queued callbacks."""

        return self._queue.qsize()


def _callable_name(fn: Callable[[], None]) -> str:
    module = getattr(fn, "__module__", "") or ""
    qualname = getattr(fn, "__qualname__", getattr(fn, "__name__", repr(fn)))
    return f"{module}.{qualname}".strip(".")
