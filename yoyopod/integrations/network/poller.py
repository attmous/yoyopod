"""Background poller for scaffold modem registration and signal state."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

from yoyopod.integrations.network.handlers import (
    apply_modem_status_to_state,
    apply_signal_to_state,
)


class NetworkPoller:
    """Poll the modem backend and marshal state updates back to the main thread."""

    def __init__(
        self,
        *,
        app: Any,
        backend: Any,
        poll_interval_seconds: float = 15.0,
        monotonic: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self.app = app
        self.backend = backend
        self.poll_interval_seconds = max(0.1, float(poll_interval_seconds))
        self._monotonic = monotonic or time.monotonic
        self._sleep = sleep or time.sleep
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def poll_once(self) -> tuple[object, object | None]:
        """Collect one modem status and signal sample and schedule the state write."""

        status = self.backend.get_status()
        signal = self.backend.get_signal()
        self.app.scheduler.post(lambda status=status, signal=signal: self._apply(status, signal))
        return status, signal

    def start(self) -> None:
        """Start the background modem poll loop."""

        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="network-poller")
        self._thread.start()

    def stop(self) -> None:
        """Stop the background modem poll loop."""

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

    def _apply(self, status: object, signal: object | None) -> None:
        apply_modem_status_to_state(self.app, status)
        apply_signal_to_state(
            self.app,
            csq=None if signal is None else getattr(signal, "csq", None),
            bars=None if signal is None else getattr(signal, "bars", None),
        )
