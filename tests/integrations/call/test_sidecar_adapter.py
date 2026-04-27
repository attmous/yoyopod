"""Unit tests for :class:`SidecarBackendAdapter`.

The adapter owns command->backend dispatch and backend->protocol event
translation inside the sidecar process. These tests run the adapter in
isolation (no supervisor, no subprocess) by feeding it commands directly
and reading the events it writes onto a real ``multiprocessing.Pipe``.
"""

from __future__ import annotations

import multiprocessing
import threading
import time
from multiprocessing.connection import Connection
from typing import Any

import pytest

from yoyopod.backends.voip.mock_backend import MockVoIPBackend
from yoyopod.integrations.call.models import (
    BackendStopped,
    CallState,
    CallStateChanged as BackendCallStateChanged,
    IncomingCallDetected,
    MessageDeliveryChanged as BackendMessageDeliveryChanged,
    MessageDeliveryState,
    MessageDirection,
    MessageDownloadCompleted as BackendMessageDownloadCompleted,
    MessageFailed as BackendMessageFailed,
    MessageKind,
    MessageReceived as BackendMessageReceived,
    RegistrationState,
    RegistrationStateChanged as BackendRegistrationStateChanged,
    VoIPConfig,
    VoIPMessageRecord,
)
from yoyopod.integrations.call.sidecar_adapter import SidecarBackendAdapter
from yoyopod.integrations.call.sidecar_protocol import (
    Accept,
    CallStateChanged,
    CancelVoiceNoteRecording,
    Configure,
    Dial,
    Error,
    Hangup,
    IncomingCall,
    Log,
    MediaStateChanged,
    MessageDeliveryChanged,
    MessageDownloadCompleted,
    MessageFailed,
    MessageReceived,
    Ping,
    Pong,
    Register,
    RegistrationStateChanged,
    Reject,
    SendTextMessage,
    SendVoiceNote,
    SetMute,
    SetVolume,
    StartVoiceNoteRecording,
    StopVoiceNoteRecording,
    Unregister,
    decode_event,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def pipe() -> tuple[Connection, Connection]:
    parent, child = multiprocessing.Pipe(duplex=True)
    yield parent, child
    try:
        parent.close()
    except OSError:
        pass
    try:
        child.close()
    except OSError:
        pass


@pytest.fixture
def parent_conn(pipe: tuple[Connection, Connection]) -> Connection:
    return pipe[0]


@pytest.fixture
def child_conn(pipe: tuple[Connection, Connection]) -> Connection:
    return pipe[1]


@pytest.fixture
def mock_backend() -> MockVoIPBackend:
    return MockVoIPBackend()


@pytest.fixture
def adapter(child_conn: Connection, mock_backend: MockVoIPBackend) -> SidecarBackendAdapter:
    captured: list[MockVoIPBackend] = []

    def factory(_config: VoIPConfig) -> MockVoIPBackend:
        captured.append(mock_backend)
        return mock_backend

    instance = SidecarBackendAdapter(conn=child_conn, backend_factory=factory)
    instance.__test_factory_calls__ = captured  # type: ignore[attr-defined]
    yield instance
    instance.shutdown()


def _drain(conn: Connection, *, timeout: float = 0.5) -> list[Any]:
    """Read every event currently available on the pipe within ``timeout``."""

    deadline = time.monotonic() + timeout
    events: list[Any] = []
    while time.monotonic() < deadline:
        if conn.poll(timeout=0.05):
            try:
                events.append(decode_event(conn.recv_bytes()))
            except (BrokenPipeError, EOFError, OSError):
                break
        elif events:
            break
    return events


def _wait_for(predicate, *, timeout: float = 0.5) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def _config_dict(**overrides: Any) -> dict[str, Any]:
    base = VoIPConfig(sip_server="sip.example.com", sip_identity="sip:alice@example.com")
    payload = {
        f.name: getattr(base, f.name)
        for f in [field for field in VoIPConfig.__dataclass_fields__.values()]
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Configure
# ---------------------------------------------------------------------------


def test_configure_creates_backend_and_logs_info(
    adapter: SidecarBackendAdapter, parent_conn: Connection, mock_backend: MockVoIPBackend
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    events = _drain(parent_conn)

    assert any(
        isinstance(event, Log) and event.level == "INFO" and "configured backend" in event.message
        for event in events
    )
    # Adapter should have asked the factory for one backend.
    assert mock_backend.event_callbacks, "factory should have wired backend callbacks"


def test_configure_with_unknown_field_returns_invalid_config_error(
    adapter: SidecarBackendAdapter, parent_conn: Connection
) -> None:
    bogus = _config_dict()
    bogus["not_a_real_field"] = "boom"
    adapter.handle_command(Configure(config=bogus, cmd_id=42))
    events = _drain(parent_conn)
    errors = [event for event in events if isinstance(event, Error)]
    assert any(error.code == "invalid_config" and error.cmd_id == 42 for error in errors), events


def test_shutdown_stops_backend_even_when_not_running(
    parent_conn: Connection, child_conn: Connection
) -> None:
    """``shutdown()`` must call ``backend.stop()`` regardless of ``backend.running``.

    Codex follow-up review on #389 (P1): liblinphone flips ``running`` to
    False when ``iterate()`` raises, but the native core/transports/audio
    devices still need an explicit ``stop()`` to be released. Skipping the
    call leaks native state into the next backend created by a follow-up
    ``Configure``.
    """

    class _StopTrackingMockBackend(MockVoIPBackend):
        def __init__(self) -> None:
            super().__init__()
            self.stop_called = 0

        def stop(self) -> None:
            self.stop_called += 1
            super().stop()

    backend = _StopTrackingMockBackend()
    adapter = SidecarBackendAdapter(
        conn=child_conn,
        backend_factory=lambda _config: backend,
    )
    try:
        adapter.handle_command(Configure(config=_config_dict()))
        adapter.handle_command(Register(cmd_id=1))
        _drain(parent_conn)
        assert _wait_for(lambda: backend.running)

        # Simulate the iterate-failure path: liblinphone flips ``running``
        # to False internally without going through ``stop()``.
        backend.running = False

        adapter.shutdown()
        assert (
            backend.stop_called == 1
        ), "shutdown() must call backend.stop() even when running is False"
    finally:
        adapter.shutdown()  # idempotent — must not double-stop


def test_configure_clears_active_call_state(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    """A re-Configure during an active call must reset the tracked call id.

    Codex follow-up review on #389 (P1): without this, a Configure issued
    while a call is active leaves ``_current_call_id`` pinned to the old
    backend's call. The subsequent Dial against the fresh backend is then
    rejected with ``call_in_progress``.
    """

    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    mock_backend.emit(IncomingCallDetected(caller_address="sip:caller@example.com"))
    _drain(parent_conn)
    assert adapter._current_call_id is not None

    # Re-Configure: should drop the old backend, fresh-create, and clear call state.
    adapter.handle_command(Configure(config=_config_dict()))
    _drain(parent_conn)
    assert adapter._current_call_id is None

    # And a fresh Register + Dial cycle must succeed without ``call_in_progress``.
    adapter.handle_command(Register(cmd_id=2))
    _drain(parent_conn)
    adapter.handle_command(Dial(uri="sip:carol@example.com", cmd_id=3))
    events = _drain(parent_conn)
    errors = [event for event in events if isinstance(event, Error)]
    assert not any(error.code == "call_in_progress" for error in errors), errors


# ---------------------------------------------------------------------------
# Register / Unregister
# ---------------------------------------------------------------------------


def test_register_before_configure_returns_not_configured(
    adapter: SidecarBackendAdapter, parent_conn: Connection
) -> None:
    adapter.handle_command(Register(cmd_id=7))
    events = _drain(parent_conn)
    assert any(
        isinstance(event, Error) and event.code == "not_configured" and event.cmd_id == 7
        for event in events
    )


def test_register_starts_backend_and_iterate_thread(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    _drain(parent_conn)

    adapter.handle_command(Register(cmd_id=2))
    assert _wait_for(lambda: mock_backend.running)
    assert mock_backend.running is True
    assert adapter._iterate_thread is not None
    assert adapter._iterate_thread.is_alive()


def test_register_when_backend_start_returns_false_emits_error(
    parent_conn: Connection, child_conn: Connection
) -> None:
    failing_backend = MockVoIPBackend(start_result=False)

    def factory(_config: VoIPConfig) -> MockVoIPBackend:
        return failing_backend

    adapter = SidecarBackendAdapter(conn=child_conn, backend_factory=factory)
    try:
        adapter.handle_command(Configure(config=_config_dict()))
        _drain(parent_conn)
        adapter.handle_command(Register(cmd_id=3))
        events = _drain(parent_conn)
        assert any(
            isinstance(event, Error) and event.code == "register_failed" and event.cmd_id == 3
            for event in events
        )
    finally:
        adapter.shutdown()


def test_unregister_stops_backend_and_iterate_thread(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)
    assert _wait_for(lambda: mock_backend.running)

    adapter.handle_command(Unregister())
    assert _wait_for(lambda: not mock_backend.running)
    assert adapter._wait_for_iterate_thread_to_exit(timeout=1.0)


def test_unregister_clears_current_call_id(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    """After Unregister, a follow-up Dial must not return ``call_in_progress``.

    Codex review on #389 (P1): the iterate loop is stopped before
    backend.stop(), so any terminal call-state event the backend would emit
    on teardown is not guaranteed to flow through. _handle_unregister must
    therefore reset the tracked call id explicitly.
    """

    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)
    mock_backend.emit(IncomingCallDetected(caller_address="sip:bob@example.com"))
    events = _drain(parent_conn)
    assert any(isinstance(event, IncomingCall) for event in events)
    assert adapter._current_call_id is not None

    adapter.handle_command(Unregister())
    assert _wait_for(lambda: not mock_backend.running)
    assert adapter._current_call_id is None

    # A follow-up re-register + dial must succeed instead of being blocked by
    # the stale call id from the previous registration.
    mock_backend.start_result = True  # default already, but make it explicit
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=2))
    _drain(parent_conn)
    adapter.handle_command(Dial(uri="sip:carol@example.com", cmd_id=3))
    events = _drain(parent_conn)
    errors = [event for event in events if isinstance(event, Error)]
    assert not any(
        error.code == "call_in_progress" for error in errors
    ), f"call_in_progress leaked across unregister: {errors!r}"


def test_register_with_stale_iterate_thread_returns_iterate_thread_busy() -> None:
    """Register must not silently start a backend when a stale iterate thread blocks the start.

    Codex follow-up review on #389 (P1): the round-1 fix retains the
    iterate-thread handle when ``join`` times out, so
    ``_start_iterate_thread`` silently returns to avoid racing two iterate
    threads against the same backend. But callers also need that visibility:
    a follow-up ``Configure + Register`` would otherwise start a fresh
    backend with no iterate driver, registration/call events would stop
    flowing, and the command path would still report success. The fixed
    handler surfaces ``iterate_thread_busy`` and leaves the freshly created
    backend untouched so ``main`` can retry once the stale thread exits.
    """

    parent, child = multiprocessing.Pipe(duplex=True)
    try:
        backend = MockVoIPBackend()
        adapter = SidecarBackendAdapter(
            conn=child,
            backend_factory=lambda _config: backend,
        )
        # Plant a stuck stale iterate thread directly.
        release = threading.Event()
        stuck_thread = threading.Thread(
            target=lambda: release.wait(timeout=10.0),
            daemon=True,
            name="voip-sidecar-iterate-stale-stub",
        )
        stuck_thread.start()
        adapter._iterate_thread = stuck_thread

        # Configure to install the backend, then attempt Register.
        adapter.handle_command(Configure(config=_config_dict()))
        _drain(parent)

        adapter.handle_command(Register(cmd_id=99))
        events = _drain(parent)
        errors = [event for event in events if isinstance(event, Error)]
        assert any(
            error.code == "iterate_thread_busy" and error.cmd_id == 99 for error in errors
        ), events
        # backend.start() must NOT have been called — the stale-thread check
        # short-circuits Register before the backend is touched.
        assert (
            backend.running is False
        ), "Register must not start backend when iterate-thread is busy"

        release.set()
        stuck_thread.join(timeout=1.0)
    finally:
        try:
            parent.close()
        except OSError:
            pass
        try:
            child.close()
        except OSError:
            pass


def test_stop_iterate_thread_retains_handle_on_join_timeout() -> None:
    """A stuck iterate thread must not be silently forgotten.

    Codex review on #389 (P1): if ``_stop_iterate_thread`` cleared
    ``_iterate_thread = None`` even when ``join`` timed out, a follow-up
    ``Register`` would happily spawn a second iterate thread alongside the
    still-running one. Both would race ``backend.iterate()``. This test
    drives the stuck case directly and asserts the handle is retained, so
    ``_start_iterate_thread`` short-circuits on ``is_alive()``.
    """

    parent, child = multiprocessing.Pipe(duplex=True)
    try:
        adapter = SidecarBackendAdapter(
            conn=child,
            backend_factory=lambda _config: MockVoIPBackend(),
        )
        # Plant a synthetic stuck thread directly into the adapter so the
        # test does not rely on a misbehaving backend.
        release = threading.Event()
        stuck_thread = threading.Thread(
            target=lambda: release.wait(timeout=10.0),
            daemon=True,
            name="voip-sidecar-iterate-test-stub",
        )
        stuck_thread.start()
        adapter._iterate_thread = stuck_thread

        # Tighten the join timeout so the test runs quickly.
        adapter._ITERATE_JOIN_TIMEOUT_SECONDS = 0.05  # type: ignore[misc]

        adapter._stop_iterate_thread()

        # Handle must still reference the alive thread.
        assert adapter._iterate_thread is stuck_thread
        assert adapter._iterate_thread.is_alive()

        # And the start path must refuse to spawn a parallel iterate thread
        # while the old one is still alive.
        adapter._start_iterate_thread()
        assert adapter._iterate_thread is stuck_thread

        release.set()
        stuck_thread.join(timeout=1.0)
    finally:
        try:
            parent.close()
        except OSError:
            pass
        try:
            child.close()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Call control
# ---------------------------------------------------------------------------


def test_dial_assigns_call_id_and_calls_backend(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    adapter.handle_command(Dial(uri="sip:bob@example.com", cmd_id=10))
    assert mock_backend.commands[-1] == "call sip:bob@example.com"
    assert adapter._current_call_id is not None


def test_dial_when_call_in_progress_returns_call_in_progress_error(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    adapter.handle_command(Dial(uri="sip:bob@example.com", cmd_id=10))
    adapter.handle_command(Dial(uri="sip:carol@example.com", cmd_id=11))

    events = _drain(parent_conn)
    assert any(
        isinstance(event, Error) and event.code == "call_in_progress" and event.cmd_id == 11
        for event in events
    )


def test_accept_with_unknown_call_id_returns_error(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    adapter.handle_command(Accept(call_id="call-bogus", cmd_id=20))
    events = _drain(parent_conn)
    assert any(
        isinstance(event, Error) and event.code == "unknown_call_id" and event.cmd_id == 20
        for event in events
    )
    assert "answer" not in mock_backend.commands


def test_accept_with_correct_call_id_calls_backend(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    mock_backend.emit(IncomingCallDetected(caller_address="sip:bob@example.com"))
    events = _drain(parent_conn)
    incoming = next(event for event in events if isinstance(event, IncomingCall))

    adapter.handle_command(Accept(call_id=incoming.call_id, cmd_id=21))
    assert "answer" in mock_backend.commands


def test_hangup_with_correct_call_id_calls_backend(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    mock_backend.emit(IncomingCallDetected(caller_address="sip:bob@example.com"))
    events = _drain(parent_conn)
    incoming = next(event for event in events if isinstance(event, IncomingCall))

    adapter.handle_command(Hangup(call_id=incoming.call_id, cmd_id=22))
    assert "terminate" in mock_backend.commands


def test_set_mute_emits_media_state_changed(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    mock_backend.emit(IncomingCallDetected(caller_address="sip:bob@example.com"))
    events = _drain(parent_conn)
    incoming = next(event for event in events if isinstance(event, IncomingCall))

    adapter.handle_command(SetMute(call_id=incoming.call_id, on=True))
    events = _drain(parent_conn)
    assert "mute" in mock_backend.commands
    assert any(
        isinstance(event, MediaStateChanged)
        and event.call_id == incoming.call_id
        and event.mic_muted
        for event in events
    )


def test_set_volume_does_not_call_backend_but_emits_media_state(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    mock_backend.emit(IncomingCallDetected(caller_address="sip:bob@example.com"))
    events = _drain(parent_conn)
    incoming = next(event for event in events if isinstance(event, IncomingCall))

    adapter.handle_command(SetVolume(call_id=incoming.call_id, level=0.4))
    events = _drain(parent_conn)
    media = [event for event in events if isinstance(event, MediaStateChanged)]
    assert media and media[-1].speaker_volume == pytest.approx(0.4)


def test_set_volume_with_unknown_call_id_returns_error(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    """A delayed SetVolume from a previous call must not mutate the current call.

    Codex follow-up review on #389 (P2): without call-id validation, a stale
    SetVolume frame can flip the adapter's tracked volume mid-call. Now the
    handler validates the id like other call-scoped commands.
    """

    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)
    mock_backend.emit(IncomingCallDetected(caller_address="sip:bob@example.com"))
    _drain(parent_conn)

    adapter.handle_command(SetVolume(call_id="call-bogus", level=0.5, cmd_id=77))
    events = _drain(parent_conn)
    errors = [event for event in events if isinstance(event, Error)]
    assert any(error.code == "unknown_call_id" and error.cmd_id == 77 for error in errors), events
    # Volume must not have changed.
    assert adapter._speaker_volume == 1.0


def test_set_volume_without_backend_returns_not_configured(
    adapter: SidecarBackendAdapter, parent_conn: Connection
) -> None:
    """SetVolume before Configure surfaces ``not_configured`` like other commands."""

    adapter.handle_command(SetVolume(call_id="call-1", level=0.5, cmd_id=88))
    events = _drain(parent_conn)
    errors = [event for event in events if isinstance(event, Error)]
    assert any(error.code == "not_configured" and error.cmd_id == 88 for error in errors), events


# ---------------------------------------------------------------------------
# Backend events -> protocol events
# ---------------------------------------------------------------------------


def test_backend_registration_state_propagates(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    _drain(parent_conn)

    mock_backend.emit(BackendRegistrationStateChanged(state=RegistrationState.OK))
    events = _drain(parent_conn)
    assert any(
        isinstance(event, RegistrationStateChanged) and event.state == "ok" for event in events
    )


def test_backend_call_state_propagates_with_call_id(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    _drain(parent_conn)

    mock_backend.emit(IncomingCallDetected(caller_address="sip:caller@example.com"))
    events = _drain(parent_conn)
    incoming = next(event for event in events if isinstance(event, IncomingCall))

    mock_backend.emit(BackendCallStateChanged(state=CallState.CONNECTED))
    events = _drain(parent_conn)
    assert any(
        isinstance(event, CallStateChanged)
        and event.call_id == incoming.call_id
        and event.state == "connected"
        for event in events
    )


def test_call_released_clears_current_call_id(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    _drain(parent_conn)

    mock_backend.emit(IncomingCallDetected(caller_address="sip:caller@example.com"))
    _drain(parent_conn)

    mock_backend.emit(BackendCallStateChanged(state=CallState.RELEASED))
    _drain(parent_conn)
    assert adapter._current_call_id is None


def test_call_end_state_is_terminal(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    """``CallState.END`` must be treated as terminal alongside RELEASED.

    Codex follow-up review on #389 (P1): liblinphone maps native state 13
    to ``CallState.END`` and may emit it without a later ``RELEASED``
    frame. The previous adapter only treated ``{RELEASED, ERROR, IDLE}``
    as terminal, leaving the call id pinned and blocking subsequent Dials
    with ``call_in_progress``.
    """

    adapter.handle_command(Configure(config=_config_dict()))
    _drain(parent_conn)

    mock_backend.emit(IncomingCallDetected(caller_address="sip:caller@example.com"))
    _drain(parent_conn)
    assert adapter._current_call_id is not None

    mock_backend.emit(BackendCallStateChanged(state=CallState.END))
    _drain(parent_conn)
    assert adapter._current_call_id is None


def test_backend_stopped_emits_error_event(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    _drain(parent_conn)

    mock_backend.emit(BackendStopped(reason="link reset"))
    events = _drain(parent_conn)
    assert any(
        isinstance(event, Error)
        and event.code == "backend_stopped"
        and "link reset" in event.message
        for event in events
    )


def test_backend_stopped_clears_active_call_id(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    """``BackendStopped`` mid-call must clear the tracked call id.

    Codex follow-up review on #389 (P1): if the backend dies during an
    active call (e.g. liblinphone's ``iterate()`` raises and emits
    ``BackendStopped``), the stale ``_current_call_id`` would otherwise
    block subsequent ``Dial`` commands with ``call_in_progress`` even
    after a recovery ``Configure`` swaps in a fresh backend.
    """

    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    mock_backend.emit(IncomingCallDetected(caller_address="sip:bob@example.com"))
    _drain(parent_conn)
    assert adapter._current_call_id is not None

    mock_backend.emit(BackendStopped(reason="iterate failed"))
    _drain(parent_conn)
    assert adapter._current_call_id is None

    # And a fresh Configure + Register + Dial cycle is no longer blocked.
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=2))
    _drain(parent_conn)
    adapter.handle_command(Dial(uri="sip:carol@example.com", cmd_id=3))
    events = _drain(parent_conn)
    errors = [event for event in events if isinstance(event, Error)]
    assert not any(error.code == "call_in_progress" for error in errors), errors


# ---------------------------------------------------------------------------
# Ping
# ---------------------------------------------------------------------------


def test_ping_returns_pong_without_backend(
    adapter: SidecarBackendAdapter, parent_conn: Connection
) -> None:
    adapter.handle_command(Ping(cmd_id=99))
    events = _drain(parent_conn)
    assert any(isinstance(event, Pong) and event.cmd_id == 99 for event in events)


# ---------------------------------------------------------------------------
# Reject path
# ---------------------------------------------------------------------------


def test_reject_with_correct_call_id_calls_backend(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    mock_backend.emit(IncomingCallDetected(caller_address="sip:caller@example.com"))
    events = _drain(parent_conn)
    incoming = next(event for event in events if isinstance(event, IncomingCall))

    adapter.handle_command(Reject(call_id=incoming.call_id, cmd_id=15))
    assert "decline" in mock_backend.commands


# ---------------------------------------------------------------------------
# Messaging (Phase 2B.4)
# ---------------------------------------------------------------------------


def _voice_record(**overrides: Any) -> VoIPMessageRecord:
    base = dict(
        id="msg-1",
        peer_sip_address="sip:bob@example.com",
        sender_sip_address="sip:bob@example.com",
        recipient_sip_address="sip:alice@example.com",
        kind=MessageKind.TEXT,
        direction=MessageDirection.INCOMING,
        delivery_state=MessageDeliveryState.DELIVERED,
        created_at="2026-04-25T10:00:00+00:00",
        updated_at="2026-04-25T10:00:00+00:00",
        text="hi",
    )
    base.update(overrides)
    return VoIPMessageRecord(**base)  # type: ignore[arg-type]


def test_send_text_message_before_configure_returns_not_configured(
    adapter: SidecarBackendAdapter, parent_conn: Connection
) -> None:
    adapter.handle_command(
        SendTextMessage(
            uri="sip:bob@example.com", text="hi", client_id="client-msg-x", cmd_id=44
        )
    )
    events = _drain(parent_conn)
    errors = [event for event in events if isinstance(event, Error)]
    assert any(error.code == "not_configured" and error.cmd_id == 44 for error in errors), events


def test_send_text_message_invokes_backend_and_records_id_mapping(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    mock_backend.next_text_message_id = "backend-msg-7"
    adapter.handle_command(
        SendTextMessage(
            uri="sip:bob@example.com",
            text="hello",
            client_id="client-msg-7",
            cmd_id=10,
        )
    )

    assert mock_backend.commands[-1] == "text sip:bob@example.com hello"
    # No error events should have been emitted on the happy path.
    events = _drain(parent_conn, timeout=0.1)
    assert not any(isinstance(event, Error) for event in events), events
    # Mapping recorded so subsequent backend events can be re-keyed to client id.
    assert adapter._outbound_message_id_map == {"backend-msg-7": "client-msg-7"}


def test_send_text_message_when_backend_returns_falsy_emits_error(
    parent_conn: Connection, child_conn: Connection
) -> None:
    backend = MockVoIPBackend()
    backend.next_text_message_id = ""  # type: ignore[assignment]

    adapter = SidecarBackendAdapter(conn=child_conn, backend_factory=lambda _config: backend)
    try:
        adapter.handle_command(Configure(config=_config_dict()))
        adapter.handle_command(Register(cmd_id=1))
        _drain(parent_conn)

        adapter.handle_command(
            SendTextMessage(
                uri="sip:bob@example.com",
                text="hi",
                client_id="client-msg-empty",
                cmd_id=33,
            )
        )
        events = _drain(parent_conn)
        errors = [event for event in events if isinstance(event, Error)]
        assert any(
            error.code == "send_text_failed" and error.cmd_id == 33 for error in errors
        ), events
        assert adapter._outbound_message_id_map == {}
    finally:
        adapter.shutdown()


def test_send_text_message_when_backend_raises_emits_error(
    parent_conn: Connection, child_conn: Connection
) -> None:
    class _RaisingBackend(MockVoIPBackend):
        def send_text_message(self, sip_address: str, text: str) -> str | None:  # type: ignore[override]
            raise RuntimeError("simulated send failure")

    backend = _RaisingBackend()
    adapter = SidecarBackendAdapter(conn=child_conn, backend_factory=lambda _config: backend)
    try:
        adapter.handle_command(Configure(config=_config_dict()))
        adapter.handle_command(Register(cmd_id=1))
        _drain(parent_conn)

        adapter.handle_command(
            SendTextMessage(
                uri="sip:bob@example.com",
                text="hi",
                client_id="client-msg-boom",
                cmd_id=34,
            )
        )
        events = _drain(parent_conn)
        errors = [event for event in events if isinstance(event, Error)]
        assert any(
            error.code == "send_text_failed"
            and error.cmd_id == 34
            and "simulated send failure" in error.message
            for error in errors
        ), events
        assert adapter._outbound_message_id_map == {}
    finally:
        adapter.shutdown()


def test_backend_message_received_forwards_with_flat_fields(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    _drain(parent_conn)

    record = _voice_record(
        id="inbound-1",
        kind=MessageKind.VOICE_NOTE,
        local_file_path="/tmp/voice.opus",
        mime_type="audio/opus",
        duration_ms=4200,
        unread=True,
        text="",
    )
    mock_backend.emit(BackendMessageReceived(message=record))
    events = _drain(parent_conn)
    matches = [event for event in events if isinstance(event, MessageReceived)]
    assert matches, events
    forwarded = matches[-1]
    assert forwarded.message_id == "inbound-1"
    assert forwarded.kind == MessageKind.VOICE_NOTE.value
    assert forwarded.direction == MessageDirection.INCOMING.value
    assert forwarded.delivery_state == MessageDeliveryState.DELIVERED.value
    assert forwarded.local_file_path == "/tmp/voice.opus"
    assert forwarded.mime_type == "audio/opus"
    assert forwarded.duration_ms == 4200
    assert forwarded.unread is True


def test_backend_message_delivery_changed_translates_outbound_id_and_drops_on_terminal(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    mock_backend.next_text_message_id = "backend-msg-A"
    adapter.handle_command(
        SendTextMessage(
            uri="sip:bob@example.com",
            text="hi",
            client_id="client-msg-A",
            cmd_id=20,
        )
    )
    _drain(parent_conn, timeout=0.1)
    assert adapter._outbound_message_id_map == {"backend-msg-A": "client-msg-A"}

    # Non-terminal delivery state — mapping retained, id translated.
    mock_backend.emit(
        BackendMessageDeliveryChanged(
            message_id="backend-msg-A",
            delivery_state=MessageDeliveryState.SENT,
        )
    )
    events = _drain(parent_conn)
    matches = [event for event in events if isinstance(event, MessageDeliveryChanged)]
    assert matches and matches[-1].message_id == "client-msg-A"
    assert matches[-1].delivery_state == MessageDeliveryState.SENT.value
    assert adapter._outbound_message_id_map == {"backend-msg-A": "client-msg-A"}

    # Terminal delivery state drops the mapping so the dict does not grow unboundedly.
    mock_backend.emit(
        BackendMessageDeliveryChanged(
            message_id="backend-msg-A",
            delivery_state=MessageDeliveryState.DELIVERED,
        )
    )
    events = _drain(parent_conn)
    matches = [event for event in events if isinstance(event, MessageDeliveryChanged)]
    assert matches[-1].message_id == "client-msg-A"
    assert matches[-1].delivery_state == MessageDeliveryState.DELIVERED.value
    assert adapter._outbound_message_id_map == {}


def test_backend_message_delivery_failed_drops_mapping(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    mock_backend.next_text_message_id = "backend-msg-fail"
    adapter.handle_command(
        SendTextMessage(
            uri="sip:bob@example.com",
            text="hi",
            client_id="client-msg-fail",
            cmd_id=21,
        )
    )
    _drain(parent_conn, timeout=0.1)

    mock_backend.emit(
        BackendMessageDeliveryChanged(
            message_id="backend-msg-fail",
            delivery_state=MessageDeliveryState.FAILED,
            error="peer offline",
        )
    )
    events = _drain(parent_conn)
    matches = [event for event in events if isinstance(event, MessageDeliveryChanged)]
    assert matches and matches[-1].message_id == "client-msg-fail"
    assert matches[-1].error == "peer offline"
    assert adapter._outbound_message_id_map == {}


def test_backend_message_delivery_changed_passes_inbound_id_unchanged(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    """Inbound (non-tracked) ids forward as-is — only outbound ids get re-keyed."""

    adapter.handle_command(Configure(config=_config_dict()))
    _drain(parent_conn)

    mock_backend.emit(
        BackendMessageDeliveryChanged(
            message_id="inbound-msg-9",
            delivery_state=MessageDeliveryState.DELIVERED,
        )
    )
    events = _drain(parent_conn)
    matches = [event for event in events if isinstance(event, MessageDeliveryChanged)]
    assert matches and matches[-1].message_id == "inbound-msg-9"
    # No mapping was ever recorded for the inbound id.
    assert adapter._outbound_message_id_map == {}


def test_backend_message_download_completed_forwards_without_dropping_mapping(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    """Download completion is not terminal for the outbound mapping."""

    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    mock_backend.next_text_message_id = "backend-msg-D"
    adapter.handle_command(
        SendTextMessage(
            uri="sip:bob@example.com",
            text="hi",
            client_id="client-msg-D",
            cmd_id=30,
        )
    )
    _drain(parent_conn, timeout=0.1)

    mock_backend.emit(
        BackendMessageDownloadCompleted(
            message_id="backend-msg-D",
            local_file_path="/tmp/asset.opus",
            mime_type="audio/opus",
        )
    )
    events = _drain(parent_conn)
    matches = [event for event in events if isinstance(event, MessageDownloadCompleted)]
    assert matches and matches[-1].message_id == "client-msg-D"
    assert matches[-1].local_file_path == "/tmp/asset.opus"
    assert matches[-1].mime_type == "audio/opus"
    # Download completion is not terminal — mapping should still be live.
    assert adapter._outbound_message_id_map == {"backend-msg-D": "client-msg-D"}


def test_backend_message_failed_forwards_and_drops_mapping(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    mock_backend.next_text_message_id = "backend-msg-F"
    adapter.handle_command(
        SendTextMessage(
            uri="sip:bob@example.com",
            text="hi",
            client_id="client-msg-F",
            cmd_id=40,
        )
    )
    _drain(parent_conn, timeout=0.1)

    mock_backend.emit(
        BackendMessageFailed(message_id="backend-msg-F", reason="timeout")
    )
    events = _drain(parent_conn)
    matches = [event for event in events if isinstance(event, MessageFailed)]
    assert matches and matches[-1].message_id == "client-msg-F"
    assert matches[-1].reason == "timeout"
    assert adapter._outbound_message_id_map == {}


# ---------------------------------------------------------------------------
# Voice notes (Phase 2B.4b)
# ---------------------------------------------------------------------------


def test_start_voice_note_recording_invokes_backend(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    adapter.handle_command(
        StartVoiceNoteRecording(file_path="/tmp/voice-1.wav", cmd_id=50)
    )
    assert mock_backend.recording_active is True
    assert mock_backend.recording_path == "/tmp/voice-1.wav"
    events = _drain(parent_conn, timeout=0.1)
    assert not any(isinstance(event, Error) for event in events), events


def test_start_voice_note_recording_before_configure_returns_not_configured(
    adapter: SidecarBackendAdapter, parent_conn: Connection
) -> None:
    adapter.handle_command(
        StartVoiceNoteRecording(file_path="/tmp/voice-1.wav", cmd_id=51)
    )
    events = _drain(parent_conn)
    errors = [event for event in events if isinstance(event, Error)]
    assert any(error.code == "not_configured" and error.cmd_id == 51 for error in errors), events


def test_start_voice_note_recording_when_backend_returns_false_emits_error(
    parent_conn: Connection, child_conn: Connection
) -> None:
    class _RecordRefusingBackend(MockVoIPBackend):
        def start_voice_note_recording(self, file_path: str) -> bool:  # type: ignore[override]
            return False

    backend = _RecordRefusingBackend()
    adapter = SidecarBackendAdapter(conn=child_conn, backend_factory=lambda _config: backend)
    try:
        adapter.handle_command(Configure(config=_config_dict()))
        _drain(parent_conn)
        adapter.handle_command(
            StartVoiceNoteRecording(file_path="/tmp/voice-1.wav", cmd_id=52)
        )
        events = _drain(parent_conn)
        errors = [event for event in events if isinstance(event, Error)]
        assert any(
            error.code == "start_voice_note_failed" and error.cmd_id == 52 for error in errors
        ), events
    finally:
        adapter.shutdown()


def test_start_voice_note_recording_when_backend_raises_emits_error(
    parent_conn: Connection, child_conn: Connection
) -> None:
    class _RaisingBackend(MockVoIPBackend):
        def start_voice_note_recording(self, file_path: str) -> bool:  # type: ignore[override]
            raise RuntimeError("alsa busy")

    backend = _RaisingBackend()
    adapter = SidecarBackendAdapter(conn=child_conn, backend_factory=lambda _config: backend)
    try:
        adapter.handle_command(Configure(config=_config_dict()))
        _drain(parent_conn)
        adapter.handle_command(
            StartVoiceNoteRecording(file_path="/tmp/voice-1.wav", cmd_id=53)
        )
        events = _drain(parent_conn)
        errors = [event for event in events if isinstance(event, Error)]
        assert any(
            error.code == "start_voice_note_failed"
            and error.cmd_id == 53
            and "alsa busy" in error.message
            for error in errors
        ), events
    finally:
        adapter.shutdown()


def test_stop_voice_note_recording_invokes_backend(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    adapter.handle_command(
        StartVoiceNoteRecording(file_path="/tmp/voice-1.wav", cmd_id=60)
    )
    _drain(parent_conn, timeout=0.1)

    adapter.handle_command(StopVoiceNoteRecording(cmd_id=61))
    assert "record-stop" in mock_backend.commands
    assert mock_backend.recording_active is False
    events = _drain(parent_conn, timeout=0.1)
    assert not any(isinstance(event, Error) for event in events), events


def test_stop_voice_note_recording_when_backend_raises_emits_error(
    parent_conn: Connection, child_conn: Connection
) -> None:
    class _RaisingStopBackend(MockVoIPBackend):
        def stop_voice_note_recording(self) -> int | None:  # type: ignore[override]
            raise RuntimeError("file finalize failed")

    backend = _RaisingStopBackend()
    adapter = SidecarBackendAdapter(conn=child_conn, backend_factory=lambda _config: backend)
    try:
        adapter.handle_command(Configure(config=_config_dict()))
        _drain(parent_conn)

        adapter.handle_command(StopVoiceNoteRecording(cmd_id=62))
        events = _drain(parent_conn)
        errors = [event for event in events if isinstance(event, Error)]
        assert any(
            error.code == "stop_voice_note_failed"
            and error.cmd_id == 62
            and "file finalize failed" in error.message
            for error in errors
        ), events
    finally:
        adapter.shutdown()


def test_cancel_voice_note_recording_invokes_backend(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    adapter.handle_command(
        StartVoiceNoteRecording(file_path="/tmp/voice-1.wav", cmd_id=70)
    )
    _drain(parent_conn, timeout=0.1)
    adapter.handle_command(CancelVoiceNoteRecording(cmd_id=71))
    assert "record-cancel" in mock_backend.commands
    assert mock_backend.recording_active is False
    events = _drain(parent_conn, timeout=0.1)
    assert not any(isinstance(event, Error) for event in events), events


def test_cancel_voice_note_recording_when_backend_returns_false_emits_error(
    parent_conn: Connection, child_conn: Connection
) -> None:
    class _CancelRefusingBackend(MockVoIPBackend):
        def cancel_voice_note_recording(self) -> bool:  # type: ignore[override]
            return False

    backend = _CancelRefusingBackend()
    adapter = SidecarBackendAdapter(conn=child_conn, backend_factory=lambda _config: backend)
    try:
        adapter.handle_command(Configure(config=_config_dict()))
        _drain(parent_conn)

        adapter.handle_command(CancelVoiceNoteRecording(cmd_id=72))
        events = _drain(parent_conn)
        errors = [event for event in events if isinstance(event, Error)]
        assert any(
            error.code == "cancel_voice_note_failed" and error.cmd_id == 72 for error in errors
        ), events
    finally:
        adapter.shutdown()


def test_send_voice_note_records_id_mapping(
    adapter: SidecarBackendAdapter,
    parent_conn: Connection,
    mock_backend: MockVoIPBackend,
) -> None:
    adapter.handle_command(Configure(config=_config_dict()))
    adapter.handle_command(Register(cmd_id=1))
    _drain(parent_conn)

    mock_backend.next_voice_note_id = "backend-vn-7"
    adapter.handle_command(
        SendVoiceNote(
            uri="sip:bob@example.com",
            file_path="/tmp/voice-7.wav",
            duration_ms=4200,
            mime_type="audio/wav",
            client_id="client-msg-vn-7",
            cmd_id=80,
        )
    )

    assert any(
        cmd.startswith("voice-note sip:bob@example.com voice-7.wav 4200 audio/wav")
        for cmd in mock_backend.commands
    ), mock_backend.commands
    events = _drain(parent_conn, timeout=0.1)
    assert not any(isinstance(event, Error) for event in events), events
    assert adapter._outbound_message_id_map == {"backend-vn-7": "client-msg-vn-7"}


def test_send_voice_note_when_backend_returns_no_id_emits_error(
    parent_conn: Connection, child_conn: Connection
) -> None:
    class _NoIdBackend(MockVoIPBackend):
        def send_voice_note(self, *args: Any, **kwargs: Any) -> str | None:  # type: ignore[override]
            return None

    backend = _NoIdBackend()
    adapter = SidecarBackendAdapter(conn=child_conn, backend_factory=lambda _config: backend)
    try:
        adapter.handle_command(Configure(config=_config_dict()))
        _drain(parent_conn)

        adapter.handle_command(
            SendVoiceNote(
                uri="sip:bob@example.com",
                file_path="/tmp/voice.wav",
                duration_ms=3000,
                mime_type="audio/wav",
                client_id="client-msg-noid",
                cmd_id=81,
            )
        )
        events = _drain(parent_conn)
        errors = [event for event in events if isinstance(event, Error)]
        assert any(
            error.code == "send_voice_note_failed" and error.cmd_id == 81 for error in errors
        ), events
        assert adapter._outbound_message_id_map == {}
    finally:
        adapter.shutdown()


def test_send_voice_note_when_backend_raises_emits_error(
    parent_conn: Connection, child_conn: Connection
) -> None:
    class _RaisingSendBackend(MockVoIPBackend):
        def send_voice_note(self, *args: Any, **kwargs: Any) -> str | None:  # type: ignore[override]
            raise RuntimeError("file transfer rejected")

    backend = _RaisingSendBackend()
    adapter = SidecarBackendAdapter(conn=child_conn, backend_factory=lambda _config: backend)
    try:
        adapter.handle_command(Configure(config=_config_dict()))
        _drain(parent_conn)

        adapter.handle_command(
            SendVoiceNote(
                uri="sip:bob@example.com",
                file_path="/tmp/voice.wav",
                duration_ms=3000,
                mime_type="audio/wav",
                client_id="client-msg-raise",
                cmd_id=82,
            )
        )
        events = _drain(parent_conn)
        errors = [event for event in events if isinstance(event, Error)]
        assert any(
            error.code == "send_voice_note_failed"
            and error.cmd_id == 82
            and "file transfer rejected" in error.message
            for error in errors
        ), events
        assert adapter._outbound_message_id_map == {}
    finally:
        adapter.shutdown()
