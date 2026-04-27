"""VoIPBackend implementation that delegates to a sidecar process.

Production wires this backend up when ``YOYOPOD_VOIP_SIDECAR=1`` is set.
The :class:`SidecarSupervisor` owns the sidecar process; this backend
adapts the synchronous :class:`yoyopod.backends.voip.protocol.VoIPBackend`
surface that :class:`VoIPManager` already consumes onto the asynchronous
command/event protocol the sidecar speaks.

Translation responsibilities:

* :meth:`start` / :meth:`stop` drive ``supervisor.start()`` /
  ``supervisor.stop()`` and send ``Configure`` / ``Register`` /
  ``Unregister`` commands at the right moments.
* Per-call methods (:meth:`make_call`, :meth:`answer_call`,
  :meth:`hangup`, :meth:`mute`, :meth:`unmute`, ...) translate to
  ``Dial`` / ``Accept`` / ``Reject`` / ``Hangup`` / ``SetMute`` commands.
* Backend events emitted by the sidecar are translated back to
  :class:`yoyopod.integrations.call.models.VoIPEvent` instances and fired
  to the callbacks registered via :meth:`on_event` so callers do not
  need to know whether the backend is in-process or sidecar-backed.

Phase 2B.4 wired text messaging. Phase 2B.4b adds voice-note recording
and sending. :meth:`stop_voice_note_recording` returns an optimistic
duration computed from main's monotonic clock (start-to-stop elapsed)
so the existing synchronous :class:`VoIPBackend` contract is preserved
without a blocking pipe round-trip; the sidecar's actual file duration
arrives later in the corresponding :class:`MessageReceived` event and
the manager can reconcile it into the persisted record.
"""

from __future__ import annotations

import dataclasses
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

from loguru import logger

from yoyopod.backends.voip.protocol import VoIPIterateMetrics
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
    VoIPEvent,
    VoIPMessageRecord,
)
from yoyopod.integrations.call.sidecar_protocol import (
    Accept,
    CallStateChanged as ProtocolCallStateChanged,
    CancelVoiceNoteRecording,
    Configure,
    Dial,
    Error as ProtocolError,
    Hangup,
    Hello,
    IncomingCall,
    Log as ProtocolLog,
    MediaStateChanged,
    MessageDeliveryChanged as ProtocolMessageDeliveryChanged,
    MessageDownloadCompleted as ProtocolMessageDownloadCompleted,
    MessageFailed as ProtocolMessageFailed,
    MessageReceived as ProtocolMessageReceived,
    Pong,
    Ready,
    Register,
    RegistrationStateChanged as ProtocolRegistrationStateChanged,
    Reject,
    SendTextMessage,
    SendVoiceNote,
    SetMute,
    StartVoiceNoteRecording,
    StopVoiceNoteRecording,
    Unregister,
)
from yoyopod.integrations.call.sidecar_supervisor import SidecarSupervisor


# States that mean the call has fully ended and the tracked id should be cleared.
_TERMINAL_CALL_STATES = frozenset(
    {
        CallState.RELEASED,
        CallState.END,
        CallState.ERROR,
        CallState.IDLE,
    }
)


# Liblinphone log levels arrive as strings; map to loguru levels.
_LOG_LEVEL_MAP = {
    "DEBUG": "DEBUG",
    "INFO": "INFO",
    "WARNING": "WARNING",
    "ERROR": "ERROR",
    "CRITICAL": "CRITICAL",
}


# Sidecar error codes emitted by ``SidecarBackendAdapter`` that mean the
# active call is finished or the attempted dial was refused. Surfacing
# them as ``BackendCallStateChanged(ERROR)`` lets the existing
# ``VoIPManager`` state machine retreat to idle instead of leaving the UI
# stuck in "dialing" / "connecting" after an optimistic make_call.
_CALL_FATAL_ERROR_CODES = frozenset(
    {
        "dial_failed",
        "call_in_progress",
        "accept_failed",
        "reject_failed",
        "hangup_failed",
        "mute_failed",
        "unknown_call_id",
    }
)


# Sidecar error codes that mean SIP registration cannot proceed. Translate
# to ``BackendRegistrationStateChanged(FAILED)`` so the manager can
# surface a "registration failed" status to the UI.
_REGISTRATION_FATAL_ERROR_CODES = frozenset({"register_failed"})


