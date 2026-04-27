"""Process supervisor for the VoIP sidecar.

Owns the sidecar's :class:`multiprocessing.Process` lifecycle, runs a daemon
reader thread that pulls events off the pipe and dispatches them to the
caller's handler, and applies an exponential-backoff restart policy when the
sidecar dies unexpectedly. After ``max_failures`` failures inside
``failure_window_seconds`` the supervisor enters a permanent failure state
and stops attempting to restart; callers should surface a fatal status to
the UI in that case.

A loopback runner is also available (``use_loopback=True``) which runs the
sidecar entry point on a daemon thread inside the calling process instead of
spawning a child process. The protocol, handshake, and event-dispatch flow
are identical to the process runner, which makes loopback ideal for
integration tests that want real sidecar logic without paying the per-test
``spawn`` / ``forkserver`` cost.

Phase 2A wires this against the scaffold sidecar in
:mod:`yoyopod.integrations.call.sidecar_main`. Phase 2B replaces the
sidecar entry point with the real liblinphone backend; the supervisor
contract does not change.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from multiprocessing.connection import Connection
from multiprocessing.context import BaseContext
from typing import Any, Protocol

from loguru import logger

from yoyopod.integrations.call.sidecar_main import run_sidecar
from yoyopod.integrations.call.sidecar_protocol import (
    Hello,
    PROTOCOL_VERSION,
    ProtocolError,
    Ready,
    Shutdown,
    recv_event,
    send_message,
)


@dataclass(frozen=True, slots=True)
class RestartPolicy:
    """Auto-restart policy applied when the sidecar dies unexpectedly."""

    max_failures: int = 3
    failure_window_seconds: float = 60.0
    backoff_initial_seconds: float = 1.0
    backoff_factor: float = 2.0
    backoff_max_seconds: float = 4.0


@dataclass(frozen=True, slots=True)
class SupervisorState:
    """Snapshot of the supervisor's externally visible state."""

    state: str  # "stopped" | "starting" | "running" | "stopping" | "failed"
    restart_count: int
    permanent_failure_reason: str | None


SidecarTarget = Callable[[Connection], None]
EventHandler = Callable[[Any], None]


class _SidecarRunner(Protocol):
    """Minimal lifecycle surface shared by ``Process`` and the loopback thread runner."""

    name: str

    def start(self) -> None: ...

    def is_alive(self) -> bool: ...

    def join(self, timeout: float | None = ...) -> None: ...


class _LoopbackThreadRunner(threading.Thread):
    """Run the sidecar entry point on a daemon thread for in-process tests.

    Mirrors the slice of :class:`multiprocessing.Process` that
    :class:`SidecarSupervisor` consumes (``start``, ``is_alive``, ``join``),
    plus a no-op ``terminate``/``kill`` so the existing teardown path can
    treat both runners uniformly.
    """

    def __init__(
        self,
        *,
        target: SidecarTarget,
        conn: Connection,
        name: str = "voip-sidecar-loopback",
    ) -> None:
        super().__init__(target=target, args=(conn,), daemon=True, name=name)

    def terminate(self) -> None:
        """No-op; threads cannot be force-terminated. Loopback shutdown is cooperative."""

    def kill(self) -> None:
        """No-op; threads cannot be force-killed. Loopback shutdown is cooperative."""


