"""Minimal app shell for the Phase A spine scaffold."""

from __future__ import annotations

import time
import threading
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from yoyopod.core.bus import Bus
from yoyopod.core.events import LifecycleEvent
from yoyopod.core.logbuffer import LogBuffer
from yoyopod.core.scheduler import MainThreadScheduler
from yoyopod.core.services import Services
from yoyopod.core.states import States


@dataclass(slots=True)
class _RegisteredIntegration:
    """One integration registration owned by the scaffold shell."""

    name: str
    setup: Callable[["YoyoPodAppShell"], None]
    teardown: Callable[["YoyoPodAppShell"], None] | None = None


class YoyoPodAppShell:
    """Bundle the scaffold primitives without touching the legacy runtime."""

    def __init__(self, strict_bus: bool = False, log_buffer_size: int = 256) -> None:
        self.main_thread_id = threading.get_ident()
        self.bus = Bus(main_thread_id=self.main_thread_id, strict=strict_bus)
        self.scheduler = MainThreadScheduler(main_thread_id=self.main_thread_id)
        self.log_buffer: LogBuffer[dict[str, object]] = LogBuffer(maxlen=log_buffer_size)
        self.states = States(self.bus)
        self.services = Services(self.bus, diagnostics_log=self.log_buffer)
        self.config: object | None = None
        self.integrations: dict[str, object] = {}
        self.running = False
        self._setup_complete = False
        self._stopped = False
        self._registered_integrations: list[_RegisteredIntegration] = []
        self._tick_durations_ms: deque[float] = deque(maxlen=100)
        self._tick_queue_depths: deque[int] = deque(maxlen=100)
        self._ui_tick_callback: Callable[[], None] | None = None

    def set_ui_tick_callback(self, callback: Callable[[], None] | None) -> None:
        """Replace the optional UI tick callback."""

        self._ui_tick_callback = callback

    def register_integration(
        self,
        name: str,
        *,
        setup: Callable[["YoyoPodAppShell"], None],
        teardown: Callable[["YoyoPodAppShell"], None] | None = None,
    ) -> None:
        """Register one integration for explicit scaffold setup/teardown."""

        if self._setup_complete:
            raise RuntimeError(f"Cannot register integration {name!r} after setup()")
        self._registered_integrations.append(
            _RegisteredIntegration(name=name, setup=setup, teardown=teardown)
        )

    def setup(self) -> None:
        """Set up registered integrations in registration order once."""

        if self._setup_complete:
            return
        for integration in self._registered_integrations:
            self.bus.publish(LifecycleEvent(phase="setup_start", detail=integration.name))
            integration.setup(self)
            self.bus.publish(LifecycleEvent(phase="setup_complete", detail=integration.name))
        self._setup_complete = True

    def start(self) -> None:
        """Mark the scaffold shell as running and queue lifecycle events."""

        self.running = True
        self.bus.publish(LifecycleEvent(phase="starting"))
        self.bus.publish(LifecycleEvent(phase="ready"))

    def stop(self) -> None:
        """Queue stop lifecycle events and mark the shell as stopped."""

        if self._stopped:
            return
        self.bus.publish(LifecycleEvent(phase="stopping"))
        for integration in reversed(self._registered_integrations):
            if integration.teardown is None:
                continue
            self.bus.publish(LifecycleEvent(phase="teardown_start", detail=integration.name))
            integration.teardown(self)
            self.bus.publish(LifecycleEvent(phase="teardown_complete", detail=integration.name))
        self.running = False
        self._stopped = True
        self.bus.publish(LifecycleEvent(phase="stopped"))

    def tick(self) -> int:
        """Advance queued main-thread work once."""

        started_at = time.perf_counter()
        queue_depth = self.scheduler.pending_count() + self.bus.pending_count()
        processed = self.scheduler.drain()
        processed += self.bus.drain()
        if self._ui_tick_callback is not None:
            self._ui_tick_callback()
        self._tick_durations_ms.append((time.perf_counter() - started_at) * 1000.0)
        self._tick_queue_depths.append(queue_depth)
        return processed

    def tick_stats_snapshot(self) -> dict[str, float | int]:
        """Return a compact summary of recent tick durations and queue depths."""

        durations = list(self._tick_durations_ms)
        queue_depths = list(self._tick_queue_depths)
        return {
            "sample_count": len(durations),
            "drain_ms_p50": _percentile(durations, 0.50),
            "drain_ms_p99": _percentile(durations, 0.99),
            "queue_depth_max": max(queue_depths, default=0),
        }

    def run(self, *, sleep_seconds: float = 0.01, max_iterations: int | None = None) -> int:
        """Run the scaffold main loop until stopped or iteration-limited."""

        iterations = 0
        total_processed = 0
        if not self.running:
            self.start()

        while self.running:
            total_processed += self.tick()
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
            time.sleep(sleep_seconds)

        return total_processed


def _percentile(values: list[float], ratio: float) -> float:
    """Return one percentile from a non-empty list of values."""

    if not values:
        return 0.0

    ordered = sorted(values)
    index = int(round((len(ordered) - 1) * ratio))
    return ordered[index]
