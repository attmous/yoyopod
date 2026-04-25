"""Supervisor for named YoYoPod worker processes."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from yoyopod.core.bus import Bus
from yoyopod.core.events import (
    WorkerDomainStateChangedEvent,
    WorkerMessageReceivedEvent,
)
from yoyopod.core.scheduler import MainThreadScheduler
from yoyopod.core.workers.process import WorkerProcessConfig, WorkerProcessRuntime
from yoyopod.core.workers.protocol import WorkerEnvelope


@dataclass(slots=True)
class _WorkerSlot:
    config: WorkerProcessConfig
    runtime: WorkerProcessRuntime | None = None
    state: str = "stopped"
    restart_count: int = 0
    next_restart_at: float = 0.0
    request_deadlines: dict[str, float] = field(default_factory=dict)
    request_timeouts: int = 0
    last_reason: str = ""


class WorkerSupervisor:
    """Own worker lifecycle from the main-thread runtime loop.

    The scheduler is retained for the Task 7 app/loop integration seam; this
    phase publishes directly because the supervisor itself is main-thread owned.
    """

    def __init__(
        self,
        *,
        scheduler: MainThreadScheduler,
        bus: Bus,
        restart_backoff_seconds: float = 1.0,
        max_restarts: int = 3,
    ) -> None:
        self._scheduler = scheduler
        self._bus = bus
        self._restart_backoff_seconds = max(0.0, restart_backoff_seconds)
        self._max_restarts = max(0, max_restarts)
        self._workers: dict[str, _WorkerSlot] = {}

    def register(self, domain: str, config: WorkerProcessConfig) -> None:
        """Register one worker domain before it is started."""

        if domain in self._workers:
            raise ValueError(f"worker domain {domain!r} is already registered")
        self._workers[domain] = _WorkerSlot(config=config)

    def start(self, domain: str) -> None:
        """Start one worker domain."""

        slot = self._workers[domain]
        if slot.runtime is not None and slot.runtime.running:
            raise RuntimeError(f"worker domain {domain!r} is already running")
        self._start_runtime(
            domain,
            slot,
            state_reason="started",
            failure_reason="start_failed",
        )

    def _start_runtime(
        self,
        domain: str,
        slot: _WorkerSlot,
        *,
        state_reason: str,
        failure_reason: str,
    ) -> None:
        runtime = WorkerProcessRuntime(slot.config)
        try:
            runtime.start()
        except Exception:
            slot.next_restart_at = 0.0
            self._set_state(domain, slot, "degraded", failure_reason)
            raise
        slot.runtime = runtime
        slot.next_restart_at = 0.0
        self._set_state(domain, slot, "running", state_reason)

    def stop_all(self, *, grace_seconds: float = 1.0) -> None:
        """Stop all registered workers with bounded waits."""

        for domain, slot in self._workers.items():
            if slot.runtime is not None:
                slot.runtime.stop(grace_seconds=grace_seconds)
            slot.request_deadlines.clear()
            slot.next_restart_at = 0.0
            self._set_state(domain, slot, "stopped", "stop_all")

    def poll(self, *, monotonic_now: float | None = None) -> int:
        """Advance worker state without blocking."""

        now = time.monotonic() if monotonic_now is None else monotonic_now
        processed = 0
        for domain, slot in self._workers.items():
            runtime = slot.runtime
            if runtime is None:
                continue
            messages = runtime.drain_messages()
            processed += len(messages)
            for message in messages:
                self._publish_message(domain, slot, message)
            self._expire_requests(domain, slot, now=now)
            if not runtime.running and slot.state == "running":
                self._handle_exit(domain, slot, now=now)
            if (
                slot.state == "degraded"
                and slot.next_restart_at > 0.0
                and now >= slot.next_restart_at
            ):
                self._restart_if_allowed(domain, slot, now=now)
        return processed

    def send_request(
        self,
        domain: str,
        *,
        type: str,
        payload: dict[str, Any],
        request_id: str,
        timeout_seconds: float,
    ) -> bool:
        """Send one request and remember its timeout."""

        slot = self._workers[domain]
        runtime = slot.runtime
        if runtime is None:
            return False
        timeout_seconds = max(0.0, timeout_seconds)
        sent = runtime.send_command(
            type=type,
            payload=payload,
            request_id=request_id,
            timestamp_ms=int(time.time() * 1000),
            deadline_ms=int(timeout_seconds * 1000),
        )
        if sent:
            slot.request_deadlines[request_id] = time.monotonic() + timeout_seconds
        return sent

    def drain_worker_messages(self, domain: str) -> list[WorkerEnvelope]:
        """Testing helper for messages that have not yet been consumed by poll."""

        runtime = self._workers[domain].runtime
        return [] if runtime is None else runtime.drain_messages()

    def wait_until_exited(self, domain: str, timeout_seconds: float) -> bool:
        """Testing helper that waits for one worker process to exit."""

        runtime = self._workers[domain].runtime
        return (
            True if runtime is None else runtime.wait_until_exited(timeout_seconds=timeout_seconds)
        )

    def snapshot(self) -> dict[str, dict[str, object]]:
        """Return status-ready worker health data."""

        result: dict[str, dict[str, object]] = {}
        for domain, slot in self._workers.items():
            process_snapshot = slot.runtime.snapshot() if slot.runtime is not None else None
            result[domain] = {
                "state": slot.state,
                "restart_count": slot.restart_count,
                "next_restart_at": slot.next_restart_at,
                "last_reason": slot.last_reason,
                "pending_requests": len(slot.request_deadlines),
                "request_timeouts": slot.request_timeouts,
                "running": process_snapshot.running if process_snapshot is not None else False,
                "pid": process_snapshot.pid if process_snapshot is not None else None,
                "received_messages": (
                    process_snapshot.received_messages if process_snapshot is not None else 0
                ),
                "protocol_errors": (
                    process_snapshot.protocol_errors if process_snapshot is not None else 0
                ),
                "dropped_messages": (
                    process_snapshot.dropped_messages if process_snapshot is not None else 0
                ),
            }
        return result

    def _publish_message(
        self,
        domain: str,
        slot: _WorkerSlot,
        message: WorkerEnvelope,
    ) -> None:
        if message.request_id is not None:
            slot.request_deadlines.pop(message.request_id, None)
        self._bus.publish(
            WorkerMessageReceivedEvent(
                domain=domain,
                kind=message.kind,
                type=message.type,
                request_id=message.request_id,
                payload=message.payload,
            )
        )

    def _expire_requests(self, domain: str, slot: _WorkerSlot, *, now: float) -> None:
        expired = [
            request_id for request_id, deadline in slot.request_deadlines.items() if deadline <= now
        ]
        for request_id in expired:
            slot.request_deadlines.pop(request_id, None)
            slot.request_timeouts += 1
            if slot.runtime is not None:
                slot.runtime.send_command(
                    type=f"{domain}.cancel",
                    payload={"request_id": request_id},
                    request_id=request_id,
                    timestamp_ms=int(time.time() * 1000),
                    deadline_ms=1000,
                )

    def _handle_exit(self, domain: str, slot: _WorkerSlot, *, now: float) -> None:
        slot.request_deadlines.clear()
        slot.next_restart_at = now + self._restart_backoff_seconds
        self._set_state(domain, slot, "degraded", "process_exited")

    def _restart_if_allowed(self, domain: str, slot: _WorkerSlot, *, now: float) -> None:
        if slot.restart_count >= self._max_restarts:
            slot.next_restart_at = 0.0
            self._set_state(domain, slot, "disabled", "max_restarts_exceeded")
            return
        slot.restart_count += 1
        try:
            self._start_runtime(
                domain,
                slot,
                state_reason="started",
                failure_reason="restart_failed",
            )
        except Exception:
            if slot.restart_count >= self._max_restarts:
                slot.next_restart_at = 0.0
            else:
                slot.next_restart_at = now + self._restart_backoff_seconds

    def _set_state(self, domain: str, slot: _WorkerSlot, state: str, reason: str) -> None:
        if slot.state == state and slot.last_reason == reason:
            return
        slot.state = state
        slot.last_reason = reason
        self._bus.publish(WorkerDomainStateChangedEvent(domain=domain, state=state, reason=reason))
