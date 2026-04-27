"""Lifecycle and restart-policy tests for :class:`SidecarSupervisor`."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

import pytest

from yoyopod.integrations.call.sidecar_main import run_sidecar
from yoyopod.integrations.call.sidecar_protocol import (
    Hello,
    PROTOCOL_VERSION,
    Ping,
    Pong,
    Ready,
    send_message,
)
from yoyopod.integrations.call.sidecar_supervisor import (
    RestartPolicy,
    SidecarSupervisor,
)

SPAWN_BUDGET_SECONDS = 12.0
"""Generous timeout for Python spawn on slower CI hosts (especially Windows)."""


# ---------------------------------------------------------------------------
# Module-level sidecar targets (must be picklable for ``spawn``)
# ---------------------------------------------------------------------------


def _instant_exit_target(_conn: Connection) -> None:
    """Sidecar target that exits immediately after handshake start."""

    # Don't even respond to the handshake; the supervisor will time out and
    # treat it as a failed startup.
    return


def _exit_after_first_command_target(conn: Connection) -> None:
    """Sidecar target that completes handshake then exits on first command."""

    send_message(conn, Hello(version=PROTOCOL_VERSION))
    try:
        peer_hello = conn.recv_bytes()  # consume Hello frame
        del peer_hello
    except (BrokenPipeError, EOFError, OSError):
        return
    send_message(conn, Ready())
    try:
        conn.recv_bytes()  # wait for first command, then exit
    except (BrokenPipeError, EOFError, OSError):
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def collected_events() -> list[Any]:
    return []


@pytest.fixture
def event_handler(collected_events: list[Any]) -> Callable[[Any], None]:
    return collected_events.append


# ---------------------------------------------------------------------------
# Happy-path lifecycle
# ---------------------------------------------------------------------------


def test_start_drives_supervisor_to_running_state(
    event_handler: Callable[[Any], None],
) -> None:
    supervisor = SidecarSupervisor(
        on_event=event_handler,
        start_method="spawn",
        sidecar_target=run_sidecar,
        handshake_timeout_seconds=SPAWN_BUDGET_SECONDS,
    )
    try:
        supervisor.start()
        assert supervisor.wait_for_state("running", timeout_seconds=SPAWN_BUDGET_SECONDS)
    finally:
        supervisor.stop(timeout_seconds=SPAWN_BUDGET_SECONDS)
        snapshot = supervisor.state_snapshot()
        assert snapshot.state == "stopped"


def test_send_ping_round_trips_to_pong(
    collected_events: list[Any], event_handler: Callable[[Any], None]
) -> None:
    supervisor = SidecarSupervisor(
        on_event=event_handler,
        start_method="spawn",
        sidecar_target=run_sidecar,
        handshake_timeout_seconds=SPAWN_BUDGET_SECONDS,
    )
    try:
        supervisor.start()
        assert supervisor.wait_for_state("running", timeout_seconds=SPAWN_BUDGET_SECONDS)
        supervisor.send(Ping(cmd_id=99))

        deadline = time.monotonic() + SPAWN_BUDGET_SECONDS
        while time.monotonic() < deadline:
            if any(isinstance(event, Pong) and event.cmd_id == 99 for event in collected_events):
                break
            time.sleep(0.05)

        assert any(
            isinstance(event, Pong) and event.cmd_id == 99 for event in collected_events
        ), f"never received Pong; saw {[type(e).__name__ for e in collected_events]}"
    finally:
        supervisor.stop(timeout_seconds=SPAWN_BUDGET_SECONDS)


# ---------------------------------------------------------------------------
# Error and idempotency paths
# ---------------------------------------------------------------------------


def test_send_when_stopped_raises(event_handler: Callable[[Any], None]) -> None:
    supervisor = SidecarSupervisor(
        on_event=event_handler,
        start_method="spawn",
        sidecar_target=run_sidecar,
    )
    with pytest.raises(RuntimeError, match="sidecar state is 'stopped'"):
        supervisor.send(Ping(cmd_id=1))


def test_start_is_idempotent(event_handler: Callable[[Any], None]) -> None:
    supervisor = SidecarSupervisor(
        on_event=event_handler,
        start_method="spawn",
        sidecar_target=run_sidecar,
        handshake_timeout_seconds=SPAWN_BUDGET_SECONDS,
    )
    try:
        supervisor.start()
        assert supervisor.wait_for_state("running", timeout_seconds=SPAWN_BUDGET_SECONDS)
        supervisor.start()  # second start should be a no-op while running
        assert supervisor.state_snapshot().state == "running"
    finally:
        supervisor.stop(timeout_seconds=SPAWN_BUDGET_SECONDS)


def test_stop_is_idempotent(event_handler: Callable[[Any], None]) -> None:
    supervisor = SidecarSupervisor(
        on_event=event_handler,
        start_method="spawn",
        sidecar_target=run_sidecar,
    )
    supervisor.stop()
    supervisor.stop()
    assert supervisor.state_snapshot().state == "stopped"


# ---------------------------------------------------------------------------
# Restart and permanent-failure paths
# ---------------------------------------------------------------------------


def test_handshake_timeout_records_failure(event_handler: Callable[[Any], None]) -> None:
    """A target that never responds counts as a failure and triggers backoff."""

    supervisor = SidecarSupervisor(
        on_event=event_handler,
        start_method="spawn",
        sidecar_target=_instant_exit_target,
        handshake_timeout_seconds=0.5,
        restart_policy=RestartPolicy(
            max_failures=2,
            failure_window_seconds=30.0,
            backoff_initial_seconds=0.1,
            backoff_factor=1.0,
            backoff_max_seconds=0.1,
        ),
    )
    try:
        supervisor.start()
        # First failure schedules a restart.
        deadline = time.monotonic() + SPAWN_BUDGET_SECONDS
        while time.monotonic() < deadline:
            snapshot = supervisor.state_snapshot()
            if snapshot.state == "failed":
                break
            time.sleep(0.1)
        snapshot = supervisor.state_snapshot()
        assert snapshot.state == "failed"
        assert snapshot.permanent_failure_reason is not None
        assert "failures within" in snapshot.permanent_failure_reason
    finally:
        supervisor.stop(timeout_seconds=SPAWN_BUDGET_SECONDS)


def test_start_after_permanent_failure_raises(
    event_handler: Callable[[Any], None],
) -> None:
    supervisor = SidecarSupervisor(
        on_event=event_handler,
        start_method="spawn",
        sidecar_target=_instant_exit_target,
        handshake_timeout_seconds=0.5,
        restart_policy=RestartPolicy(
            max_failures=1,
            failure_window_seconds=30.0,
            backoff_initial_seconds=0.05,
            backoff_factor=1.0,
            backoff_max_seconds=0.05,
        ),
    )
    try:
        supervisor.start()
        deadline = time.monotonic() + SPAWN_BUDGET_SECONDS
        while time.monotonic() < deadline:
            if supervisor.state_snapshot().state == "failed":
                break
            time.sleep(0.05)
        assert supervisor.state_snapshot().state == "failed"

        with pytest.raises(RuntimeError, match="permanently failed"):
            supervisor.start()
    finally:
        supervisor.stop(timeout_seconds=SPAWN_BUDGET_SECONDS)


def test_unexpected_exit_triggers_restart(event_handler: Callable[[Any], None]) -> None:
    """A sidecar that handshakes then exits on first command should be restarted."""

    supervisor = SidecarSupervisor(
        on_event=event_handler,
        start_method="spawn",
        sidecar_target=_exit_after_first_command_target,
        handshake_timeout_seconds=SPAWN_BUDGET_SECONDS,
        restart_policy=RestartPolicy(
            max_failures=5,
            failure_window_seconds=60.0,
            backoff_initial_seconds=0.05,
            backoff_factor=1.0,
            backoff_max_seconds=0.05,
        ),
    )
    try:
        supervisor.start()
        assert supervisor.wait_for_state("running", timeout_seconds=SPAWN_BUDGET_SECONDS)
        supervisor.send(Ping(cmd_id=1))

        deadline = time.monotonic() + SPAWN_BUDGET_SECONDS
        while time.monotonic() < deadline:
            snapshot = supervisor.state_snapshot()
            if snapshot.restart_count >= 1 and snapshot.state == "running":
                break
            time.sleep(0.05)

        snapshot = supervisor.state_snapshot()
        assert snapshot.restart_count >= 1, snapshot
        assert snapshot.state == "running", snapshot
    finally:
        supervisor.stop(timeout_seconds=SPAWN_BUDGET_SECONDS)


def test_state_demotes_from_running_after_unexpected_exit(
    event_handler: Callable[[Any], None],
) -> None:
    """After a sidecar dies, ``state_snapshot()`` must not report ``running``
    until the restart re-handshakes; ``send()`` must raise during the
    backoff window instead of trying to write to a dead pipe."""

    long_backoff = 5.0  # longer than the test's observation window
    supervisor = SidecarSupervisor(
        on_event=event_handler,
        start_method="spawn",
        sidecar_target=_exit_after_first_command_target,
        handshake_timeout_seconds=SPAWN_BUDGET_SECONDS,
        restart_policy=RestartPolicy(
            max_failures=5,
            failure_window_seconds=60.0,
            backoff_initial_seconds=long_backoff,
            backoff_factor=1.0,
            backoff_max_seconds=long_backoff,
        ),
    )
    try:
        supervisor.start()
        assert supervisor.wait_for_state("running", timeout_seconds=SPAWN_BUDGET_SECONDS)
        supervisor.send(Ping(cmd_id=1))

        # Wait for state to fall out of "running" once the sidecar dies.
        deadline = time.monotonic() + SPAWN_BUDGET_SECONDS
        while time.monotonic() < deadline:
            if supervisor.state_snapshot().state != "running":
                break
            time.sleep(0.02)

        snapshot = supervisor.state_snapshot()
        assert snapshot.state != "running", snapshot
        assert snapshot.state != "failed", snapshot

        # send() must raise cleanly while the supervisor is in backoff —
        # the previous bug let it fall through to a dead pipe write.
        with pytest.raises(RuntimeError, match=r"sidecar state is"):
            supervisor.send(Ping(cmd_id=2))
    finally:
        supervisor.stop(timeout_seconds=SPAWN_BUDGET_SECONDS)


def test_intentional_stop_does_not_trigger_restart(
    event_handler: Callable[[Any], None],
) -> None:
    supervisor = SidecarSupervisor(
        on_event=event_handler,
        start_method="spawn",
        sidecar_target=run_sidecar,
        handshake_timeout_seconds=SPAWN_BUDGET_SECONDS,
        restart_policy=RestartPolicy(
            max_failures=5,
            failure_window_seconds=60.0,
            backoff_initial_seconds=0.05,
            backoff_factor=1.0,
            backoff_max_seconds=0.05,
        ),
    )
    supervisor.start()
    assert supervisor.wait_for_state("running", timeout_seconds=SPAWN_BUDGET_SECONDS)

    supervisor.stop(timeout_seconds=SPAWN_BUDGET_SECONDS)
    # Wait briefly to ensure no restart fires after intentional stop.
    time.sleep(0.5)
    snapshot = supervisor.state_snapshot()
    assert snapshot.state == "stopped"
    assert snapshot.restart_count == 0


def test_state_snapshot_reflects_lifecycle(event_handler: Callable[[Any], None]) -> None:
    supervisor = SidecarSupervisor(
        on_event=event_handler,
        start_method="spawn",
        sidecar_target=run_sidecar,
        handshake_timeout_seconds=SPAWN_BUDGET_SECONDS,
    )
    assert supervisor.state_snapshot().state == "stopped"
    try:
        supervisor.start()
        assert supervisor.wait_for_state("running", timeout_seconds=SPAWN_BUDGET_SECONDS)
        assert supervisor.state_snapshot().state == "running"
    finally:
        supervisor.stop(timeout_seconds=SPAWN_BUDGET_SECONDS)
        assert supervisor.state_snapshot().state == "stopped"


# ---------------------------------------------------------------------------
# Reader-thread isolation
# ---------------------------------------------------------------------------


def test_event_handler_exception_does_not_kill_reader(
    event_handler: Callable[[Any], None],
) -> None:
    """If the on_event handler raises, subsequent events still flow."""

    received: list[Any] = []
    raised = threading.Event()

    def handler(event: Any) -> None:
        received.append(event)
        if not raised.is_set():
            raised.set()
            raise RuntimeError("first-event boom")

    supervisor = SidecarSupervisor(
        on_event=handler,
        start_method="spawn",
        sidecar_target=run_sidecar,
        handshake_timeout_seconds=SPAWN_BUDGET_SECONDS,
    )
    try:
        supervisor.start()
        assert supervisor.wait_for_state("running", timeout_seconds=SPAWN_BUDGET_SECONDS)
        supervisor.send(Ping(cmd_id=1))
        supervisor.send(Ping(cmd_id=2))

        deadline = time.monotonic() + SPAWN_BUDGET_SECONDS
        while time.monotonic() < deadline:
            pong_ids = sorted(event.cmd_id for event in received if isinstance(event, Pong))
            if pong_ids == [1, 2]:
                break
            time.sleep(0.05)

        pong_ids = sorted(event.cmd_id for event in received if isinstance(event, Pong))
        assert pong_ids == [1, 2], pong_ids
        assert raised.is_set()
    finally:
        supervisor.stop(timeout_seconds=SPAWN_BUDGET_SECONDS)
