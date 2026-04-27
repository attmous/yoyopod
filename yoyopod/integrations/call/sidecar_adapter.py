"""Translate protocol commands to ``VoIPBackend`` calls and back.

The adapter is owned by the sidecar process. It receives decoded protocol
commands from :func:`yoyopod.integrations.call.sidecar_main.run_sidecar`
and dispatches them to the backend, runs the iterate loop on a dedicated
thread, and emits backend events as protocol events through the pipe.

Pipe writes happen from two threads — the command-handling thread when
sending acks/errors, and the iterate thread when forwarding backend events.
:class:`SidecarBackendAdapter` serializes pipe writes through ``_send_lock``
so frames never interleave.

The :class:`yoyopod.backends.voip.protocol.VoIPBackend` API is implicitly
single-call (no ``call_id`` parameters). The sidecar mints a ``call_id``
the first time it sees an :class:`IncomingCallDetected` or after
:class:`Dial` succeeds; it tracks that id until the call releases. When
main sends :class:`Accept`/:class:`Hangup`/:class:`SetMute` with a
``call_id``, the adapter validates it matches the current call before
calling the backend.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from multiprocessing.connection import Connection
from typing import Any

from loguru import logger

from yoyopod.backends.voip.protocol import VoIPBackend
from yoyopod.integrations.call.models import (
    BackendStopped,
    CallState,
    CallStateChanged as BackendCallStateChanged,
    IncomingCallDetected,
    RegistrationState,
    RegistrationStateChanged as BackendRegistrationStateChanged,
    VoIPConfig,
    VoIPEvent,
)
from yoyopod.integrations.call.sidecar_protocol import (
    Accept,
    CallStateChanged,
    Configure,
    Dial,
    Error,
    Hangup,
    IncomingCall,
    Log,
    MediaStateChanged,
    Ping,
    Pong,
    Register,
    RegistrationStateChanged,
    Reject,
    SetMute,
    SetVolume,
    Unregister,
    send_message,
)

BackendFactory = Callable[[VoIPConfig], VoIPBackend]


class SidecarBackendAdapter:
    """Stateful adapter between the wire protocol and a ``VoIPBackend`` instance."""

    _ITERATE_INTERVAL_FALLBACK_SECONDS = 0.02
    _ITERATE_JOIN_TIMEOUT_SECONDS = 1.0

    def __init__(
        self,
        *,
        conn: Connection,
        backend_factory: BackendFactory,
    ) -> None:
        self._conn = conn
        self._backend_factory = backend_factory
        self._backend: VoIPBackend | None = None
        self._send_lock = threading.Lock()
        self._iterate_thread: threading.Thread | None = None
        self._iterate_stop = threading.Event()
        self._iterate_interval_seconds = self._ITERATE_INTERVAL_FALLBACK_SECONDS

        self._call_lock = threading.Lock()
        self._next_call_id = 0
        self._current_call_id: str | None = None
        self._is_muted = False
        self._speaker_volume = 1.0

    # ------------------------------------------------------------------
    # Public command dispatch
    # ------------------------------------------------------------------

    def handle_command(self, command: Any) -> None:
        """Dispatch one decoded command to the appropriate backend operation."""

        if isinstance(command, Ping):
            self._safe_send(Pong(cmd_id=command.cmd_id))
            return

        if isinstance(command, Configure):
            self._handle_configure(command)
            return

        if isinstance(command, Register):
            self._handle_register(command)
            return

        if isinstance(command, Unregister):
            self._handle_unregister(command)
            return

        if isinstance(command, Dial):
            self._handle_dial(command)
            return

        if isinstance(command, Accept):
            self._handle_accept(command)
            return

        if isinstance(command, Reject):
            self._handle_reject(command)
            return

        if isinstance(command, Hangup):
            self._handle_hangup(command)
            return

        if isinstance(command, SetMute):
            self._handle_set_mute(command)
            return

        if isinstance(command, SetVolume):
            self._handle_set_volume(command)
            return

        self._safe_send(
            Log(
                level="WARNING",
                message=f"sidecar adapter: ignored unknown command {type(command).__name__}",
            )
        )

    def shutdown(self) -> None:
        """Tear down the iterate thread and stop the backend, if any."""

        self._stop_iterate_thread()
        backend = self._backend
        self._backend = None
        # Always stop the backend if one exists. ``backend.running`` is not a
        # reliable cleanup signal: ``LiblinphoneBackend`` flips ``running``
        # to False when ``iterate()`` raises, but the native core, transports,
        # and audio device claims still need ``stop()``/``shutdown()`` to
        # release them. Skipping the call would leak native state into the
        # next backend created by a follow-up Configure.
        if backend is not None:
            try:
                backend.stop()
            except Exception:
                logger.exception("Sidecar adapter: backend.stop() raised during shutdown")

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _handle_configure(self, command: Configure) -> None:
        try:
            config = VoIPConfig(**command.config)
        except TypeError as exc:
            self._safe_send(
                Error(
                    code="invalid_config",
                    message=f"VoIPConfig construction failed: {exc}",
                    cmd_id=command.cmd_id,
                )
            )
            return

        # Replace any prior backend cleanly. ``shutdown()`` joins the iterate
        # thread and stops the old backend, but it does not clear tracked
        # call state — a Configure issued during an active call would leave
        # the adapter believing the call is still in progress and reject
        # subsequent Dials with ``call_in_progress``. Reset explicitly so
        # backend replacement is truly idempotent (matches the behaviour
        # added to ``_handle_unregister``).
        self.shutdown()
        self._reset_call_state()
        try:
            backend = self._backend_factory(config)
        except Exception as exc:
            self._safe_send(
                Error(
                    code="backend_factory_failed",
                    message=f"backend factory raised: {exc}",
                    cmd_id=command.cmd_id,
                )
            )
            return

        backend.on_event(self._on_backend_event)
        self._backend = backend
        self._iterate_interval_seconds = max(0.001, float(config.iterate_interval_ms) / 1000.0)
        self._safe_send(
            Log(
                level="INFO",
                message=f"sidecar adapter: configured backend for {config.sip_server!r}",
            )
        )

    def _handle_register(self, command: Register) -> None:
        backend = self._require_backend(command.cmd_id)
        if backend is None:
            return

        # The iterate thread from a prior backend may still be alive — e.g.
        # ``_stop_iterate_thread`` retained the handle when its join timed
        # out (round-1 fix). ``_start_iterate_thread`` silently short-circuits
        # in that case to avoid racing two iterate threads against the same
        # backend, but that means a fresh backend would have no iterate
        # driver and the SIP keep-alives / event drains would not flow even
        # though Register reported success. Surface the situation as a
        # caller-visible error instead of starting the backend in a
        # half-broken state. ``main`` can retry once the stale thread exits.
        if self._iterate_thread is not None and self._iterate_thread.is_alive():
            self._safe_send(
                Error(
                    code="iterate_thread_busy",
                    message=(
                        "cannot register: previous iterate thread is still alive; "
                        "retry once it exits"
                    ),
                    cmd_id=command.cmd_id,
                )
            )
            return

        try:
            started = backend.start()
        except Exception as exc:
            self._safe_send(
                Error(
                    code="register_failed",
                    message=f"backend.start() raised: {exc}",
                    cmd_id=command.cmd_id,
                )
            )
            return

        if not started:
            self._safe_send(
                Error(
                    code="register_failed",
                    message="backend.start() returned False",
                    cmd_id=command.cmd_id,
                )
            )
            return

        self._start_iterate_thread()

    def _handle_unregister(self, command: Unregister) -> None:
        backend = self._backend
        if backend is None:
            self._safe_send(
                Error(
                    code="not_configured",
                    message="cannot unregister; no backend configured",
                    cmd_id=command.cmd_id,
                )
            )
            return

        self._stop_iterate_thread()
        try:
            backend.stop()
        except Exception as exc:
            self._safe_send(
                Error(
                    code="unregister_failed",
                    message=f"backend.stop() raised: {exc}",
                    cmd_id=command.cmd_id,
                )
            )
        # Stopping the iterate loop happens before backend.stop(), so any
        # terminal call-state event the backend would have emitted on
        # teardown is no longer guaranteed to flow through. Reset the
        # tracked call id explicitly so a follow-up Configure/Register/Dial
        # cycle is not stuck on a stale ``call_in_progress``.
        self._reset_call_state()

    def _handle_dial(self, command: Dial) -> None:
        backend = self._require_backend(command.cmd_id)
        if backend is None:
            return
        with self._call_lock:
            if self._current_call_id is not None:
                self._safe_send(
                    Error(
                        code="call_in_progress",
                        message=f"refusing to dial; current call {self._current_call_id!r}",
                        cmd_id=command.cmd_id,
                    )
                )
                return
            call_id = self._mint_call_id_locked()

        try:
            success = backend.make_call(command.uri)
        except Exception as exc:
            self._clear_call_id(call_id)
            self._safe_send(
                Error(
                    code="dial_failed",
                    message=f"backend.make_call raised: {exc}",
                    cmd_id=command.cmd_id,
                )
            )
            return

        if not success:
            self._clear_call_id(call_id)
            self._safe_send(
                Error(
                    code="dial_failed",
                    message="backend.make_call returned False",
                    cmd_id=command.cmd_id,
                )
            )

    def _handle_accept(self, command: Accept) -> None:
        backend = self._require_backend(command.cmd_id)
        if backend is None:
            return
        if not self._verify_call_id(command.call_id, command.cmd_id):
            return
        self._invoke_simple_action(
            backend.answer_call,
            cmd_id=command.cmd_id,
            failure_code="accept_failed",
            label="answer_call",
        )

    def _handle_reject(self, command: Reject) -> None:
        backend = self._require_backend(command.cmd_id)
        if backend is None:
            return
        if not self._verify_call_id(command.call_id, command.cmd_id):
            return
        self._invoke_simple_action(
            backend.reject_call,
            cmd_id=command.cmd_id,
            failure_code="reject_failed",
            label="reject_call",
        )

    def _handle_hangup(self, command: Hangup) -> None:
        backend = self._require_backend(command.cmd_id)
        if backend is None:
            return
        if not self._verify_call_id(command.call_id, command.cmd_id):
            return
        self._invoke_simple_action(
            backend.hangup,
            cmd_id=command.cmd_id,
            failure_code="hangup_failed",
            label="hangup",
        )

    def _handle_set_mute(self, command: SetMute) -> None:
        backend = self._require_backend(command.cmd_id)
        if backend is None:
            return
        if not self._verify_call_id(command.call_id, command.cmd_id):
            return
        try:
            success = backend.mute() if command.on else backend.unmute()
        except Exception as exc:
            self._safe_send(
                Error(
                    code="mute_failed",
                    message=f"backend mute/unmute raised: {exc}",
                    cmd_id=command.cmd_id,
                )
            )
            return
        if not success:
            self._safe_send(
                Error(
                    code="mute_failed",
                    message="backend mute/unmute returned False",
                    cmd_id=command.cmd_id,
                )
            )
            return
        self._is_muted = bool(command.on)
        self._emit_media_state_locked()

    def _handle_set_volume(self, command: SetVolume) -> None:
        # The current ``VoIPBackend`` protocol has no volume control; track
        # the requested value and surface it via :class:`MediaStateChanged`
        # so the main process keeps an accurate view of intended state.
        # Validate the call id like the other call-scoped commands so a
        # delayed SetVolume from a previous call cannot mutate the current
        # call's media state. ``_require_backend`` and ``_verify_call_id``
        # both emit Error events on rejection.
        if self._require_backend(command.cmd_id) is None:
            return
        if not self._verify_call_id(command.call_id, command.cmd_id):
            return
        self._speaker_volume = max(0.0, min(1.0, float(command.level)))
        self._emit_media_state_locked()

    # ------------------------------------------------------------------
    # Backend event translation
    # ------------------------------------------------------------------

    def _on_backend_event(self, event: VoIPEvent) -> None:
        """Translate one backend event to a protocol event and send it."""

        try:
            if isinstance(event, BackendRegistrationStateChanged):
                self._safe_send(
                    RegistrationStateChanged(
                        state=_registration_state_value(event.state), reason=None
                    )
                )
                return

            if isinstance(event, IncomingCallDetected):
                with self._call_lock:
                    if self._current_call_id is None:
                        call_id = self._mint_call_id_locked()
                    else:
                        call_id = self._current_call_id
                self._safe_send(
                    IncomingCall(
                        call_id=call_id,
                        from_uri=event.caller_address,
                        from_display=None,
                    )
                )
                return

            if isinstance(event, BackendCallStateChanged):
                call_id = self._current_call_id
                state_value = _call_state_value(event.state)
                if call_id is not None:
                    self._safe_send(CallStateChanged(call_id=call_id, state=state_value))
                if event.state in _CALL_TERMINAL_STATES:
                    self._reset_call_state()
                return

            if isinstance(event, BackendStopped):
                # Treat as terminal for any in-flight call: the backend has
                # gone down (typically because ``iterate()`` failed and the
                # native shim is gone), so the tracked ``_current_call_id``
                # would otherwise block future ``Dial`` commands with
                # ``call_in_progress`` even after a recovery Configure.
                self._reset_call_state()
                self._safe_send(
                    Error(
                        code="backend_stopped",
                        message=event.reason or "backend stopped",
                    )
                )
                return

            # Messaging and voice-note events are out of scope for Phase 2B.2;
            # forward them as a debug log so callers can see them in flight.
            self._safe_send(
                Log(
                    level="DEBUG",
                    message=f"sidecar adapter: forwarded {type(event).__name__}",
                )
            )
        except Exception:
            logger.exception(
                "Sidecar adapter: failed to translate backend event {}",
                type(event).__name__,
            )

    # ------------------------------------------------------------------
    # Iterate thread
    # ------------------------------------------------------------------

    def _start_iterate_thread(self) -> None:
        if self._iterate_thread is not None and self._iterate_thread.is_alive():
            return
        self._iterate_stop.clear()
        thread = threading.Thread(
            target=self._run_iterate_loop,
            daemon=True,
            name="voip-sidecar-iterate",
        )
        self._iterate_thread = thread
        thread.start()

    def _stop_iterate_thread(self) -> None:
        thread = self._iterate_thread
        if thread is None:
            return
        self._iterate_stop.set()
        thread.join(timeout=self._ITERATE_JOIN_TIMEOUT_SECONDS)
        if thread.is_alive():
            # Keep the handle so we never let a fresh start spawn a second
            # iterate thread alongside the one that is still alive: two
            # threads racing ``backend.iterate()`` would corrupt liblinphone
            # state and double up on event emission. ``_start_iterate_thread``
            # checks ``is_alive()`` and returns without spawning if the old
            # thread is still here.
            logger.warning(
                "Sidecar adapter: iterate thread did not exit within join timeout; "
                "retaining handle so a restart cannot race a second iterate thread"
            )
            return
        self._iterate_thread = None

    def _run_iterate_loop(self) -> None:
        backend = self._backend
        if backend is None:
            return
        while not self._iterate_stop.is_set():
            try:
                if backend.running:
                    backend.iterate()
            except Exception:
                logger.exception("Sidecar adapter: backend.iterate raised; continuing")
            self._iterate_stop.wait(timeout=self._iterate_interval_seconds)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _require_backend(self, cmd_id: int | None) -> VoIPBackend | None:
        backend = self._backend
        if backend is None:
            self._safe_send(
                Error(
                    code="not_configured",
                    message="sidecar received command before Configure",
                    cmd_id=cmd_id,
                )
            )
        return backend

    def _verify_call_id(self, call_id: str, cmd_id: int | None) -> bool:
        with self._call_lock:
            current = self._current_call_id
        if current != call_id:
            self._safe_send(
                Error(
                    code="unknown_call_id",
                    message=f"command targets {call_id!r} but current call is {current!r}",
                    cmd_id=cmd_id,
                )
            )
            return False
        return True

    def _invoke_simple_action(
        self,
        action: Callable[[], bool],
        *,
        cmd_id: int | None,
        failure_code: str,
        label: str,
    ) -> None:
        try:
            success = action()
        except Exception as exc:
            self._safe_send(
                Error(
                    code=failure_code,
                    message=f"backend.{label} raised: {exc}",
                    cmd_id=cmd_id,
                )
            )
            return
        if not success:
            self._safe_send(
                Error(
                    code=failure_code,
                    message=f"backend.{label} returned False",
                    cmd_id=cmd_id,
                )
            )

    def _mint_call_id_locked(self) -> str:
        """Caller must hold ``self._call_lock``."""

        self._next_call_id += 1
        call_id = f"call-{self._next_call_id}"
        self._current_call_id = call_id
        self._is_muted = False
        self._speaker_volume = 1.0
        return call_id

    def _clear_call_id(self, call_id: str) -> None:
        with self._call_lock:
            if self._current_call_id == call_id:
                self._current_call_id = None
                self._is_muted = False
                self._speaker_volume = 1.0

    def _reset_call_state(self) -> None:
        with self._call_lock:
            self._current_call_id = None
            self._is_muted = False
            self._speaker_volume = 1.0

    def _emit_media_state_locked(self) -> None:
        with self._call_lock:
            call_id = self._current_call_id
            mic_muted = self._is_muted
            volume = self._speaker_volume
        if call_id is None:
            return
        self._safe_send(
            MediaStateChanged(call_id=call_id, mic_muted=mic_muted, speaker_volume=volume)
        )

    def _safe_send(self, message: Any) -> None:
        with self._send_lock:
            try:
                send_message(self._conn, message)
            except (BrokenPipeError, EOFError, OSError):
                pass

    # ------------------------------------------------------------------
    # Test seams
    # ------------------------------------------------------------------

    def _wait_for_iterate_thread_to_exit(self, *, timeout: float = 1.0) -> bool:
        """Block until the iterate thread has exited. Returns True on success."""

        thread = self._iterate_thread
        if thread is None:
            return True
        deadline = time.monotonic() + timeout
        while thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.005)
        return not thread.is_alive()


_CALL_TERMINAL_STATES = frozenset(
    {
        CallState.RELEASED,
        CallState.END,
        CallState.ERROR,
        CallState.IDLE,
    }
)
"""Liblinphone emits a native terminal that maps to ``CallState.END`` (state 13;
see :file:`yoyopod/backends/voip/liblinphone.py`). Treat it as terminal here
so a hangup that lands as END (with no later RELEASED) still clears the
tracked ``_current_call_id`` instead of blocking subsequent Dials with
``call_in_progress``. Mirrors the existing ``_TERMINAL_STATES`` set in
:mod:`yoyopod.integrations.call.handlers`."""


def _registration_state_value(state: RegistrationState) -> str:
    return state.value if isinstance(state, RegistrationState) else str(state)


def _call_state_value(state: CallState) -> str:
    return state.value if isinstance(state, CallState) else str(state)
