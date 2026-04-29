"""VoIPBackend adapter backed by the Rust VoIP Host worker."""

from __future__ import annotations

import dataclasses
import os
import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from loguru import logger

from yoyopod.backends.voip.protocol import VoIPIterateMetrics
from yoyopod.core.workers import WorkerProcessConfig
from yoyopod.integrations.call.models import (
    BackendRecovered,
    BackendStopped,
    CallState,
    CallStateChanged,
    IncomingCallDetected,
    MessageDeliveryChanged,
    MessageDeliveryState,
    MessageDirection,
    MessageDownloadCompleted,
    MessageFailed,
    MessageKind,
    MessageReceived,
    RegistrationState,
    RegistrationStateChanged,
    VoIPCallSessionSnapshot,
    VoIPConfig,
    VoIPEvent,
    VoIPLifecycleSnapshot,
    VoIPMessageSnapshot,
    VoIPMessageRecord,
    VoIPRuntimeSnapshot,
    VoIPRuntimeSnapshotChanged,
    VoIPVoiceNoteSnapshot,
)

_STARTUP_COMMANDS = frozenset({"voip.configure", "voip.register"})
_CALL_CONTROL_COMMANDS = frozenset(
    {
        "voip.dial",
        "voip.answer",
        "voip.reject",
        "voip.hangup",
        "voip.set_mute",
    }
)
_MESSAGE_SEND_COMMANDS = frozenset({"voip.send_text_message", "voip.send_voice_note"})
_VOICE_NOTE_RECORDING_COMMANDS = frozenset(
    {
        "voip.start_voice_note_recording",
        "voip.stop_voice_note_recording",
        "voip.cancel_voice_note_recording",
    }
)
_INTENTIONAL_STOP_REASONS = frozenset({"stop", "stop_all"})
_INTENTIONAL_LIFECYCLE_STOP_REASONS = frozenset({"unregistered", "shutdown"})


