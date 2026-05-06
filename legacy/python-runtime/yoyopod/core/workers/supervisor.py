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
from yoyopod_cli.contracts.worker_protocol import WorkerEnvelope


@dataclass(slots=True)
class _WorkerSlot:
    config: WorkerProcessConfig
    runtime: WorkerProcessRuntime | None = None
    state: str = "stopped"
    restart_count: int = 0
    next_restart_at: float = 0.0
    request_types: dict[str, str] = field(default_factory=dict)
    request_deadlines: dict[str, float] = field(default_factory=dict)
    request_attempts: dict[str, int] = field(default_factory=dict)
    stale_request_ids: dict[str, float] = field(default_factory=dict)
    request_timeouts: int = 0
    last_reason: str = ""


class WorkerSupervisor:
    """Own worker lifecycle from the main-thread runtime loop.

    The scheduler is retained for the Task 7 app/loop integration seam; this
    phase publishes directly because the supervisor itself is main-thread owned.
    """

    _STALE_REQUEST_RETENTION_SECONDS = 30.0
    _DEFAULT_MAX_MESSAGES_PER_POLL = 8
    _REQUEST_ATTEMPT_PAYLOAD_KEY = "_yoyopod_request_attempt"

    def __init__(
        self,
        *,
        scheduler: MainThreadScheduler,
        bus: Bus,
        restart_backoff_seconds: float = 1.0,
        max_restarts: int = 3,
        max_messages_per_poll: int = _DEFAULT_MAX_MESSAGES_PER_POLL,
    ) -> None:
        self._scheduler = scheduler
        self._bus = bus
        self._restart_backoff_seconds = max(0.0, restart_backoff_seconds)
        self._max_restarts = max(0, max_restarts)
        self._max_messages_per_poll = max(1, int(max_messages_per_poll))
        self._workers: dict[str, _WorkerSlot] = {}
        self._poll_start_index = 0

    def register(self, domain: str, config: WorkerProcessConfig) -> None:
        """Register one worker domain before it is started."""

        if domain in self._workers:
            raise ValueError(f"worker domain {domain!r} is already registered")
        self._workers[domain] = _WorkerSlot(config=config)

    def start(self, domain: str) -> bool:
        """Start one worker domain."""

        slot = self._workers[domain]
        if slot.runtime is not None and slot.runtime.running:
            raise RuntimeError(f"worker domain {domain!r} is already running")
        return self._start_runtime(
            domain,
            slot,
            state_reason="started",
            failure_reason="start_failed",
        )

    def stop(self, domain: str, *, grace_seconds: float = 1.0) -> None:
        """Stop one registered worker domain with a bounded wait."""

        slot = self._workers[domain]
        if slot.runtime is not None:
            slot.runtime.stop(grace_seconds=grace_seconds)
        slot.request_types.clear()
        slot.request_deadlines.clear()
        slot.request_attempts.clear()
        slot.stale_request_ids.clear()
        slot.next_restart_at = 0.0
        self._set_state(domain, slot, "stopped", "stop")

    def _start_runtime(
        self,
        domain: str,
        slot: _WorkerSlot,
        *,
        state_reason: str,
        failure_reason: str,
    ) -> bool:
        runtime = WorkerProcessRuntime(slot.config)
        try:
            runtime.start()
        except Exception:
            if failure_reason == "start_failed" and self._max_restarts > 0:
                slot.next_restart_at = time.monotonic() + self._restart_backoff_seconds
            else:
                slot.next_restart_at = 0.0
            slot.request_types.clear()
            slot.request_attempts.clear()
            slot.stale_request_ids.clear()
            self._set_state(domain, slot, "degraded", failure_reason)
            return False
        slot.runtime = runtime
        slot.next_restart_at = 0.0
        slot.request_types.clear()
        slot.request_attempts.clear()
        slot.stale_request_ids.clear()
        self._set_state(domain, slot, "running", state_reason)
        return True

    def stop_all(self, *, grace_seconds: float = 1.0) -> None:
        """Stop all registered workers with bounded waits."""

        for domain, slot in self._workers.items():
            if slot.runtime is not None:
                slot.runtime.stop(grace_seconds=grace_seconds)
            slot.request_types.clear()
            slot.request_deadlines.clear()
            slot.request_attempts.clear()
            slot.stale_request_ids.clear()
            slot.next_restart_at = 0.0
            self._set_state(domain, slot, "stopped", "stop_all")

    def poll(self, *, monotonic_now: float | None = None) -> int:
        """Advance worker state without blocking."""

        now = time.monotonic() if monotonic_now is None else monotonic_now
        processed = 0
        worker_items = list(self._workers.items())
        if not worker_items:
            return 0

        for domain, slot in worker_items:
            runtime = slot.runtime
            if runtime is None:
                continue
            self._expire_requests(domain, slot, now=now)

        remaining_message_budget = self._max_messages_per_poll
        ordered_worker_items = self._rotate_worker_items(worker_items)
        candidate_worker_items = [
            (domain, slot) for domain, slot in ordered_worker_items if slot.runtime is not None
        ]
        while remaining_message_budget > 0 and candidate_worker_items:
            next_candidate_worker_items: list[tuple[str, _WorkerSlot]] = []
            drained_in_round = False
            remaining_runtime_count = len(candidate_worker_items)
            for index, (domain, slot) in enumerate(candidate_worker_items):
                runtime = slot.runtime
                if runtime is None or remaining_message_budget <= 0:
                    continue
                share = max(1, remaining_message_budget // (remaining_runtime_count - index))
                messages = runtime.drain_messages(limit=share)
                if not messages:
                    continue
                drained_in_round = True
                processed += len(messages)
                remaining_message_budget -= len(messages)
                for message in messages:
                    self._publish_message(domain, slot, message)
                if len(messages) == share and remaining_message_budget > 0:
                    next_candidate_worker_items.append((domain, slot))
            if not drained_in_round:
                break
            candidate_worker_items = next_candidate_worker_items

        self._poll_start_index = (self._poll_start_index + 1) % len(worker_items)

        for domain, slot in worker_items:
            runtime = slot.runtime
            if runtime is not None and not runtime.running and slot.state == "running":
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
        now = time.monotonic()
        existing_deadline = slot.request_deadlines.get(request_id)
        if existing_deadline is not None and existing_deadline <= now:
            self._expire_request(domain, slot, request_id, now=now)
        request_attempt = slot.request_attempts.get(request_id, 0) + 1
        command_payload = dict(payload)
        command_payload[self._REQUEST_ATTEMPT_PAYLOAD_KEY] = request_attempt
        sent = runtime.send_command(
            type=type,
            payload=command_payload,
            request_id=request_id,
            timestamp_ms=int(time.time() * 1000),
            deadline_ms=int(timeout_seconds * 1000),
        )
        if sent:
            slot.request_types[request_id] = type
            slot.request_attempts[request_id] = request_attempt
            slot.stale_request_ids.pop(request_id, None)
            slot.request_deadlines[request_id] = now + timeout_seconds
        return sent

    def send_command(
        self,
        domain: str,
        *,
        type: str,
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        timestamp_ms: int = 0,
        deadline_ms: int = 0,
    ) -> bool:
        """Send one untracked command without creating request-timeout state."""

        slot = self._workers[domain]
        runtime = slot.runtime
        if runtime is None:
            return False
        return runtime.send_command(
            type=type,
            payload=payload or {},
            request_id=request_id,
            timestamp_ms=timestamp_ms,
            deadline_ms=deadline_ms,
        )

    def drain_worker_messages(self, domain: str) -> list[WorkerEnvelope]:
        """Return messages that have not yet been consumed by poll."""

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
                "sent_messages": (
                    process_snapshot.sent_messages if process_snapshot is not None else 0
                ),
                "queued_sends": (
                    process_snapshot.queued_sends if process_snapshot is not None else 0
                ),
                "dropped_sends": (
                    process_snapshot.dropped_sends if process_snapshot is not None else 0
                ),
                "send_failures": (
                    process_snapshot.send_failures if process_snapshot is not None else 0
                ),
            }
        return result

    def _publish_message(
        self,
        domain: str,
        slot: _WorkerSlot,
        message: WorkerEnvelope,
    ) -> None:
        if not self._matches_active_request_attempt(slot, message):
            return
        if self._should_drop_active_cancel_ack(domain, slot, message):
            return
        if message.request_id is not None and message.request_id in slot.stale_request_ids:
            if not self._is_timeout_cancel_ack(domain, message):
                return
        if message.request_id is not None and self._is_terminal_request_reply(domain, message):
            slot.request_types.pop(message.request_id, None)
            slot.request_deadlines.pop(message.request_id, None)
            slot.request_attempts.pop(message.request_id, None)
        self._bus.publish(
            WorkerMessageReceivedEvent(
                domain=domain,
                kind=message.kind,
                type=message.type,
                request_id=message.request_id,
                payload=self._public_payload(message),
            )
        )

    def _expire_requests(self, domain: str, slot: _WorkerSlot, *, now: float) -> None:
        self._prune_stale_request_ids(slot, now=now)
        expired = [
            request_id for request_id, deadline in slot.request_deadlines.items() if deadline <= now
        ]
        for request_id in expired:
            self._expire_request(domain, slot, request_id, now=now)

    def _expire_request(
        self,
        domain: str,
        slot: _WorkerSlot,
        request_id: str,
        *,
        now: float,
    ) -> None:
        slot.request_deadlines.pop(request_id, None)
        slot.request_timeouts += 1
        slot.stale_request_ids[request_id] = now + self._STALE_REQUEST_RETENTION_SECONDS
        if slot.runtime is not None:
            slot.runtime.send_command(
                type=f"{domain}.cancel",
                payload={"request_id": request_id},
                request_id=request_id,
                timestamp_ms=int(time.time() * 1000),
                deadline_ms=1000,
            )

    def _handle_exit(self, domain: str, slot: _WorkerSlot, *, now: float) -> None:
        slot.request_types.clear()
        slot.request_deadlines.clear()
        slot.request_attempts.clear()
        slot.stale_request_ids.clear()
        slot.next_restart_at = now + self._restart_backoff_seconds
        self._set_state(domain, slot, "degraded", "process_exited")

    def _prune_stale_request_ids(self, slot: _WorkerSlot, *, now: float) -> None:
        expired_stale_ids = [
            request_id
            for request_id, stale_until in slot.stale_request_ids.items()
            if stale_until <= now
        ]
        for request_id in expired_stale_ids:
            slot.stale_request_ids.pop(request_id, None)
            if request_id not in slot.request_deadlines:
                slot.request_types.pop(request_id, None)
                slot.request_attempts.pop(request_id, None)

    def _is_timeout_cancel_ack(self, domain: str, message: WorkerEnvelope) -> bool:
        return message.type == f"{domain}.cancelled"

    def _is_terminal_request_reply(self, domain: str, message: WorkerEnvelope) -> bool:
        if self._is_timeout_cancel_ack(domain, message):
            return True
        return message.kind in {"result", "error"}

    def _should_drop_active_cancel_ack(
        self,
        domain: str,
        slot: _WorkerSlot,
        message: WorkerEnvelope,
    ) -> bool:
        request_id = message.request_id
        if request_id is None or not self._is_timeout_cancel_ack(domain, message):
            return False
        if request_id not in slot.request_deadlines or request_id in slot.stale_request_ids:
            return False
        return slot.request_types.get(request_id) != f"{domain}.cancel"

    def _rotate_worker_items(
        self, worker_items: list[tuple[str, _WorkerSlot]]
    ) -> list[tuple[str, _WorkerSlot]]:
        if not worker_items:
            return []
        start_index = self._poll_start_index % len(worker_items)
        return worker_items[start_index:] + worker_items[:start_index]

    def _matches_active_request_attempt(
        self,
        slot: _WorkerSlot,
        message: WorkerEnvelope,
    ) -> bool:
        request_id = message.request_id
        if request_id is None:
            return True
        active_attempt = slot.request_attempts.get(request_id)
        if active_attempt is None:
            return True
        message_attempt = message.payload.get(self._REQUEST_ATTEMPT_PAYLOAD_KEY)
        if message_attempt is None:
            return True
        return message_attempt == active_attempt

    def _public_payload(self, message: WorkerEnvelope) -> dict[str, Any]:
        payload = dict(message.payload)
        payload.pop(self._REQUEST_ATTEMPT_PAYLOAD_KEY, None)
        return payload

    def _restart_if_allowed(self, domain: str, slot: _WorkerSlot, *, now: float) -> None:
        if slot.restart_count >= self._max_restarts:
            slot.next_restart_at = 0.0
            self._set_state(domain, slot, "disabled", "max_restarts_exceeded")
            return
        slot.restart_count += 1
        started = self._start_runtime(
            domain,
            slot,
            state_reason="started",
            failure_reason="restart_failed",
        )
        if not started:
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
