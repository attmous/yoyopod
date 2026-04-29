"""Canonical call-domain models and typed backend events."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TypeAlias

LINPHONE_HOSTED_SIP_SERVER = "sip.linphone.org"
LINPHONE_HOSTED_CONFERENCE_FACTORY_URI = "sip:conference-factory@sip.linphone.org"
LINPHONE_HOSTED_FILE_TRANSFER_SERVER_URL = "https://files.linphone.org/lft.php"
LINPHONE_HOSTED_LIME_SERVER_URL = "https://lime.linphone.org/lime-server/lime-server.php"


class RegistrationState(Enum):
    """SIP registration states."""

    NONE = "none"
    PROGRESS = "progress"
    OK = "ok"
    CLEARED = "cleared"
    FAILED = "failed"


class CallState(Enum):
    """Call states."""

    IDLE = "idle"
    INCOMING = "incoming"
    OUTGOING = "outgoing_init"
    OUTGOING_PROGRESS = "outgoing_progress"
    OUTGOING_RINGING = "outgoing_ringing"
    OUTGOING_EARLY_MEDIA = "outgoing_early_media"
    CONNECTED = "connected"
    STREAMS_RUNNING = "streams_running"
    PAUSED = "paused"
    PAUSED_BY_REMOTE = "paused_by_remote"
    UPDATED_BY_REMOTE = "updated_by_remote"
    RELEASED = "released"
    ERROR = "error"
    END = "end"


class MessageKind(Enum):
    """Kinds of VoIP messages handled by the Liblinphone backend."""

    TEXT = "text"
    VOICE_NOTE = "voice_note"


class MessageDirection(Enum):
    """Direction of a VoIP message relative to the local endpoint."""

    INCOMING = "incoming"
    OUTGOING = "outgoing"


class MessageDeliveryState(Enum):
    """Delivery state for one VoIP message."""

    QUEUED = "queued"
    SENDING = "sending"
    SENT = "sent"
    DELIVERED = "delivered"
    FAILED = "failed"


@dataclass(slots=True)
class VoIPConfig:
    """Runtime communication config passed into the Liblinphone-backed service."""

    sip_server: str = "sip.linphone.org"
    sip_username: str = ""
    sip_password: str = ""
    sip_password_ha1: str = ""
    sip_identity: str = ""
    factory_config_path: str = "config/communication/integrations/liblinphone_factory.conf"
    transport: str = "tcp"
    stun_server: str = ""
    conference_factory_uri: str = ""
    file_transfer_server_url: str = ""
    lime_server_url: str = ""
    iterate_interval_ms: int = 20
    message_store_dir: str = "data/communication/messages"
    voice_note_store_dir: str = "data/communication/voice_notes"
    call_history_file: str = "data/communication/call_history.json"
    voice_note_max_duration_seconds: int = 30
    auto_download_incoming_voice_recordings: bool = True
    playback_dev_id: str = "ALSA: wm8960-soundcard"
    ringer_dev_id: str = "ALSA: wm8960-soundcard"
    capture_dev_id: str = "ALSA: wm8960-soundcard"
    media_dev_id: str = "ALSA: wm8960-soundcard"
    mic_gain: int = 80
    output_volume: int = 100

    @staticmethod
    def from_config_manager(config_manager) -> "VoIPConfig":
        """Create a VoIPConfig from the current config manager."""

        return VoIPConfig(
            sip_server=config_manager.get_sip_server(),
            sip_username=config_manager.get_sip_username(),
            sip_password=config_manager.get_sip_password(),
            sip_password_ha1=config_manager.get_sip_password_ha1(),
            sip_identity=config_manager.get_sip_identity(),
            factory_config_path=str(
                config_manager.resolve_runtime_path(config_manager.get_voip_factory_config_path())
            ),
            transport=config_manager.get_transport(),
            stun_server=config_manager.get_stun_server(),
            conference_factory_uri=config_manager.get_conference_factory_uri(),
            file_transfer_server_url=config_manager.get_file_transfer_server_url(),
            lime_server_url=config_manager.get_lime_server_url(),
            iterate_interval_ms=config_manager.get_voip_iterate_interval_ms(),
            message_store_dir=str(
                config_manager.resolve_runtime_path(config_manager.get_message_store_dir())
            ),
            voice_note_store_dir=str(
                config_manager.resolve_runtime_path(config_manager.get_voice_note_store_dir())
            ),
            call_history_file=str(
                config_manager.resolve_runtime_path(config_manager.get_call_history_file())
            ),
            voice_note_max_duration_seconds=config_manager.get_voice_note_max_duration_seconds(),
            auto_download_incoming_voice_recordings=(
                config_manager.get_auto_download_incoming_voice_recordings()
            ),
            playback_dev_id=config_manager.get_playback_device_id(),
            ringer_dev_id=config_manager.get_ringer_device_id(),
            capture_dev_id=config_manager.get_capture_device_id(),
            media_dev_id=config_manager.get_media_device_id(),
            mic_gain=config_manager.get_mic_gain(),
            output_volume=config_manager.get_default_output_volume(),
        )

    def is_linphone_hosted(self) -> bool:
        """Return whether this config targets the default Linphone hosted SIP service."""

        return self.sip_server.strip().lower() == LINPHONE_HOSTED_SIP_SERVER

    def is_backend_start_configured(self) -> bool:
        """Return whether the native backend has the minimum required startup config."""

        return bool(self.sip_server.strip()) and bool(self.sip_identity.strip())

    def effective_file_transfer_server_url(self) -> str:
        """Return the configured or inferred file-transfer endpoint."""

        configured = self.file_transfer_server_url.strip()
        if configured:
            return configured
        if self.is_linphone_hosted():
            return LINPHONE_HOSTED_FILE_TRANSFER_SERVER_URL
        return ""

    def effective_conference_factory_uri(self) -> str:
        """Return the configured or inferred conference-factory URI."""

        configured = self.conference_factory_uri.strip()
        if configured:
            return configured
        if self.is_linphone_hosted():
            return LINPHONE_HOSTED_CONFERENCE_FACTORY_URI
        return ""

    def effective_lime_server_url(self) -> str:
        """Return the configured or inferred LIME/X3DH endpoint."""

        configured = self.lime_server_url.strip()
        if configured:
            return configured
        if self.is_linphone_hosted():
            return LINPHONE_HOSTED_LIME_SERVER_URL
        return ""


@dataclass(frozen=True, slots=True)
class VoIPMessageRecord:
    """One text or voice-note message known to the local endpoint."""

    id: str
    peer_sip_address: str
    sender_sip_address: str
    recipient_sip_address: str
    kind: MessageKind
    direction: MessageDirection
    delivery_state: MessageDeliveryState
    created_at: str
    updated_at: str
    text: str = ""
    local_file_path: str = ""
    mime_type: str = ""
    duration_ms: int = 0
    unread: bool = False
    display_name: str = ""


@dataclass(frozen=True, slots=True)
class VoIPLifecycleSnapshot:
    """Rust-owned VoIP host lifecycle facts."""

    state: str = "unconfigured"
    reason: str = ""
    backend_available: bool = False


@dataclass(frozen=True, slots=True)
class VoIPVoiceNoteSnapshot:
    """Rust-owned active voice-note facts."""

    state: str = "idle"
    file_path: str = ""
    duration_ms: int = 0
    mime_type: str = ""
    message_id: str = ""


@dataclass(frozen=True, slots=True)
class VoIPMessageSnapshot:
    """Rust-owned last-message facts from the VoIP worker."""

    message_id: str
    kind: MessageKind | None = None
    direction: MessageDirection | None = None
    delivery_state: MessageDeliveryState | None = None
    local_file_path: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class VoIPCallSessionSnapshot:
    """Rust-owned call-session facts used for app side effects and history."""

    active: bool = False
    session_id: str = ""
    direction: str = ""
    peer_sip_address: str = ""
    answered: bool = False
    terminal_state: str = ""
    local_end_action: str = ""
    duration_seconds: int = 0
    history_outcome: str = ""


@dataclass(frozen=True, slots=True)
class VoIPRuntimeSnapshot:
    """Canonical live VoIP state reported by the Rust worker."""

    configured: bool = False
    registered: bool = False
    registration_state: RegistrationState = RegistrationState.NONE
    call_state: CallState = CallState.IDLE
    active_call_id: str = ""
    active_call_peer: str = ""
    muted: bool = False
    pending_outbound_messages: int = 0
    unread_voice_notes: int = 0
    unread_voice_notes_by_contact: dict[str, int] = field(default_factory=dict)
    latest_voice_note_by_contact: dict[str, dict[str, object]] = field(default_factory=dict)
    lifecycle: VoIPLifecycleSnapshot = field(default_factory=VoIPLifecycleSnapshot)
    call_session: VoIPCallSessionSnapshot = field(default_factory=VoIPCallSessionSnapshot)
    voice_note: VoIPVoiceNoteSnapshot = field(default_factory=VoIPVoiceNoteSnapshot)
    last_message: VoIPMessageSnapshot | None = None


@dataclass(frozen=True, slots=True)
class RegistrationStateChanged:
    """Typed event emitted when SIP registration changes."""

    state: RegistrationState


@dataclass(frozen=True, slots=True)
class CallStateChanged:
    """Typed event emitted when the active call state changes."""

    state: CallState


@dataclass(frozen=True, slots=True)
class IncomingCallDetected:
    """Typed event emitted when an incoming call address is detected."""

    caller_address: str


@dataclass(frozen=True, slots=True)
class BackendStopped:
    """Typed event emitted when the backend process exits unexpectedly."""

    reason: str = ""


@dataclass(frozen=True, slots=True)
class BackendRecovered:
    """Typed event emitted when a stopped backend becomes usable again."""

    reason: str = "backend_recovered"


@dataclass(frozen=True, slots=True)
class MessageReceived:
    """Typed event emitted when a new message is received."""

    message: VoIPMessageRecord


@dataclass(frozen=True, slots=True)
class MessageDeliveryChanged:
    """Typed event emitted when one message delivery state changes."""

    message_id: str
    delivery_state: MessageDeliveryState
    local_file_path: str = ""
    error: str = ""


@dataclass(frozen=True, slots=True)
class MessageDownloadCompleted:
    """Typed event emitted when an incoming message attachment finishes downloading."""

    message_id: str
    local_file_path: str
    mime_type: str = ""


@dataclass(frozen=True, slots=True)
class MessageFailed:
    """Typed event emitted when a message send or receive operation fails."""

    message_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class VoIPRuntimeSnapshotChanged:
    """Typed event emitted when Rust reports its canonical runtime snapshot."""

    snapshot: VoIPRuntimeSnapshot


VoIPEvent: TypeAlias = (
    RegistrationStateChanged
    | CallStateChanged
    | IncomingCallDetected
    | BackendStopped
    | BackendRecovered
    | MessageReceived
    | MessageDeliveryChanged
    | MessageDownloadCompleted
    | MessageFailed
    | VoIPRuntimeSnapshotChanged
)