class RustHostBackend:
    """VoIPBackend adapter backed by the Rust VoIP Host worker."""

    def __init__(
        self,
        config: VoIPConfig,
        *,
        worker_supervisor: Any,
        worker_path: str,
        domain: str = "voip",
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self.config = config
        self.worker_supervisor = worker_supervisor
        self.worker_path = worker_path
        self.domain = domain
        self.env = env
        self.cwd = cwd
        self.running = False
        self.event_callbacks: list[Callable[[VoIPEvent], None]] = []
        self._registered_with_supervisor = False
        self._request_counter = 0
        self._pending_commands: dict[str, str] = {}
        self._pending_message_ids: dict[str, str] = {}
        self._startup_commands_sent = False
        self._ready_seen = False
        self._reconfigure_on_ready = False
        self._stopping = False
        self._last_stop_reason: str | None = None
        self._recording_start_monotonic: float | None = None
        self._runtime_snapshot: VoIPRuntimeSnapshot | None = None
        self._snapshot_registration_state = RegistrationState.NONE
        self._snapshot_call_state = CallState.IDLE
        self._last_lifecycle_state = "unconfigured"

    def on_event(self, callback: Callable[[VoIPEvent], None]) -> None:
        self.event_callbacks.append(callback)

    def start(self) -> bool:
        if self.running:
            return True
        if not self.config.is_backend_start_configured():
            logger.error("Rust VoIP Host requires sip_server and sip_identity")
            return False

        register = getattr(self.worker_supervisor, "register", None)
        start = getattr(self.worker_supervisor, "start", None)
        if not callable(register) or not callable(start):
            logger.error("Rust VoIP Host supervisor is unavailable")
            return False

        try:
            if not self._registered_with_supervisor:
                register(
                    self.domain,
                    WorkerProcessConfig(
                        name=self.domain,
                        argv=[self.worker_path],
                        cwd=self.cwd,
                        env=self._process_env(),
                    ),
                )
                self._registered_with_supervisor = True
            if not bool(start(self.domain)):
                return False
            if not self._send_startup_commands():
                self._stop_after_startup_command_failure(
                    "startup_command_failed", notify_backend_stopped=False
                )
                return False
        except Exception as exc:
            logger.error("Rust VoIP Host start failed: {}", exc)
            self.running = False
            return False

        self.running = True
        self._last_stop_reason = None
        return True

    def stop(self) -> None:
        self._stopping = True
        try:
            if self._registered_with_supervisor:
                self._send("voip.unregister", {})
                stop = getattr(self.worker_supervisor, "stop", None)
                if callable(stop):
                    stop(self.domain, grace_seconds=1.0)
        finally:
            self._pending_commands.clear()
            self._pending_message_ids.clear()
            self._startup_commands_sent = False
            self._ready_seen = False
            self._reconfigure_on_ready = False
            self._recording_start_monotonic = None
            self._runtime_snapshot = None
            self._snapshot_registration_state = RegistrationState.NONE
            self._snapshot_call_state = CallState.IDLE
            self._last_lifecycle_state = "stopped"
            self.running = False
            self._stopping = False

    def iterate(self) -> int:
        return 0

    def get_iterate_metrics(self) -> VoIPIterateMetrics | None:
        return None

    def get_runtime_snapshot(self) -> VoIPRuntimeSnapshot | None:
        """Return the latest canonical runtime snapshot emitted by the Rust worker."""

        return self._runtime_snapshot

    def make_call(self, sip_address: str) -> bool:
        return self._send("voip.dial", {"uri": sip_address})

    def answer_call(self) -> bool:
        return self._send("voip.answer", {})

    def reject_call(self) -> bool:
        return self._send("voip.reject", {})

    def hangup(self) -> bool:
        return self._send("voip.hangup", {})

    def mute(self) -> bool:
        return self._send("voip.set_mute", {"muted": True})

    def unmute(self) -> bool:
        return self._send("voip.set_mute", {"muted": False})

    def send_text_message(self, sip_address: str, text: str) -> str | None:
        message_id = self._next_message_id()
        request_id = self._send_with_request_id(
            "voip.send_text_message",
            {"uri": sip_address, "text": text, "client_id": message_id},
        )
        if request_id is None:
            return None
        self._pending_message_ids[request_id] = message_id
        return message_id

    def start_voice_note_recording(self, file_path: str) -> bool:
        request_id = self._send_with_request_id(
            "voip.start_voice_note_recording", {"file_path": file_path}
        )
        if request_id is None:
            return False
        self._recording_start_monotonic = time.monotonic()
        return True

    def stop_voice_note_recording(self) -> int | None:
        start = self._recording_start_monotonic
        if start is None:
            return None
        if self._send_with_request_id("voip.stop_voice_note_recording", {}) is None:
            return None
        self._recording_start_monotonic = None
        return max(0, int((time.monotonic() - start) * 1000))

    def cancel_voice_note_recording(self) -> bool:
        self._recording_start_monotonic = None
        return self._send("voip.cancel_voice_note_recording", {})

    def send_voice_note(
        self,
        sip_address: str,
        *,
        file_path: str,
        duration_ms: int,
        mime_type: str,
    ) -> str | None:
        message_id = self._next_message_id()
        request_id = self._send_with_request_id(
            "voip.send_voice_note",
            {
                "uri": sip_address,
                "file_path": file_path,
                "duration_ms": int(duration_ms),
                "mime_type": mime_type,
                "client_id": message_id,
            },
        )
        if request_id is None:
            return None
        self._pending_message_ids[request_id] = message_id
        return message_id

    def mark_voice_notes_seen(self, sip_address: str) -> bool:
        return self._send("voip.mark_voice_notes_seen", {"uri": sip_address})

    def handle_worker_message(self, event: Any) -> None:
        if getattr(event, "domain", self.domain) != self.domain:
            return

        payload = getattr(event, "payload", {}) or {}
        event_type = getattr(event, "type", "")
        request_id = getattr(event, "request_id", None)
        kind = getattr(event, "kind", "event")
        if kind == "result":
            self._pending_message_ids.pop(request_id, None)
            self._pop_pending_command(request_id)
            return
        if kind == "error":
            self._handle_worker_error(payload, request_id=request_id)
            return
        if kind != "event":
            return
        if event_type == "voip.ready":
            self._handle_worker_ready()
            return
        if event_type == "voip.snapshot":
            self._handle_session_snapshot(payload)
            return
        if event_type == "voip.lifecycle_changed":
            self._handle_lifecycle_changed(payload)
            return
        if event_type == "voip.registration_changed":
            self._dispatch_registration_state(
                _registration_state(str(payload.get("state", "none")))
            )
            return
        if event_type == "voip.incoming_call":
            self._dispatch(IncomingCallDetected(caller_address=str(payload.get("from_uri", ""))))
            return
        if event_type == "voip.call_state_changed":
            self._dispatch_call_state(_call_state(str(payload.get("state", "idle"))))
            return
        if event_type == "voip.backend_stopped":
            self._mark_stopped(str(payload.get("reason", "")) or "backend_stopped")
            return
        if event_type == "voip.message_received":
            message = _message_record(payload)
            if message is not None:
                self._dispatch(MessageReceived(message=message))
            return
        if event_type == "voip.message_delivery_changed":
            delivery_state = _message_delivery_state(str(payload.get("delivery_state", "")))
            if delivery_state is None:
                logger.warning(
                    "Rust VoIP Host emitted unknown message delivery state {!r}",
                    payload.get("delivery_state", ""),
                )
                return
            self._dispatch(
                MessageDeliveryChanged(
                    message_id=str(payload.get("message_id", "")),
                    delivery_state=delivery_state,
                    local_file_path=str(payload.get("local_file_path", "")),
                    error=str(payload.get("error", "")),
                )
            )
            return
        if event_type == "voip.message_download_completed":
            self._dispatch(
                MessageDownloadCompleted(
                    message_id=str(payload.get("message_id", "")),
                    local_file_path=str(payload.get("local_file_path", "")),
                    mime_type=str(payload.get("mime_type", "")),
                )
            )
            return
        if event_type == "voip.message_failed":
            self._dispatch(
                MessageFailed(
                    message_id=str(payload.get("message_id", "")),
                    reason=str(payload.get("reason", "")),
                )
            )

    def handle_worker_state_change(self, event: Any) -> None:
        if getattr(event, "domain", self.domain) != self.domain:
            return

        state = str(getattr(event, "state", ""))
        reason = str(getattr(event, "reason", "")) or state
        if state == "running":
            if self._ready_seen:
                self._reconfigure_on_ready = True
            return
        if state in {"degraded", "disabled", "stopped"}:
            intentional_stop = state == "stopped" and reason in _INTENTIONAL_STOP_REASONS
            self._reconfigure_on_ready = not self._stopping and not intentional_stop
            if self._stopping or intentional_stop:
                self.running = False
                return
            self._mark_stopped(reason)

    def _send(self, message_type: str, payload: dict[str, Any]) -> bool:
        return self._send_with_request_id(message_type, payload) is not None

    def _send_with_request_id(self, message_type: str, payload: dict[str, Any]) -> str | None:
        send_command = getattr(self.worker_supervisor, "send_command", None)
        if not callable(send_command):
            return None
        request_id = self._next_request_id(message_type)
        try:
            sent = bool(
                send_command(
                    self.domain,
                    type=message_type,
                    payload=payload,
                    request_id=request_id,
                )
            )
        except Exception as exc:
            logger.error("Rust VoIP Host command {} failed: {}", message_type, exc)
            return None
        if sent:
            self._pending_commands[request_id] = message_type
            return request_id
        return None

    def _dispatch(self, event: VoIPEvent) -> None:
        for callback in list(self.event_callbacks):
            try:
                callback(event)
            except Exception:
                logger.exception("Rust VoIP Host callback raised for {}", type(event).__name__)

    def _config_payload(self) -> dict[str, Any]:
        payload = dataclasses.asdict(self.config)
        payload["conference_factory_uri"] = self.config.effective_conference_factory_uri()
        payload["file_transfer_server_url"] = self.config.effective_file_transfer_server_url()
        payload["lime_server_url"] = self.config.effective_lime_server_url()
        return payload

    def _process_env(self) -> dict[str, str] | None:
        if self.env is None:
            return None
        merged = dict(os.environ)
        merged.update(self.env)
        return merged

    def _send_startup_commands(self) -> bool:
        self._last_lifecycle_state = "starting"
        if not self._send("voip.configure", self._config_payload()):
            return False
        if not self._send("voip.register", {}):
            return False
        self._startup_commands_sent = True
        return True

    def _handle_worker_ready(self) -> None:
        if self._reconfigure_on_ready or not self._startup_commands_sent:
            logger.info("Rust VoIP Host ready; sending configure/register")
            if not self._send_startup_commands():
                self._stop_after_startup_command_failure("worker_ready_reconfigure_failed")
                return
            self.running = True
        self._ready_seen = True
        self._reconfigure_on_ready = False

    def _handle_worker_error(self, payload: dict[str, Any], *, request_id: str | None) -> None:
        command = self._pop_pending_command(request_id)
        reason = _worker_error_reason(payload, command=command)
        message_id = self._pending_message_ids.pop(request_id, "") if request_id else ""
        if command in _STARTUP_COMMANDS or command is None:
            self._stop_after_startup_command_failure(
                reason,
                notify_backend_stopped=self._last_lifecycle_state not in {"failed", "stopped"},
            )
            return
        if command in _CALL_CONTROL_COMMANDS:
            logger.warning("Rust VoIP Host call command failed: {}", reason)
            self._dispatch(CallStateChanged(state=CallState.ERROR))
            return
        if command in _VOICE_NOTE_RECORDING_COMMANDS:
            self._recording_start_monotonic = None
            self._dispatch(MessageFailed(message_id="", reason=reason))
            return
        if command in _MESSAGE_SEND_COMMANDS:
            if message_id:
                self._dispatch(MessageFailed(message_id=message_id, reason=reason))
            else:
                logger.warning("Rust VoIP Host message command failed: {}", reason)
            return
        logger.warning("Rust VoIP Host command failed: {}", reason)

    def _stop_after_startup_command_failure(
        self,
        reason: str,
        *,
        notify_backend_stopped: bool = True,
    ) -> None:
        stop = getattr(self.worker_supervisor, "stop", None)
        if self._registered_with_supervisor and callable(stop):
            was_stopping = self._stopping
            self._stopping = True
            try:
                stop(self.domain, grace_seconds=1.0)
            except Exception as exc:
                logger.warning(
                    "Rust VoIP Host failed to stop worker after startup command failure {}: {}",
                    reason,
                    exc,
                )
            finally:
                self._stopping = was_stopping
        self._pending_commands.clear()
        self._pending_message_ids.clear()
        self._startup_commands_sent = False
        self._ready_seen = False
        self._reconfigure_on_ready = False
        self._recording_start_monotonic = None
        self._runtime_snapshot = None
        self._snapshot_registration_state = RegistrationState.NONE
        self._snapshot_call_state = CallState.IDLE
        self._last_lifecycle_state = "failed"
        self.running = False
        if notify_backend_stopped:
            self._mark_stopped(reason)
        else:
            self._last_stop_reason = reason

    def _handle_lifecycle_changed(self, payload: dict[str, Any]) -> None:
        state = str(payload.get("state", "") or "").strip()
        if not state:
            return
        reason = str(payload.get("reason", "") or "").strip() or state
        recovered = _bool_payload(payload.get("recovered", False))
        self._last_lifecycle_state = state
        if state == "stopped" and (self._stopping or reason in _INTENTIONAL_LIFECYCLE_STOP_REASONS):
            self.running = False
            return
        if state in {"failed", "stopped"}:
            self._mark_stopped(reason)
            return
        if state == "registered":
            was_stopped = self._last_stop_reason is not None
            self.running = True
            if recovered or was_stopped:
                self._dispatch(BackendRecovered(reason=reason))
            self._last_stop_reason = None

    def _handle_session_snapshot(self, payload: dict[str, Any]) -> None:
        snapshot = _runtime_snapshot(payload)
        self._runtime_snapshot = snapshot
        self._dispatch_registration_state(snapshot.registration_state)
        self._dispatch_call_state(snapshot.call_state)
        self._dispatch(VoIPRuntimeSnapshotChanged(snapshot=snapshot))

    def _dispatch_registration_state(self, state: RegistrationState) -> None:
        if state == self._snapshot_registration_state:
            return
        self._snapshot_registration_state = state
        self._dispatch(RegistrationStateChanged(state=state))

    def _dispatch_call_state(self, state: CallState) -> None:
        if state == self._snapshot_call_state:
            return
        self._snapshot_call_state = state
        self._dispatch(CallStateChanged(state=state))

    def _mark_stopped(self, reason: str) -> None:
        if not self.running and self._last_stop_reason == reason:
            return
        self.running = False
        self._last_stop_reason = reason
        if self._last_lifecycle_state != "stopped":
            self._last_lifecycle_state = "failed"
        self._dispatch(BackendStopped(reason=reason))

    def _next_request_id(self, message_type: str) -> str:
        self._request_counter += 1
        command_name = message_type.replace(".", "_")
        return f"{self.domain}-{command_name}-{self._request_counter}"

    def _next_message_id(self) -> str:
        return f"rust-msg-{uuid.uuid4()}"

    def _pop_pending_command(self, request_id: str | None) -> str | None:
        if request_id is None:
            return None
        return self._pending_commands.pop(request_id, None)


def _registration_state(value: str) -> RegistrationState:
    try:
        return RegistrationState(value)
    except ValueError:
        return RegistrationState.NONE


def _call_state(value: str) -> CallState:
    try:
        return CallState(value)
    except ValueError:
        return CallState.IDLE


def _message_record(payload: dict[str, Any]) -> VoIPMessageRecord | None:
    kind = _message_kind(str(payload.get("kind", "")))
    direction = _message_direction(str(payload.get("direction", "")))
    delivery_state = _message_delivery_state(str(payload.get("delivery_state", "")))
    if kind is None or direction is None or delivery_state is None:
        logger.warning(
            "Rust VoIP Host emitted message with unknown enum values: "
            "kind={!r} direction={!r} delivery_state={!r}",
            payload.get("kind", ""),
            payload.get("direction", ""),
            payload.get("delivery_state", ""),
        )
        return None

    timestamp = _iso_timestamp(payload.get("created_at"))
    updated_at = (
        _iso_timestamp(payload.get("updated_at")) if payload.get("updated_at") else timestamp
    )
    return VoIPMessageRecord(
        id=str(payload.get("message_id", "")),
        peer_sip_address=str(payload.get("peer_sip_address", "")),
        sender_sip_address=str(payload.get("sender_sip_address", "")),
        recipient_sip_address=str(payload.get("recipient_sip_address", "")),
        kind=kind,
        direction=direction,
        delivery_state=delivery_state,
        created_at=timestamp,
        updated_at=updated_at,
        text=str(payload.get("text", "")),
        local_file_path=str(payload.get("local_file_path", "")),
        mime_type=str(payload.get("mime_type", "")),
        duration_ms=_duration_ms(payload.get("duration_ms")),
        unread=_bool_payload(payload.get("unread", False)),
        display_name=str(payload.get("display_name", "")),
    )


def _runtime_snapshot(payload: dict[str, Any]) -> VoIPRuntimeSnapshot:
    lifecycle_payload = _dict_payload(payload.get("lifecycle"))
    call_session_payload = _dict_payload(payload.get("call_session"))
    voice_note_payload = _dict_payload(payload.get("voice_note"))
    return VoIPRuntimeSnapshot(
        configured=_bool_payload(payload.get("configured", False)),
        registered=_bool_payload(payload.get("registered", False)),
        registration_state=_registration_state(_snapshot_registration_value(payload)),
        call_state=_call_state(str(payload.get("call_state", "idle"))),
        active_call_id=str(payload.get("active_call_id", "") or ""),
        active_call_peer=str(payload.get("active_call_peer", "") or ""),
        muted=_bool_payload(payload.get("muted", False)),
        pending_outbound_messages=_duration_ms(payload.get("pending_outbound_messages")),
        unread_voice_notes=_duration_ms(payload.get("unread_voice_notes")),
        unread_voice_notes_by_contact=_int_map_payload(
            payload.get("unread_voice_notes_by_contact")
        ),
        latest_voice_note_by_contact=_summary_map_payload(
            payload.get("latest_voice_note_by_contact")
        ),
        lifecycle=VoIPLifecycleSnapshot(
            state=str(lifecycle_payload.get("state", "unconfigured") or "unconfigured"),
            reason=str(lifecycle_payload.get("reason", "") or ""),
            backend_available=_bool_payload(lifecycle_payload.get("backend_available", False)),
        ),
        call_session=VoIPCallSessionSnapshot(
            active=_bool_payload(call_session_payload.get("active", False)),
            session_id=str(call_session_payload.get("session_id", "") or ""),
            direction=str(call_session_payload.get("direction", "") or ""),
            peer_sip_address=str(call_session_payload.get("peer_sip_address", "") or ""),
            answered=_bool_payload(call_session_payload.get("answered", False)),
            terminal_state=str(call_session_payload.get("terminal_state", "") or ""),
            local_end_action=str(call_session_payload.get("local_end_action", "") or ""),
            duration_seconds=_duration_ms(call_session_payload.get("duration_seconds")),
            history_outcome=str(call_session_payload.get("history_outcome", "") or ""),
        ),
        voice_note=VoIPVoiceNoteSnapshot(
            state=str(voice_note_payload.get("state", "idle") or "idle"),
            file_path=str(voice_note_payload.get("file_path", "") or ""),
            duration_ms=_duration_ms(voice_note_payload.get("duration_ms")),
            mime_type=str(voice_note_payload.get("mime_type", "") or ""),
            message_id=str(voice_note_payload.get("message_id", "") or ""),
        ),
        last_message=_message_snapshot(payload.get("last_message")),
    )


def _snapshot_registration_value(payload: dict[str, Any]) -> str:
    registration_state = str(payload.get("registration_state", "") or "").strip()
    if registration_state:
        return registration_state
    return "ok" if _bool_payload(payload.get("registered", False)) else "none"


def _message_snapshot(payload: object) -> VoIPMessageSnapshot | None:
    message_payload = _dict_payload(payload)
    message_id = str(message_payload.get("message_id", "") or "")
    if not message_id:
        return None
    return VoIPMessageSnapshot(
        message_id=message_id,
        kind=_message_kind(str(message_payload.get("kind", ""))),
        direction=_message_direction(str(message_payload.get("direction", ""))),
        delivery_state=_message_delivery_state(str(message_payload.get("delivery_state", ""))),
        local_file_path=str(message_payload.get("local_file_path", "") or ""),
        error=str(message_payload.get("error", "") or ""),
    )


def _dict_payload(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _int_map_payload(value: object) -> dict[str, int]:
    payload = _dict_payload(value)
    result: dict[str, int] = {}
    for key, raw_value in payload.items():
        normalized_key = str(key).strip()
        if not normalized_key:
            continue
        result[normalized_key] = _duration_ms(raw_value)
    return result


def _summary_map_payload(value: object) -> dict[str, dict[str, object]]:
    payload = _dict_payload(value)
    result: dict[str, dict[str, object]] = {}
    for key, raw_summary in payload.items():
        normalized_key = str(key).strip()
        if not normalized_key:
            continue
        summary = _dict_payload(raw_summary)
        result[normalized_key] = {
            "message_id": str(summary.get("message_id", "") or ""),
            "direction": str(summary.get("direction", "") or ""),
            "delivery_state": str(summary.get("delivery_state", "") or ""),
            "local_file_path": str(summary.get("local_file_path", "") or ""),
            "duration_ms": _duration_ms(summary.get("duration_ms")),
            "unread": _bool_payload(summary.get("unread", False)),
            "display_name": str(summary.get("display_name", "") or ""),
        }
    return result


def _message_kind(value: str) -> MessageKind | None:
    try:
        return MessageKind(value)
    except ValueError:
        return None


def _message_direction(value: str) -> MessageDirection | None:
    try:
        return MessageDirection(value)
    except ValueError:
        return None


def _message_delivery_state(value: str) -> MessageDeliveryState | None:
    try:
        return MessageDeliveryState(value)
    except ValueError:
        return None


def _iso_timestamp(value: Any) -> str:
    timestamp = str(value or "").strip()
    if timestamp:
        return timestamp
    return datetime.now(timezone.utc).isoformat()


def _duration_ms(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _bool_payload(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _worker_error_reason(payload: dict[str, Any], *, command: str | None) -> str:
    code = str(payload.get("code", "worker_error")).strip() or "worker_error"
    message = str(payload.get("message", "")).strip()
    prefix = f"{command} {code}" if command else code
    if message:
        return f"{prefix}: {message}"
    return prefix