class SidecarSupervisor:
    """Manage one VoIP sidecar process with auto-restart and event dispatch."""

    def __init__(
        self,
        *,
        on_event: EventHandler,
        restart_policy: RestartPolicy | None = None,
        start_method: str | None = None,
        sidecar_target: SidecarTarget = run_sidecar,
        handshake_timeout_seconds: float = 5.0,
        use_loopback: bool = False,
    ) -> None:
        self._on_event = on_event
        self._restart_policy = restart_policy or RestartPolicy()
        self._start_method = start_method or _default_start_method()
        self._sidecar_target = sidecar_target
        self._handshake_timeout_seconds = handshake_timeout_seconds
        self._use_loopback = use_loopback

        self._lock = threading.RLock()
        self._state = "stopped"
        self._process: _SidecarRunner | None = None
        self._parent_conn: Connection | None = None
        self._reader_thread: threading.Thread | None = None
        self._restart_timer: threading.Timer | None = None
        self._failure_times: deque[float] = deque()
        self._restart_count = 0
        self._permanent_failure_reason: str | None = None
        self._intentional_stop = threading.Event()
        self._intentional_stop.set()  # initially "stopped" means intentional

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch the sidecar process. No-op if already running or starting."""

        with self._lock:
            if self._state in ("starting", "running"):
                return
            if self._state == "failed":
                raise RuntimeError(f"Sidecar permanently failed: {self._permanent_failure_reason}")
            self._intentional_stop.clear()
            self._launch_locked()

    def stop(self, *, timeout_seconds: float = 2.0) -> None:
        """Send :class:`Shutdown`, join the sidecar, and cancel any pending restart."""

        with self._lock:
            if self._state == "stopped":
                return
            self._state = "stopping"
            self._intentional_stop.set()
            process = self._process
            conn = self._parent_conn
            restart_timer = self._restart_timer
            reader_thread = self._reader_thread

        if restart_timer is not None:
            restart_timer.cancel()

        if conn is not None:
            try:
                send_message(conn, Shutdown())
            except (BrokenPipeError, EOFError, OSError):
                pass
            try:
                conn.close()
            except OSError:
                pass

        if process is not None:
            process.join(timeout=timeout_seconds)
            if process.is_alive():
                logger.warning("Sidecar did not exit cleanly; terminating")
                process.terminate()
                process.join(timeout=1.0)
                if process.is_alive():
                    logger.error("Sidecar still alive after terminate; sending kill")
                    process.kill()
                    process.join(timeout=1.0)

        if reader_thread is not None:
            reader_thread.join(timeout=timeout_seconds)

        with self._lock:
            # ``_LoopbackThreadRunner.terminate``/``kill`` are no-ops because
            # CPython does not expose force-stop for a thread. If the loopback
            # target refused to honor ``Shutdown`` and the closed pipe, the
            # runner is still alive here. Mark the supervisor as ``"failed"``
            # so subsequent ``start()`` calls raise instead of leaking a
            # parallel runner alongside the stuck one.
            if process is not None and process.is_alive():
                self._state = "failed"
                self._permanent_failure_reason = (
                    f"sidecar runner {process.name!r} did not exit on stop; "
                    "force-termination is unavailable for the loopback runner"
                )
                logger.error("Sidecar permanently failed: {}", self._permanent_failure_reason)
                self._parent_conn = None
                self._reader_thread = None
                self._restart_timer = None
                return

            self._process = None
            self._parent_conn = None
            self._reader_thread = None
            self._restart_timer = None
            self._state = "stopped"

    def send(self, command: Any) -> None:
        """Send one command to the sidecar. Raises if the sidecar is not running."""

        with self._lock:
            conn = self._parent_conn
            state = self._state
        if conn is None or state != "running":
            raise RuntimeError(f"Cannot send command: sidecar state is {state!r}")
        try:
            send_message(conn, command)
        except (BrokenPipeError, EOFError, OSError) as exc:
            raise RuntimeError(f"Sidecar pipe closed during send: {exc}") from exc

    def state_snapshot(self) -> SupervisorState:
        """Return a snapshot of the supervisor's externally visible state."""

        with self._lock:
            return SupervisorState(
                state=self._state,
                restart_count=self._restart_count,
                permanent_failure_reason=self._permanent_failure_reason,
            )

    def wait_for_state(self, target: str, *, timeout_seconds: float) -> bool:
        """Block until the supervisor reaches ``target`` state. Returns True on success."""

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            with self._lock:
                if self._state == target:
                    return True
            time.sleep(0.01)
        return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_runner(self, child_conn: Connection) -> _SidecarRunner:
        """Construct the sidecar runner for the active mode (process or loopback)."""

        if self._use_loopback:
            return _LoopbackThreadRunner(target=self._sidecar_target, conn=child_conn)
        ctx: BaseContext = multiprocessing.get_context(self._start_method)
        return ctx.Process(
            target=self._sidecar_target,
            args=(child_conn,),
            daemon=True,
            name="voip-sidecar",
        )

    def _launch_locked(self) -> None:
        """Spawn one sidecar runner (process or loopback thread). Caller must hold ``self._lock``."""

        self._state = "starting"
        parent_conn, child_conn = multiprocessing.Pipe(duplex=True)
        process: _SidecarRunner = self._build_runner(child_conn)
        try:
            process.start()
        except Exception:
            parent_conn.close()
            child_conn.close()
            self._state = "stopped"
            raise

        # In process mode the child holds its own Connection; close ours to
        # it so the child sees EOF if the parent dies. The loopback runner
        # shares this process's address space, so closing the child end here
        # would cut both directions of the pipe.
        if not self._use_loopback:
            child_conn.close()

        self._process = process
        self._parent_conn = parent_conn

        # Run the handshake on the calling thread before starting the reader,
        # so the two are not racing for reads from the same pipe.
        if not self._await_handshake(parent_conn):
            self._state = "stopped"
            try:
                parent_conn.close()
            except OSError:
                pass
            if process.is_alive():
                process.terminate()
                process.join(timeout=1.0)

            # ``_LoopbackThreadRunner.terminate``/``kill`` are no-ops because
            # CPython does not expose force-stop for a thread. If the loopback
            # target blocked during startup and never reached Ready, the
            # original runner is still alive here. Scheduling a restart in
            # that state would launch a second loopback runner concurrently
            # and corrupt test state — surface a permanent failure instead.
            if process.is_alive():
                self._state = "failed"
                self._permanent_failure_reason = (
                    f"sidecar runner {process.name!r} did not exit after handshake "
                    "failure; force-termination is unavailable for the loopback runner"
                )
                logger.error("Sidecar permanently failed: {}", self._permanent_failure_reason)
                self._parent_conn = None
                return

            self._process = None
            self._parent_conn = None
            self._record_failure_and_maybe_restart(reason="handshake failed")
            return

        reader = threading.Thread(
            target=self._reader_loop,
            args=(parent_conn,),
            daemon=True,
            name="voip-sidecar-reader",
        )
        self._reader_thread = reader
        reader.start()

        self._state = "running"

    def _await_handshake(self, conn: Connection) -> bool:
        """Send our :class:`Hello`, wait for the sidecar's :class:`Ready`."""

        try:
            send_message(conn, Hello(version=PROTOCOL_VERSION))
        except (BrokenPipeError, EOFError, OSError) as exc:
            logger.warning("Sidecar handshake send failed: {}", exc)
            return False

        deadline = time.monotonic() + self._handshake_timeout_seconds
        while time.monotonic() < deadline:
            try:
                if not conn.poll(timeout=0.1):
                    continue
            except (BrokenPipeError, EOFError, OSError) as exc:
                logger.warning("Sidecar handshake poll failed: {}", exc)
                return False
            try:
                event = recv_event(conn)
            except (BrokenPipeError, EOFError, OSError) as exc:
                logger.warning("Sidecar handshake recv failed: {}", exc)
                return False
            except ProtocolError as exc:
                logger.warning("Sidecar handshake protocol error: {}", exc)
                continue
            if isinstance(event, Hello):
                if event.version != PROTOCOL_VERSION:
                    logger.error(
                        "Sidecar handshake version mismatch: expected {}, got {}",
                        PROTOCOL_VERSION,
                        event.version,
                    )
                    return False
                continue  # Wait for Ready next.
            if isinstance(event, Ready):
                return True
            # Forward unexpected pre-Ready events to the handler so nothing is lost.
            self._safe_dispatch(event)
        logger.warning("Sidecar handshake timed out after {}s", self._handshake_timeout_seconds)
        return False

    def _reader_loop(self, conn: Connection) -> None:
        """Drain events from the sidecar; trigger restart on pipe close."""

        while True:
            try:
                event = recv_event(conn)
            except (BrokenPipeError, EOFError, OSError):
                self._handle_sidecar_death()
                return
            except ProtocolError as exc:
                logger.warning("Sidecar emitted malformed frame: {}", exc)
                continue
            self._safe_dispatch(event)

    def _safe_dispatch(self, event: Any) -> None:
        try:
            self._on_event(event)
        except Exception:
            logger.exception("Sidecar event handler raised for {}", type(event).__name__)

    def _handle_sidecar_death(self) -> None:
        with self._lock:
            if self._intentional_stop.is_set():
                return
            self._record_failure_and_maybe_restart(reason="sidecar process exited")

    def _record_failure_and_maybe_restart(self, *, reason: str) -> None:
        """Caller must hold ``self._lock``."""

        # Drop the stale pipe so callers cannot send on a dead connection
        # while we wait for the restart timer to fire.
        stale_conn = self._parent_conn
        self._parent_conn = None
        if stale_conn is not None:
            try:
                stale_conn.close()
            except OSError:
                pass

        now = time.monotonic()
        self._failure_times.append(now)
        window_start = now - self._restart_policy.failure_window_seconds
        while self._failure_times and self._failure_times[0] < window_start:
            self._failure_times.popleft()

        if len(self._failure_times) >= self._restart_policy.max_failures:
            self._state = "failed"
            self._permanent_failure_reason = (
                f"{len(self._failure_times)} sidecar failures within "
                f"{self._restart_policy.failure_window_seconds:.0f}s ({reason})"
            )
            logger.error("Sidecar permanently failed: {}", self._permanent_failure_reason)
            return

        # Demote state during the backoff window so ``state_snapshot()``
        # cannot report "running" with a closed pipe and ``send()`` raises
        # cleanly until the restart timer fires and re-handshakes.
        self._state = "starting"

        backoff = self._next_backoff_seconds()
        self._restart_count += 1
        logger.warning(
            "Sidecar died ({}); restart #{} scheduled in {:.1f}s",
            reason,
            self._restart_count,
            backoff,
        )

        timer = threading.Timer(backoff, self._restart_callback)
        timer.daemon = True
        self._restart_timer = timer
        timer.start()

    def _next_backoff_seconds(self) -> float:
        attempt = max(0, len(self._failure_times) - 1)
        seconds = self._restart_policy.backoff_initial_seconds * (
            self._restart_policy.backoff_factor**attempt
        )
        return min(seconds, self._restart_policy.backoff_max_seconds)

    def _restart_callback(self) -> None:
        with self._lock:
            if self._intentional_stop.is_set():
                return
            if self._state == "failed":
                return
            self._launch_locked()


def _default_start_method() -> str:
    """Return the cheapest start method available on this platform."""

    available = multiprocessing.get_all_start_methods()
    if "forkserver" in available:
        return "forkserver"
    if "spawn" in available:
        return "spawn"
    return available[0]