class SupervisorBackedBackend:
    """``VoIPBackend`` adapter on top of a :class:`SidecarSupervisor`."""

    def __init__(
        self,
        config: VoIPConfig,
        *,
        supervisor: SidecarSupervisor | None = None,
    ) -> None:
        self.config = config
        self.running = False
        self.event_callbacks: list[Callable[[VoIPEvent], None]] = []

        self._supervisor = supervisor or SidecarSupervisor(
            on_event=self._on_protocol_event,
            on_ready=self._on_supervisor_ready,
        )
        # If the caller passed in a pre-built supervisor, rewire its event
        # and ready handlers to ours so events from the sidecar reach this
        # backend (including ``Ready`` callbacks fired after every restart).
        if supervisor is not None:
            self._supervisor._on_event = self._on_protocol_event  # type: ignore[attr-defined]
            self._supervisor._on_ready = self._on_supervisor_ready  # type: ignore[attr-defined]

        self._call_lock = threading.Lock()
        self._current_call_id: str | None = None

        # Voice-note recording timing. ``stop_voice_note_recording`` is
        # called inline from the LVGL UI event handler and must return a
        # duration synchronously (per the ``VoIPBackend`` contract). We
        # therefore record the start time on the main side when the
        # recording command is sent, and report ``now - start`` on stop.
        # The sidecar's actual file duration arrives later in the
        # ``MessageReceived`` event for the voice-note kind; the manager
        # can reconcile the persisted record then.
        self._recording_lock = threading.Lock()
        self._recording_start_monotonic: float | None = None

    # ------------------------------------------------------------------
    # VoIPBackend surface
    # ------------------------------------------------------------------

    def on_event(self, callback: Callable[[VoIPEvent], None]) -> None:
        """Register a callback for translated VoIP events."""

        self.event_callbacks.append(callback)

    def start(self) -> bool:
        """Spawn the sidecar (if needed), Configure it, and Register."""

        try:
            self._supervisor.start()
        except Exception as exc:
            # ``SidecarSupervisor.start()`` propagates whatever
            # ``multiprocessing.Process.start()`` raises (typically
            # ``OSError`` on spawn / fork failure) in addition to its own
            # ``RuntimeError`` for permanent-failure state. A spawn failure
            # at boot must not crash ``ManagersBoot.init_managers``;
            # ``VoIPManager.start()`` treats ``False`` as music-only mode.
            logger.error("VoIP sidecar supervisor refused to start: {}", exc)
            return False

        config_dict = dataclasses.asdict(self.config)
        try:
            self._supervisor.send(Configure(config=config_dict))
            self._supervisor.send(Register())
        except Exception as exc:
            logger.error("VoIP sidecar refused configure/register command: {}", exc)
            return False

        self.running = True
        return True

    def stop(self) -> None:
        """Send Unregister and stop the sidecar supervisor."""

        # Best-effort Unregister; if the supervisor is already in a non-running
        # state ``send`` raises and we proceed straight to stop().
        try:
            self._supervisor.send(Unregister())
        except RuntimeError:
            pass
        self._supervisor.stop()
        self.running = False
        self._reset_call_state()
        self._reset_recording_state()

    def _on_supervisor_ready(self) -> None:
        """Re-issue Configure + Register after the supervisor (re)starts the sidecar.

        Called by :class:`SidecarSupervisor` after every successful
        handshake, including the transparent restart that follows a
        sidecar pipe-death. The first invocation happens during
        :meth:`start`, before ``self.running`` is True; we skip it then
        because the start path will send Configure + Register itself.

        On every subsequent invocation the sidecar is fresh (no backend
        configured), so we resend Configure + Register so the new sidecar
        accepts subsequent call-control commands instead of rejecting
        them as ``not_configured``.
        """

        if not self.running:
            # Initial handshake — start() will Configure separately.
            return
        try:
            self._supervisor.send(Configure(config=dataclasses.asdict(self.config)))
            self._supervisor.send(Register())
        except Exception as exc:
            logger.error("VoIP sidecar re-Configure after restart failed: {}", exc)
            return
        # Surface a registration progress signal so the manager / UI know
        # the sidecar bounced and we are re-registering.
        self._dispatch(BackendRegistrationStateChanged(state=RegistrationState.PROGRESS))
        self._reset_call_state()
        # The fresh sidecar has no in-flight recording, so any tracked
        # start time on the main side is stale. Drop it so a follow-up
        # stop_voice_note_recording call does not return a duration
        # measured against a recording that no longer exists.
        self._reset_recording_state()
        logger.info("VoIP sidecar re-Configured after supervisor restart")

    def iterate(self) -> int:
        """No-op: the sidecar drives its own iterate cadence."""

        return 0

    def get_iterate_metrics(self) -> VoIPIterateMetrics | None:
        """The sidecar owns iterate metrics; the main process does not see them."""

        return None

    def make_call(self, sip_address: str) -> bool:
        """Send a Dial command. Backend events surface call progress."""

        return self._send_or_log(Dial(uri=sip_address), label="Dial")

    def answer_call(self) -> bool:
        """Accept the currently-tracked incoming call."""

        call_id = self._read_current_call_id()
        if call_id is None:
            logger.warning("answer_call called with no tracked call")
            return False
        return self._send_or_log(Accept(call_id=call_id), label="Accept")

    def reject_call(self) -> bool:
        """Reject the currently-tracked incoming call."""

        call_id = self._read_current_call_id()
        if call_id is None:
            logger.warning("reject_call called with no tracked call")
            return False
        return self._send_or_log(Reject(call_id=call_id), label="Reject")

    def hangup(self) -> bool:
        """Terminate the currently-tracked active call."""

        call_id = self._read_current_call_id()
        if call_id is None:
            logger.warning("hangup called with no tracked call")
            return False
        return self._send_or_log(Hangup(call_id=call_id), label="Hangup")

    def mute(self) -> bool:
        """Mute the local microphone for the currently-tracked call."""

        call_id = self._read_current_call_id()
        if call_id is None:
            logger.warning("mute called with no tracked call")
            return False
        return self._send_or_log(SetMute(call_id=call_id, on=True), label="SetMute(on)")

    def unmute(self) -> bool:
        """Unmute the local microphone for the currently-tracked call."""

        call_id = self._read_current_call_id()
        if call_id is None:
            logger.warning("unmute called with no tracked call")
            return False
        return self._send_or_log(SetMute(call_id=call_id, on=False), label="SetMute(off)")

    def send_text_message(self, sip_address: str, text: str) -> str | None:
        """Send a text message via the sidecar.

        Mints a ``client_id`` locally and includes it in the
        :class:`SendTextMessage` command so the call site has an id to
        track delivery against immediately. The sidecar adapter records
        the mapping ``backend_id -> client_id`` so subsequent message
        events for this message are re-keyed before they reach the main
        process.
        """

        client_id = f"client-msg-{uuid.uuid4()}"
        try:
            self._supervisor.send(
                SendTextMessage(uri=sip_address, text=text, client_id=client_id)
            )
        except Exception as exc:
            logger.error("VoIP sidecar refused SendTextMessage: {}", exc)
            return None
        return client_id

    def start_voice_note_recording(self, file_path: str) -> bool:
        """Start a sidecar-side voice-note recording into ``file_path``.

        Records the start time on the main side so
        :meth:`stop_voice_note_recording` can return an optimistic
        duration synchronously without a pipe round-trip. Returns
        ``False`` if the supervisor refuses the command (sidecar down /
        permanently failed); on success returns ``True`` immediately,
        any backend-side failure surfaces later as a sidecar
        ``Error(code="start_voice_note_failed")`` and is logged.
        """

        try:
            self._supervisor.send(StartVoiceNoteRecording(file_path=file_path))
        except Exception as exc:
            logger.error("VoIP sidecar refused StartVoiceNoteRecording: {}", exc)
            return False
        with self._recording_lock:
            self._recording_start_monotonic = time.monotonic()
        return True

    def stop_voice_note_recording(self) -> int | None:
        """Return the optimistic monotonic-elapsed duration in milliseconds.

        Sends the stop command to the sidecar (best-effort) and returns
        the elapsed wall time since
        :meth:`start_voice_note_recording`. Returns ``None`` if no
        recording was started, or if the start time was already
        consumed by a prior stop/cancel.
        """

        with self._recording_lock:
            start = self._recording_start_monotonic
            self._recording_start_monotonic = None
        if start is None:
            return None
        try:
            self._supervisor.send(StopVoiceNoteRecording())
        except Exception as exc:
            logger.error("VoIP sidecar refused StopVoiceNoteRecording: {}", exc)
            # Returning the elapsed duration here is still useful — main can
            # surface "recording too long" UX immediately even if the
            # sidecar's stop command did not land. The cancel path would
            # have returned False instead.
        return max(0, int((time.monotonic() - start) * 1000))

    def cancel_voice_note_recording(self) -> bool:
        """Discard the active voice-note recording.

        Clears the start-time tracker locally and best-effort-sends the
        cancel command to the sidecar. Returns ``False`` only if the
        supervisor refuses the command outright.
        """

        with self._recording_lock:
            self._recording_start_monotonic = None
        try:
            self._supervisor.send(CancelVoiceNoteRecording())
        except Exception as exc:
            logger.error("VoIP sidecar refused CancelVoiceNoteRecording: {}", exc)
            return False
        return True

    def send_voice_note(
        self,
        sip_address: str,
        *,
        file_path: str,
        duration_ms: int,
        mime_type: str,
    ) -> str | None:
        """Send a previously-recorded voice note via the sidecar.

        Mints a ``client_id`` on the main side and includes it in the
        :class:`SendVoiceNote` command; the sidecar adapter records the
        ``backend_id -> client_id`` mapping so subsequent message
        events for this voice note are re-keyed before they reach main.
        """

        client_id = f"client-msg-{uuid.uuid4()}"
        try:
            self._supervisor.send(
                SendVoiceNote(
                    uri=sip_address,
                    file_path=file_path,
                    duration_ms=duration_ms,
                    mime_type=mime_type,
                    client_id=client_id,
                )
            )
        except Exception as exc:
            logger.error("VoIP sidecar refused SendVoiceNote: {}", exc)
            return None
        return client_id

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _send_or_log(self, command: Any, *, label: str) -> bool:
        """Send a command and return ``False`` on supervisor errors."""

        try:
            self._supervisor.send(command)
            return True
        except RuntimeError as exc:
            logger.error("VoIP sidecar refused {} command: {}", label, exc)
            return False

    def _read_current_call_id(self) -> str | None:
        with self._call_lock:
            return self._current_call_id

    def _set_current_call_id(self, call_id: str | None) -> None:
        with self._call_lock:
            self._current_call_id = call_id

    def _reset_call_state(self) -> None:
        self._set_current_call_id(None)

    def _reset_recording_state(self) -> None:
        with self._recording_lock:
            self._recording_start_monotonic = None

    def _on_protocol_event(self, event: Any) -> None:
        """Translate a protocol event from the sidecar into a ``VoIPEvent``."""

        # Protocol-only events that don't surface to the call layer.
        if isinstance(event, (Hello, Ready, Pong, MediaStateChanged)):
            return

        if isinstance(event, ProtocolLog):
            self._forward_log(event)
            return

        if isinstance(event, ProtocolError):
            logger.warning(
                "VoIP sidecar reported error: code={!r} message={!r} cmd_id={}",
                event.code,
                event.message,
                event.cmd_id,
            )
            # ``backend_stopped`` is the supervisor's signal that the sidecar's
            # backend is gone — surface as a BackendStopped event so existing
            # recovery paths can react.
            if event.code == "backend_stopped":
                self._reset_call_state()
                self._reset_recording_state()
                self._dispatch(BackendStopped(reason=event.message))
                return
            # Non-terminal sidecar errors that nonetheless mean the call did
            # not / cannot proceed: always synthesize a CallStateChanged(ERROR)
            # so ``VoIPManager``'s existing terminal-state handling drops the
            # UI back to idle rather than leaving an optimistic "dialing"
            # state in place. Dispatching unconditionally is safe because
            # the manager treats CallState.ERROR as a no-op when the call
            # state machine is already idle, and missing the dispatch
            # silently strands the UI when sidecar's _current_call_id is
            # set but main's tracker is not (e.g., back-to-back Dials).
            if event.code in _CALL_FATAL_ERROR_CODES:
                self._reset_call_state()
                self._dispatch(BackendCallStateChanged(state=CallState.ERROR))
                return
            # SIP registration cannot proceed — surface as a registration
            # state change so the manager flips to FAILED instead of staying
            # in PROGRESS forever.
            if event.code in _REGISTRATION_FATAL_ERROR_CODES:
                self._dispatch(BackendRegistrationStateChanged(state=RegistrationState.FAILED))
                return
            return

        if isinstance(event, ProtocolRegistrationStateChanged):
            try:
                state = RegistrationState(event.state)
            except ValueError:
                logger.warning("Sidecar emitted unknown registration state {!r}", event.state)
                return
            self._dispatch(BackendRegistrationStateChanged(state=state))
            return

        if isinstance(event, IncomingCall):
            self._set_current_call_id(event.call_id)
            self._dispatch(IncomingCallDetected(caller_address=event.from_uri))
            return

        if isinstance(event, ProtocolCallStateChanged):
            try:
                state = CallState(event.state)
            except ValueError:
                logger.warning("Sidecar emitted unknown call state {!r}", event.state)
                return
            # Track the call id whenever a non-terminal state arrives so
            # outgoing-call flows (Dial -> CallStateChanged) populate it
            # without an IncomingCall ever firing.
            if state not in _TERMINAL_CALL_STATES:
                self._set_current_call_id(event.call_id)
            else:
                self._reset_call_state()
            self._dispatch(BackendCallStateChanged(state=state))
            return

        if isinstance(event, ProtocolMessageReceived):
            record = self._build_voip_message_record(event)
            if record is not None:
                self._dispatch(BackendMessageReceived(message=record))
            return

        if isinstance(event, ProtocolMessageDeliveryChanged):
            try:
                delivery_state = MessageDeliveryState(event.delivery_state)
            except ValueError:
                logger.warning(
                    "Sidecar emitted unknown message delivery state {!r}",
                    event.delivery_state,
                )
                return
            self._dispatch(
                BackendMessageDeliveryChanged(
                    message_id=event.message_id,
                    delivery_state=delivery_state,
                    local_file_path=event.local_file_path,
                    error=event.error,
                )
            )
            return

        if isinstance(event, ProtocolMessageDownloadCompleted):
            self._dispatch(
                BackendMessageDownloadCompleted(
                    message_id=event.message_id,
                    local_file_path=event.local_file_path,
                    mime_type=event.mime_type,
                )
            )
            return

        if isinstance(event, ProtocolMessageFailed):
            self._dispatch(
                BackendMessageFailed(
                    message_id=event.message_id, reason=event.reason
                )
            )
            return

        # Anything else (DTMFReceived, etc.) — log and drop. Future events get
        # explicit handling here as they're added.
        logger.debug(
            "SupervisorBackedBackend dropping unhandled event {}",
            type(event).__name__,
        )

    def _build_voip_message_record(
        self, event: ProtocolMessageReceived
    ) -> VoIPMessageRecord | None:
        try:
            return VoIPMessageRecord(
                id=event.message_id,
                peer_sip_address=event.peer_sip_address,
                sender_sip_address=event.sender_sip_address,
                recipient_sip_address=event.recipient_sip_address,
                kind=MessageKind(event.kind),
                direction=MessageDirection(event.direction),
                delivery_state=MessageDeliveryState(event.delivery_state),
                created_at=event.created_at,
                updated_at=event.updated_at,
                text=event.text,
                local_file_path=event.local_file_path,
                mime_type=event.mime_type,
                duration_ms=event.duration_ms,
                unread=event.unread,
                display_name=event.display_name,
            )
        except ValueError:
            logger.warning(
                "Sidecar emitted MessageReceived with unknown enum value: "
                "kind={!r} direction={!r} delivery_state={!r}",
                event.kind,
                event.direction,
                event.delivery_state,
            )
            return None

    def _dispatch(self, event: VoIPEvent) -> None:
        """Fire a translated VoIP event to all registered callbacks."""

        for callback in list(self.event_callbacks):
            try:
                callback(event)
            except Exception:
                logger.exception("VoIP event callback raised for {}", type(event).__name__)

    def _forward_log(self, event: ProtocolLog) -> None:
        level = _LOG_LEVEL_MAP.get(event.level.upper(), "INFO")
        logger.bind(subsystem="comm").log(level, "[voip-sidecar] {}", event.message)
