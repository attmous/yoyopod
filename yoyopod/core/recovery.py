"""Cross-cutting backend recovery supervision for the frozen scaffold spine."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Callable

from loguru import logger

from yoyopod.core.events import BackendStoppedEvent

RetryHandler = Callable[[], bool]


@dataclass(slots=True)
class RecoveryState:
    """Track reconnect backoff for one recoverable subsystem."""

    next_attempt_at: float = 0.0
    delay_seconds: float = 1.0
    in_flight: bool = False

    def reset(self) -> None:
        """Reset backoff after a successful recovery."""

        self.next_attempt_at = 0.0
        self.delay_seconds = 1.0
        self.in_flight = False


@dataclass(frozen=True, slots=True)
class RequestRecoveryCommand:
    """Request a retry cycle for one recoverable domain."""

    domain: str


@dataclass(frozen=True, slots=True)
class RecoveryAttemptedEvent:
    """Published after one recovery attempt finishes."""

    domain: str
    success: bool
    reason: str = ""


@dataclass(slots=True)
class RecoveryRuntime:
    """Runtime handles owned by the scaffold recovery helpers."""

    supervisor: "RecoverySupervisor"


@dataclass(slots=True)
class _DomainState:
    """Mutable retry bookkeeping for one domain."""

    attempt_count: int = 0
    next_delay_seconds: float = 1.0
    scheduled: bool = False


class RecoverySupervisor:
    """Coordinate recovery retries for core-owned and integration-owned backends."""

    def __init__(
        self,
        app: Any,
        *,
        initial_delay_seconds: float = 1.0,
        max_delay_seconds: float = 30.0,
        retry_handlers: dict[str, RetryHandler] | None = None,
    ) -> None:
        self._app = app
        self._initial_delay_seconds = max(0.0, float(initial_delay_seconds))
        self._max_delay_seconds = max(self._initial_delay_seconds, float(max_delay_seconds))
        self._retry_handlers = dict(retry_handlers or {})
        self._domains: dict[str, _DomainState] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def stop(self) -> None:
        """Prevent further retries from being scheduled."""

        self._stop.set()

    def register_retry_handler(self, domain: str, handler: RetryHandler) -> None:
        """Register one recoverable domain."""

        self._retry_handlers[str(domain)] = handler

    def on_backend_stopped(self, event: BackendStoppedEvent) -> None:
        """Schedule recovery after a backend-stopped signal."""

        self.request_recovery(event.domain, reason=event.reason or "backend_stopped")

    def request_recovery(self, domain: str, *, reason: str = "manual") -> None:
        """Schedule one retry cycle for a recoverable domain."""

        domain_name = str(domain)
        if not domain_name or self._stop.is_set():
            return

        with self._lock:
            state = self._domains.setdefault(
                domain_name,
                _DomainState(next_delay_seconds=self._initial_delay_seconds),
            )
            if state.scheduled:
                return
            state.scheduled = True
            delay = state.next_delay_seconds

        worker = threading.Thread(
            target=self._sleep_then_attempt,
            args=(domain_name, reason, delay),
            daemon=True,
            name=f"recovery-{domain_name}",
        )
        worker.start()

    def _sleep_then_attempt(self, domain: str, reason: str, delay: float) -> None:
        if self._stop.wait(delay):
            return
        self._app.scheduler.run_on_main(lambda: self._attempt(domain, reason))

    def _attempt(self, domain: str, reason: str) -> None:
        if self._stop.is_set():
            return

        handler = self._retry_handlers.get(domain)
        with self._lock:
            state = self._domains.setdefault(
                domain,
                _DomainState(next_delay_seconds=self._initial_delay_seconds),
            )
            state.scheduled = False
            state.attempt_count += 1

        success = False
        if handler is not None:
            success = bool(handler())

        self._app.bus.publish(RecoveryAttemptedEvent(domain=domain, success=success, reason=reason))

        with self._lock:
            if success:
                state.attempt_count = 0
                state.next_delay_seconds = self._initial_delay_seconds
                return
            state.next_delay_seconds = min(
                max(self._initial_delay_seconds, state.next_delay_seconds * 2.0),
                self._max_delay_seconds,
            )

        self.request_recovery(domain, reason=f"retry_{state.attempt_count}")


def setup(
    app: Any,
    *,
    initial_delay_seconds: float = 1.0,
    max_delay_seconds: float = 30.0,
) -> RecoveryRuntime:
    """Register recovery services and the backend-stop subscriber."""

    supervisor = RecoverySupervisor(
        app,
        initial_delay_seconds=initial_delay_seconds,
        max_delay_seconds=max_delay_seconds,
    )
    runtime = RecoveryRuntime(supervisor=supervisor)
    app.recovery = runtime
    app.recovery_supervisor = supervisor
    app.bus.subscribe(BackendStoppedEvent, supervisor.on_backend_stopped)
    app.services.register(
        "recovery",
        "request_recovery",
        lambda data: _request_recovery(supervisor, data),
    )
    return runtime


def teardown(app: Any) -> None:
    """Stop recovery helpers and drop runtime attributes."""

    runtime = getattr(app, "recovery", None)
    if runtime is not None:
        runtime.supervisor.stop()
        delattr(app, "recovery")
    if hasattr(app, "recovery_supervisor"):
        delattr(app, "recovery_supervisor")


def _request_recovery(supervisor: RecoverySupervisor, data: RequestRecoveryCommand) -> None:
    if not isinstance(data, RequestRecoveryCommand):
        raise TypeError("recovery.request_recovery expects RequestRecoveryCommand")
    supervisor.request_recovery(data.domain, reason="manual")


__all__ = [
    "BackendStoppedEvent",
    "RecoveryAttemptedEvent",
    "RecoveryRuntime",
    "RecoveryState",
    "RecoverySupervisor",
    "RuntimeRecoveryService",
    "RequestRecoveryCommand",
    "setup",
    "teardown",
]


class RuntimeRecoveryService:
    """Supervise recoverable VoIP/music/network managers in the live app shell."""

    def __init__(self, app: Any) -> None:
        self.app = app

    def handle_recovery_attempt_completed(
        self,
        *,
        manager: str,
        recovered: bool,
        recovery_now: float,
    ) -> None:
        """Finalize one background recovery attempt on the coordinator thread."""

        if manager == "music":
            self.app._music_recovery.in_flight = False
            if self.app._stopping:
                return

            if recovered and self.app.music_backend:
                if hasattr(self.app.music_backend, "polling") and not getattr(
                    self.app.music_backend,
                    "polling",
                ):
                    start_polling = getattr(self.app.music_backend, "start_polling", None)
                    if start_polling is not None:
                        start_polling()

            self.finalize_recovery_attempt(
                "Music",
                self.app._music_recovery,
                recovered,
                recovery_now,
            )
            return

        if manager != "network":
            return

        self.app._network_recovery.in_flight = False
        if self.app._stopping:
            return

        if self.app.network_manager is not None:
            self.app.network_events.sync_network_context_from_manager()
            if self.app.cloud_manager is not None:
                self.app.cloud_manager.note_network_change(
                    connected=self.app.network_manager.is_online
                )

        self.finalize_recovery_attempt(
            "Network",
            self.app._network_recovery,
            recovered,
            recovery_now,
        )

    def attempt_manager_recovery(self, now: float | None = None) -> None:
        """Try to recover VoIP and music when they become unavailable."""
        if self.app._stopping:
            return

        recovery_now = time.monotonic() if now is None else now
        self.attempt_voip_recovery(recovery_now)
        self.attempt_music_recovery(recovery_now)
        self.attempt_network_recovery(recovery_now)

    def attempt_voip_recovery(self, recovery_now: float) -> None:
        """Restart the VoIP backend when it is not running."""
        if self.app.voip_manager is None:
            return

        if self.app.voip_manager.running:
            self.app._voip_recovery.reset()
            return

        if recovery_now < self.app._voip_recovery.next_attempt_at:
            return

        logger.info("Attempting VoIP recovery")
        self.finalize_recovery_attempt(
            "VoIP",
            self.app._voip_recovery,
            self.app.voip_manager.start(),
            recovery_now,
        )

    def start_music_backend(self) -> bool:
        """Start the current music backend using the available lifecycle API."""
        if self.app.music_backend is None:
            return False

        start = getattr(self.app.music_backend, "start", None)
        if start is not None:
            return bool(start())

        connect = getattr(self.app.music_backend, "connect", None)
        if connect is not None:
            return bool(connect())

        return False

    def attempt_music_recovery(self, recovery_now: float) -> None:
        """Reconnect the music backend when it becomes unavailable."""
        if self.app.music_backend is None:
            return

        if self.app.music_backend.is_connected:
            self.app._music_recovery.reset()
            return

        if self.app._music_recovery.in_flight:
            return

        if recovery_now < self.app._music_recovery.next_attempt_at:
            return

        logger.info("Attempting music backend recovery")
        self.app._music_recovery.in_flight = True
        self.start_music_recovery_worker(recovery_now)

    def attempt_network_recovery(self, recovery_now: float) -> None:
        """Reinitialize the modem when cellular registration or PPP is down."""

        if (
            self.app.simulate
            or self.app.network_manager is None
            or not self.app.network_manager.config.enabled
        ):
            return

        if self.app._network_recovery.in_flight:
            return

        if self.app.network_manager.is_online:
            self.app._network_recovery.reset()
            return

        if recovery_now < self.app._network_recovery.next_attempt_at:
            return

        logger.info("Attempting network recovery")
        self.app._network_recovery.in_flight = True
        self.start_network_recovery_worker(recovery_now)

    def start_music_recovery_worker(self, recovery_now: float) -> None:
        """Launch the non-blocking music recovery attempt worker."""
        worker = threading.Thread(
            target=self.run_music_recovery_attempt,
            args=(recovery_now,),
            daemon=True,
            name="music-recovery",
        )
        worker.start()

    def start_network_recovery_worker(self, recovery_now: float) -> None:
        """Launch the non-blocking network recovery attempt worker."""

        worker = threading.Thread(
            target=self.run_network_recovery_attempt,
            args=(recovery_now,),
            daemon=True,
            name="network-recovery",
        )
        worker.start()

    def run_music_recovery_attempt(self, recovery_now: float) -> None:
        """Run a single music recovery attempt off the coordinator thread."""
        recovered = False
        if not self.app._stopping and self.app.music_backend is not None:
            recovered = self.start_music_backend()

        self.app.runtime_loop.queue_main_thread_callback(
            lambda: self.handle_recovery_attempt_completed(
                manager="music",
                recovered=recovered,
                recovery_now=recovery_now,
            )
        )

    def run_network_recovery_attempt(self, recovery_now: float) -> None:
        """Run one modem reinitialization attempt off the coordinator thread."""

        recovered = False
        if not self.app._stopping and self.app.network_manager is not None:
            recovered = self.app.network_manager.recover()

        self.app.runtime_loop.queue_main_thread_callback(
            lambda: self.handle_recovery_attempt_completed(
                manager="network",
                recovered=recovered,
                recovery_now=recovery_now,
            )
        )

    def finalize_recovery_attempt(
        self,
        label: str,
        state: RecoveryState,
        recovered: bool,
        recovery_now: float,
    ) -> None:
        """Update reconnect backoff after a recovery attempt."""
        if recovered:
            logger.info(f"{label} recovery succeeded")
            state.reset()
            return

        retry_in = state.delay_seconds
        logger.warning(f"{label} recovery failed, retrying in {retry_in:.0f}s")
        state.next_attempt_at = recovery_now + retry_in
        state.delay_seconds = min(
            state.delay_seconds * 2.0,
            self.app._RECOVERY_MAX_DELAY_SECONDS,
        )
