"""Direct Rust VoIP worker client for CLI diagnostics and validation."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, TextIO

from loguru import logger

from yoyopod_cli.common import REPO_ROOT, resolve_config_dir
from yoyopod_cli.contracts.worker_protocol import (
    WorkerEnvelope,
    encode_envelope,
    make_envelope,
    parse_envelope_line,
)

LINPHONE_HOSTED_SIP_SERVER = "sip.linphone.org"
LINPHONE_HOSTED_CONFERENCE_FACTORY_URI = "sip:conference-factory@sip.linphone.org"
LINPHONE_HOSTED_FILE_TRANSFER_SERVER_URL = "https://files.linphone.org/lft.php"
LINPHONE_HOSTED_LIME_SERVER_URL = "https://lime.linphone.org/lime-server/lime-server.php"


class RegistrationState(Enum):
    NONE = "none"
    PROGRESS = "progress"
    OK = "ok"
    CLEARED = "cleared"
    FAILED = "failed"


class CallState(Enum):
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


@dataclass(slots=True)
class VoIPConfig:
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
    auto_download_incoming_voice_recordings: bool = True
    playback_dev_id: str = "ALSA: wm8960-soundcard"
    ringer_dev_id: str = "ALSA: wm8960-soundcard"
    capture_dev_id: str = "ALSA: wm8960-soundcard"
    media_dev_id: str = "ALSA: wm8960-soundcard"
    mic_gain: int = 80
    output_volume: int = 100

    @staticmethod
    def from_config_dir(config_dir: str | Path) -> "VoIPConfig":
        from yoyopod_cli.config import ConfigManager

        config_manager = ConfigManager(config_dir=str(resolve_config_dir(str(config_dir))))
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

    def is_backend_start_configured(self) -> bool:
        return bool(self.sip_server.strip()) and bool(self.sip_identity.strip())

    def worker_payload(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["conference_factory_uri"] = self._effective_conference_factory_uri()
        payload["file_transfer_server_url"] = self._effective_file_transfer_server_url()
        payload["lime_server_url"] = self._effective_lime_server_url()
        return payload

    def _is_linphone_hosted(self) -> bool:
        return self.sip_server.strip().lower() == LINPHONE_HOSTED_SIP_SERVER

    def _effective_conference_factory_uri(self) -> str:
        configured = self.conference_factory_uri.strip()
        if configured:
            return configured
        return LINPHONE_HOSTED_CONFERENCE_FACTORY_URI if self._is_linphone_hosted() else ""

    def _effective_file_transfer_server_url(self) -> str:
        configured = self.file_transfer_server_url.strip()
        if configured:
            return configured
        return LINPHONE_HOSTED_FILE_TRANSFER_SERVER_URL if self._is_linphone_hosted() else ""

    def _effective_lime_server_url(self) -> str:
        configured = self.lime_server_url.strip()
        if configured:
            return configured
        return LINPHONE_HOSTED_LIME_SERVER_URL if self._is_linphone_hosted() else ""


@dataclass(frozen=True, slots=True)
class VoIPLifecycleSnapshot:
    state: str = "unconfigured"
    reason: str = ""
    backend_available: bool = False


@dataclass(frozen=True, slots=True)
class VoIPCallSessionSnapshot:
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
    configured: bool = False
    registered: bool = False
    registration_state: RegistrationState = RegistrationState.NONE
    call_state: CallState = CallState.IDLE
    active_call_id: str = ""
    active_call_peer: str = ""
    muted: bool = False
    lifecycle: VoIPLifecycleSnapshot = field(default_factory=VoIPLifecycleSnapshot)
    call_session: VoIPCallSessionSnapshot = field(default_factory=VoIPCallSessionSnapshot)


class RustVoipWorkerClient:
    """Small direct client for the Rust VoIP host NDJSON protocol."""

    def __init__(
        self,
        config: VoIPConfig,
        *,
        worker_path: str | None = None,
        cwd: Path = REPO_ROOT,
    ) -> None:
        self.config = config
        self.worker_path = worker_path or rust_voip_worker_path()
        self.cwd = cwd
        self.running = False
        self._process: subprocess.Popen[str] | None = None
        self._stdout_queue: queue.Queue[str | None] = queue.Queue()
        self._stderr_queue: queue.Queue[str | None] = queue.Queue()
        self._registration_callbacks: list[Callable[[RegistrationState], None]] = []
        self._snapshot_callbacks: list[Callable[[VoIPRuntimeSnapshot], None]] = []
        self._snapshot = VoIPRuntimeSnapshot()
        self._last_error = ""
        self._request_counter = 0

    def start(self) -> bool:
        if self.running:
            return True
        if not self.config.is_backend_start_configured():
            logger.error("Rust VoIP worker requires sip_server and sip_identity")
            return False

        worker = _resolve_worker_path(self.worker_path)
        if not worker.is_file():
            raise RuntimeError(_missing_artifact_message(worker))

        self._process = subprocess.Popen(
            [str(worker)],
            cwd=str(self.cwd),
            env=os.environ.copy(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert self._process.stdout is not None
        assert self._process.stderr is not None
        threading.Thread(
            target=_read_lines,
            args=(self._process.stdout, self._stdout_queue),
            daemon=True,
        ).start()
        threading.Thread(
            target=_read_lines,
            args=(self._process.stderr, self._stderr_queue),
            daemon=True,
        ).start()

        self.running = True
        if not self._wait_for_ready(timeout=2.0):
            self.stop()
            return False
        return self._send("voip.configure", self.config.worker_payload()) and self._send(
            "voip.register", {}
        )

    def stop(self) -> None:
        process = self._process
        if process is None:
            self.running = False
            return
        try:
            if process.poll() is None:
                self._send("voip.unregister", {})
                self._send("worker.stop", {})
                try:
                    process.wait(timeout=1.0)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    try:
                        process.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
        finally:
            self.iterate()
            self._process = None
            self.running = False

    def iterate(self) -> int:
        drained = 0
        while True:
            try:
                line = self._stdout_queue.get_nowait()
            except queue.Empty:
                break
            if line is None:
                self.running = False
                continue
            drained += 1
            self._handle_stdout_line(line)
        while True:
            try:
                line = self._stderr_queue.get_nowait()
            except queue.Empty:
                break
            if line:
                logger.debug("Rust VoIP worker stderr: {}", line.rstrip())
        process = self._process
        if process is not None and process.poll() is not None:
            self.running = False
        return drained

    def get_status(self) -> dict[str, Any]:
        self.iterate()
        return {
            "running": self.running,
            "registered": self._snapshot.registered,
            "registration_state": self._snapshot.registration_state.value,
            "call_state": self._snapshot.call_state.value,
            "call_id": self._snapshot.active_call_id,
            "sip_identity": self.config.sip_identity,
            "last_error": self._last_error,
        }

    def get_iterate_metrics(self) -> object | None:
        return None

    def on_registration_change(self, callback: Callable[[RegistrationState], None]) -> None:
        self._registration_callbacks.append(callback)

    def on_runtime_snapshot_change(
        self,
        callback: Callable[[VoIPRuntimeSnapshot], None],
    ) -> None:
        self._snapshot_callbacks.append(callback)

    def make_call(self, sip_address: str, contact_name: str | None = None) -> bool:
        del contact_name
        return self._send("voip.dial", {"uri": sip_address})

    def hangup(self) -> bool:
        return self._send("voip.hangup", {})

    def get_call_duration(self) -> int:
        return self._snapshot.call_session.duration_seconds

    def _wait_for_ready(self, *, timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() <= deadline:
            self.iterate()
            if self._process is not None and self._process.poll() is not None:
                return False
            if self._snapshot.lifecycle.state == "ready":
                return True
            time.sleep(0.02)
        return False

    def _send(self, message_type: str, payload: dict[str, Any]) -> bool:
        process = self._process
        if process is None or process.stdin is None or process.poll() is not None:
            self.running = False
            return False
        self._request_counter += 1
        request_id = f"cli-{self._request_counter}-{uuid.uuid4().hex[:8]}"
        envelope = make_envelope(
            kind="command",
            type=message_type,
            request_id=request_id,
            payload=payload,
        )
        try:
            process.stdin.write(encode_envelope(envelope))
            process.stdin.flush()
        except OSError as exc:
            self._last_error = str(exc)
            self.running = False
            return False
        return True

    def _handle_stdout_line(self, line: str) -> None:
        try:
            envelope = parse_envelope_line(line)
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("Ignoring invalid Rust VoIP worker line: {}", exc)
            return
        if envelope.kind == "error":
            self._last_error = _worker_error_reason(envelope)
            logger.warning("Rust VoIP worker error: {}", self._last_error)
            return
        if envelope.type == "voip.ready":
            self._snapshot = _snapshot_from_payload(
                {
                    "lifecycle": {
                        "state": "ready",
                        "reason": "worker_ready",
                        "backend_available": False,
                    },
                    "registration_state": self._snapshot.registration_state.value,
                    "call_state": self._snapshot.call_state.value,
                    "registered": self._snapshot.registered,
                }
            )
            return
        if envelope.type == "voip.registration_changed":
            state = _registration_state(str(envelope.payload.get("state", "")))
            self._snapshot = _snapshot_from_payload(
                {
                    **_snapshot_payload(self._snapshot),
                    "registration_state": state.value,
                    "registered": state == RegistrationState.OK,
                }
            )
            self._notify_registration(state)
            return
        if envelope.type == "voip.call_state_changed":
            call_state = _call_state(str(envelope.payload.get("state", "")))
            self._snapshot = _snapshot_from_payload(
                {
                    **_snapshot_payload(self._snapshot),
                    "call_state": call_state.value,
                    "active_call_id": str(envelope.payload.get("call_id", "") or ""),
                }
            )
            self._notify_snapshot()
            return
        if envelope.type == "voip.lifecycle_changed":
            payload = dict(envelope.payload)
            self._snapshot = _snapshot_from_payload(
                {**_snapshot_payload(self._snapshot), "lifecycle": payload}
            )
            self._notify_snapshot()
            return
        if envelope.type == "voip.snapshot":
            self._snapshot = _snapshot_from_payload(envelope.payload)
            self._notify_registration(self._snapshot.registration_state)
            self._notify_snapshot()

    def _notify_registration(self, state: RegistrationState) -> None:
        for callback in list(self._registration_callbacks):
            callback(state)

    def _notify_snapshot(self) -> None:
        for callback in list(self._snapshot_callbacks):
            callback(self._snapshot)


def build_rust_voip_client(config_dir: str) -> RustVoipWorkerClient:
    assert_rust_voip_artifacts_present()
    return RustVoipWorkerClient(VoIPConfig.from_config_dir(config_dir))


def rust_voip_worker_path() -> str:
    return os.environ.get(
        "YOYOPOD_RUST_VOIP_HOST_WORKER",
        "device/voip/build/yoyopod-voip-host",
    ).strip()


def assert_rust_voip_artifacts_present() -> None:
    worker = _resolve_worker_path(rust_voip_worker_path())
    if not worker.is_file():
        raise RuntimeError(_missing_artifact_message(worker))


def _resolve_worker_path(worker_path: str) -> Path:
    path = Path(worker_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    return path


def _missing_artifact_message(path: Path) -> str:
    return (
        "Rust VoIP host artifact is missing. Download the GitHub Actions artifact "
        "for the exact commit under test; do not build Rust binaries on the Pi.\n"
        f"- {path}"
    )


def _read_lines(stream: TextIO, out: queue.Queue[str | None]) -> None:
    try:
        for line in stream:
            out.put(line)
    finally:
        out.put(None)


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


def _snapshot_from_payload(payload: dict[str, Any]) -> VoIPRuntimeSnapshot:
    lifecycle_raw = _dict_payload(payload.get("lifecycle"))
    call_session_raw = _dict_payload(payload.get("call_session"))
    return VoIPRuntimeSnapshot(
        configured=bool(payload.get("configured", False)),
        registered=bool(payload.get("registered", False)),
        registration_state=_registration_state(str(payload.get("registration_state", "none"))),
        call_state=_call_state(str(payload.get("call_state", "idle"))),
        active_call_id=str(payload.get("active_call_id", "") or ""),
        active_call_peer=str(payload.get("active_call_peer", "") or ""),
        muted=bool(payload.get("muted", False)),
        lifecycle=VoIPLifecycleSnapshot(
            state=str(lifecycle_raw.get("state", "unconfigured") or "unconfigured"),
            reason=str(lifecycle_raw.get("reason", "") or ""),
            backend_available=bool(lifecycle_raw.get("backend_available", False)),
        ),
        call_session=VoIPCallSessionSnapshot(
            active=bool(call_session_raw.get("active", False)),
            session_id=str(call_session_raw.get("session_id", "") or ""),
            direction=str(call_session_raw.get("direction", "") or ""),
            peer_sip_address=str(call_session_raw.get("peer_sip_address", "") or ""),
            answered=bool(call_session_raw.get("answered", False)),
            terminal_state=str(call_session_raw.get("terminal_state", "") or ""),
            local_end_action=str(call_session_raw.get("local_end_action", "") or ""),
            duration_seconds=int(call_session_raw.get("duration_seconds", 0) or 0),
            history_outcome=str(call_session_raw.get("history_outcome", "") or ""),
        ),
    )


def _snapshot_payload(snapshot: VoIPRuntimeSnapshot) -> dict[str, Any]:
    return {
        "configured": snapshot.configured,
        "registered": snapshot.registered,
        "registration_state": snapshot.registration_state.value,
        "call_state": snapshot.call_state.value,
        "active_call_id": snapshot.active_call_id,
        "active_call_peer": snapshot.active_call_peer,
        "muted": snapshot.muted,
        "lifecycle": asdict(snapshot.lifecycle),
        "call_session": asdict(snapshot.call_session),
    }


def _dict_payload(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _worker_error_reason(envelope: WorkerEnvelope) -> str:
    code = str(envelope.payload.get("code", "") or "")
    message = str(envelope.payload.get("message", "") or "")
    if code and message:
        return f"{code}: {message}"
    return message or code or envelope.type
