"""Small in-memory ring buffer used by the scaffold diagnostics path."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from typing import Generic, TypeVar

_T = TypeVar("_T")


class LogBuffer(Generic[_T]):
    """Keep only the most recent log-like entries."""

    def __init__(self, maxlen: int = 256) -> None:
        if maxlen <= 0:
            raise ValueError("LogBuffer maxlen must be positive")
        self.maxlen = maxlen
        self._entries: deque[_T] = deque(maxlen=maxlen)

    def append(self, entry: _T) -> None:
        """Append one entry."""

        self._entries.append(entry)

    def extend(self, entries: Iterable[_T]) -> None:
        """Append many entries."""

        for entry in entries:
            self._entries.append(entry)

    def snapshot(self) -> list[_T]:
        """Return all retained entries in order."""

        return list(self._entries)

    def tail(self, count: int) -> list[_T]:
        """Return the newest ``count`` entries."""

        if count <= 0:
            return []
        return list(self._entries)[-count:]
