"""Wire protocol between the main YoyoPod process and the VoIP sidecar.

Commands flow main -> sidecar. Events flow sidecar -> main. Each message is
an immutable dataclass; the wire format is msgpack with a string ``type``
discriminator and a ``data`` payload. Each frame is sent via
:meth:`multiprocessing.connection.Connection.send_bytes`, which preserves
message boundaries on both POSIX and Windows.

Phase 2A intentionally lands the protocol and supervisor scaffolding without
wiring liblinphone yet; the sidecar entry point in this PR runs an echo
loop that the supervisor tests exercise. Phase 2B replaces the echo loop
with the real ``LiblinphoneBackend`` and routes ``VoIPManager`` through the
supervisor.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from multiprocessing.connection import Connection
from typing import Any

import msgpack

PROTOCOL_VERSION = 1


# ---------------------------------------------------------------------------
# Commands (main -> sidecar)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Hello:
    """Handshake message exchanged in both directions at startup."""

    version: int = PROTOCOL_VERSION
    capabilities: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Configure:
    """Send the serialized ``VoIPConfig`` to the sidecar before registration.

    ``config`` carries a ``dataclasses.asdict``-style payload of
    :class:`yoyopod.integrations.call.models.VoIPConfig`. The sidecar
    reconstructs the dataclass and asks the backend factory for a fresh
    backend; idempotent calls replace the prior backend cleanly.
    """

    config: dict[str, Any]
    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class Register:
    """Initiate SIP registration with the previously :class:`Configure`-d account."""

    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class Unregister:
    """Clear the active SIP registration."""

    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class Dial:
    """Place an outgoing call to the given SIP URI."""

    uri: str
    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class Accept:
    """Accept the incoming call identified by ``call_id``."""

    call_id: str
    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class Reject:
    """Reject the incoming call identified by ``call_id``."""

    call_id: str
    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class Hangup:
    """Terminate the active call identified by ``call_id``."""

    call_id: str
    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class SetMute:
    """Mute or unmute the local microphone for the given call."""

    call_id: str
    on: bool
    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class SetVolume:
    """Adjust the speaker volume for the given call. ``level`` is 0.0-1.0."""

    call_id: str
    level: float
    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class SendTextMessage:
    """Send a SIP text message to the given URI.

    ``client_id`` is minted on the main side so the sender can return it
    synchronously from :meth:`VoIPBackend.send_text_message`. The sidecar
    adapter records the mapping ``backend_id -> client_id`` internally;
    every subsequent message event the sidecar emits for this message
    uses ``client_id`` as its ``message_id``, so the main process never
    has to know the underlying liblinphone-assigned id.
    """

    uri: str
    text: str
    client_id: str
    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class StartVoiceNoteRecording:
    """Begin recording a voice note into ``file_path`` on the sidecar's filesystem.

    Main and sidecar share the host filesystem on the Pi, so ``file_path``
    is a path the main process picked under
    :attr:`yoyopod.integrations.call.models.VoIPConfig.voice_note_store_dir`
    that the sidecar writes into directly. Main also records the start
    time on its own clock so :class:`StopVoiceNoteRecording` can return
    an optimistic duration synchronously without a round-trip.
    """

    file_path: str
    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class StopVoiceNoteRecording:
    """Finalize the active voice-note recording.

    The sidecar's actual file duration may differ from main's
    monotonic-elapsed measurement by a small amount (IPC start/stop
    latency + WAV header finalization). The corrected value travels
    back in the eventual :class:`MessageReceived` event for the
    voice-note kind.
    """

    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class CancelVoiceNoteRecording:
    """Discard the active voice-note recording without sending it."""

    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class SendVoiceNote:
    """Send a previously-recorded voice note to the given URI.

    ``client_id`` follows the same mint-on-main-side pattern used by
    :class:`SendTextMessage`. ``duration_ms`` is the optimistic duration
    main computed from monotonic-elapsed; the sidecar passes it straight
    through to liblinphone so the peer sees it in the message metadata.
    """

    uri: str
    file_path: str
    duration_ms: int
    mime_type: str
    client_id: str
    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class Ping:
    """Liveness probe. Sidecar must echo back :class:`Pong`."""

    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class Shutdown:
    """Request a graceful sidecar shutdown."""


# ---------------------------------------------------------------------------
# Events (sidecar -> main)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Ready:
    """Sidecar finished initializing and is ready to accept commands."""


@dataclass(frozen=True, slots=True)
class RegistrationStateChanged:
    """Reported whenever SIP registration state transitions."""

    state: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class IncomingCall:
    """A new inbound call rang."""

    call_id: str
    from_uri: str
    from_display: str | None = None


@dataclass(frozen=True, slots=True)
class CallStateChanged:
    """Active call transitioned to a new state."""

    call_id: str
    state: str


@dataclass(frozen=True, slots=True)
class MediaStateChanged:
    """Media plane state for the active call."""

    call_id: str
    mic_muted: bool
    speaker_volume: float


@dataclass(frozen=True, slots=True)
class DTMFReceived:
    """A DTMF tone was received on the active call."""

    call_id: str
    digit: str


@dataclass(frozen=True, slots=True)
class MessageReceived:
    """An inbound SIP message arrived.

    Mirrors the flat fields of
    :class:`yoyopod.integrations.call.models.VoIPMessageRecord` so the
    main process can reconstruct the record without nested-dict
    serialization. Enum-valued fields (``kind``, ``direction``,
    ``delivery_state``) are sent as their ``.value`` strings.
    """

    message_id: str
    peer_sip_address: str
    sender_sip_address: str
    recipient_sip_address: str
    kind: str
    direction: str
    delivery_state: str
    created_at: str
    updated_at: str
    text: str = ""
    local_file_path: str = ""
    mime_type: str = ""
    duration_ms: int = 0
    unread: bool = False
    display_name: str = ""


@dataclass(frozen=True, slots=True)
class MessageDeliveryChanged:
    """Delivery state of a known message changed.

    For outbound messages, ``message_id`` carries the ``client_id`` that
    main minted in :class:`SendTextMessage`; the adapter's
    ``backend_id -> client_id`` map performs the translation. For inbound
    messages it carries whatever id the sidecar assigned (typically the
    backend's id passed straight through).
    """

    message_id: str
    delivery_state: str
    local_file_path: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class MessageDownloadCompleted:
    """An inbound message attachment finished downloading on the sidecar side."""

    message_id: str
    local_file_path: str
    mime_type: str = ""


@dataclass(frozen=True, slots=True)
class MessageFailed:
    """A message send or receive operation failed on the sidecar side."""

    message_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class Pong:
    """Liveness response to :class:`Ping`."""

    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class Error:
    """Sidecar reported a command failure or asynchronous error."""

    code: str
    message: str
    cmd_id: int | None = None


@dataclass(frozen=True, slots=True)
class Log:
    """Forwarded log line from the sidecar process."""

    level: str
    message: str


# ---------------------------------------------------------------------------
# Registries and codec
# ---------------------------------------------------------------------------


# ``Hello`` is bidirectional and appears in both registries so either side
# can decode the handshake without special-casing.
_COMMAND_REGISTRY: dict[str, type[Any]] = {
    "Hello": Hello,
    "Configure": Configure,
    "Register": Register,
    "Unregister": Unregister,
    "Dial": Dial,
    "Accept": Accept,
    "Reject": Reject,
    "Hangup": Hangup,
    "SetMute": SetMute,
    "SetVolume": SetVolume,
    "SendTextMessage": SendTextMessage,
    "StartVoiceNoteRecording": StartVoiceNoteRecording,
    "StopVoiceNoteRecording": StopVoiceNoteRecording,
    "CancelVoiceNoteRecording": CancelVoiceNoteRecording,
    "SendVoiceNote": SendVoiceNote,
    "Ping": Ping,
    "Shutdown": Shutdown,
}

_EVENT_REGISTRY: dict[str, type[Any]] = {
    "Hello": Hello,
    "Ready": Ready,
    "RegistrationStateChanged": RegistrationStateChanged,
    "IncomingCall": IncomingCall,
    "CallStateChanged": CallStateChanged,
    "MediaStateChanged": MediaStateChanged,
    "DTMFReceived": DTMFReceived,
    "MessageReceived": MessageReceived,
    "MessageDeliveryChanged": MessageDeliveryChanged,
    "MessageDownloadCompleted": MessageDownloadCompleted,
    "MessageFailed": MessageFailed,
    "Pong": Pong,
    "Error": Error,
    "Log": Log,
}


class ProtocolError(RuntimeError):
    """Raised when a frame cannot be decoded against the expected registry."""


def encode(message: Any) -> bytes:
    """Pack one dataclass message as a tagged msgpack payload."""

    type_name = type(message).__name__
    if type_name not in _COMMAND_REGISTRY and type_name not in _EVENT_REGISTRY:
        raise ProtocolError(f"Unknown message type for encode: {type_name!r}")
    return msgpack.packb(  # type: ignore[no-any-return]
        {"type": type_name, "data": dataclasses.asdict(message)},
        use_bin_type=True,
    )


def decode_command(data: bytes) -> Any:
    """Decode one frame received by the sidecar (a command from main)."""

    return _decode(data, registry=_COMMAND_REGISTRY, direction="command")


def decode_event(data: bytes) -> Any:
    """Decode one frame received by the main process (an event from sidecar)."""

    return _decode(data, registry=_EVENT_REGISTRY, direction="event")


def _decode(data: bytes, *, registry: dict[str, type[Any]], direction: str) -> Any:
    payload = msgpack.unpackb(data, raw=False)
    if not isinstance(payload, dict) or "type" not in payload or "data" not in payload:
        raise ProtocolError(f"Malformed {direction} frame: {payload!r}")
    type_name = payload["type"]
    cls = registry.get(type_name)
    if cls is None:
        raise ProtocolError(f"Unknown {direction} type: {type_name!r}")
    fields = payload["data"]
    if not isinstance(fields, dict):
        raise ProtocolError(f"Malformed {direction} payload for {type_name}: {fields!r}")
    return _construct(cls, fields)


def _construct(cls: type[Any], fields: dict[str, Any]) -> Any:
    """Build a dataclass instance from a decoded fields dict, normalizing tuples."""

    converted: dict[str, Any] = {}
    for field in dataclasses.fields(cls):
        if field.name not in fields:
            continue
        value = fields[field.name]
        # msgpack decodes Python tuples as lists; restore where the field is typed as tuple.
        if isinstance(value, list) and _expects_tuple(field.type):
            converted[field.name] = tuple(value)
        else:
            converted[field.name] = value
    try:
        return cls(**converted)
    except TypeError as exc:
        # Missing required fields or unknown keys raise TypeError from the
        # dataclass ``__init__``. Surface them as ProtocolError so the
        # readers (``run_sidecar``, ``SidecarSupervisor._reader_loop``) can
        # keep handling frames instead of crashing the thread/process.
        raise ProtocolError(f"Cannot construct {cls.__name__} from frame fields: {exc}") from exc


def _expects_tuple(annotation: Any) -> bool:
    """Best-effort check for tuple-typed fields without importing ``typing`` machinery."""

    text = str(annotation)
    return text.startswith("tuple[") or text.startswith("Tuple[")


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------


def send_message(conn: Connection, message: Any) -> None:
    """Encode one message and send it over the multiprocessing connection."""

    conn.send_bytes(encode(message))


def recv_command(conn: Connection) -> Any:
    """Block until a command frame arrives and return the decoded command."""

    return decode_command(conn.recv_bytes())


def recv_event(conn: Connection) -> Any:
    """Block until an event frame arrives and return the decoded event."""

    return decode_event(conn.recv_bytes())
