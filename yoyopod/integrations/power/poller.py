"""Polling helpers for the scaffold power integration."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from yoyopod.integrations.power.models import PowerSnapshot


class PowerPoller:
    """Poll the power backend and marshal snapshots back to the main thread."""

    def __init__(
        self,
        *,
        backend: object,
        scheduler: object,
        on_snapshot: Callable[[PowerSnapshot], None],
        poll_interval_seconds: float = 30.0,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.backend = backend
        self.scheduler = scheduler
        self.on_snapshot = on_snapshot
        self.poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def poll_once(self) -> PowerSnapshot:
        """Collect one snapshot and schedule its main-thread handler."""

        snapshot = self.backend.get_snapshot()
        self.scheduler.post(lambda snapshot=snapshot: self.on_snapshot(snapshot))
        return snapshot

    def start(self) -> None:
        """Start the background poll loop if it is not already running."""

        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="power-poller")
        self._thread.start()

    def stop(self) -> None:
        """Stop the background poll loop."""

        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=self.poll_interval_seconds + 0.5)
            self._thread = None

    def _run(self) -> None:
        next_poll_at = 0.0
        while not self._stop_event.is_set():
            now = self._monotonic()
            if now >= next_poll_at:
                self.poll_once()
                next_poll_at = now + self.poll_interval_seconds
            self._sleep(min(0.1, self.poll_interval_seconds))
