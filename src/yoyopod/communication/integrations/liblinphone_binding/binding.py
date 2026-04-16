"""Low-level cffi binding for the native YoyoPod Liblinphone shim."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from cffi import FFI
from loguru import logger

SHIM_CDEF = """
typedef struct {
    int32_t type;
    int32_t registration_state;
    int32_t call_state;
    int32_t message_kind;
    int32_t message_direction;
    int32_t message_delivery_state;
    int32_t duration_ms;
    int32_t unread;
    char message_id[128];
    char peer_sip_address[256];
    char sender_sip_address[256];
    char recipient_sip_address[256];
    char local_file_path[512];
    char mime_type[128];
    char text[1024];
    char reason[256];
} yoyopod_liblinphone_event_t;

int yoyopod_liblinphone_init(void);
void yoyopod_liblinphone_shutdown(void);
int yoyopod_liblinphone_start(
    const char * sip_server,
    const char * sip_username,
    const char * sip_password,
    const char * sip_password_ha1,
    const char * sip_identity,
    const char * factory_config_path,
    const char * transport,
    const char * stun_server,
    const char * conference_factory_uri,
    const char * file_transfer_server_url,
    const char * lime_server_url,
    int32_t auto_download_incoming_voice_recordings,
    const char * playback_device_id,
    const char * ringer_device_id,
    const char * capture_device_id,
    const char * media_device_id,
    int32_t echo_cancellation,
    int32_t mic_gain,
    int32_t output_volume,
    const char * voice_note_store_dir
);
void yoyopod_liblinphone_stop(void);
void yoyopod_liblinphone_iterate(void);
int yoyopod_liblinphone_poll_event(yoyopod_liblinphone_event_t * event_out);
int yoyopod_liblinphone_make_call(const char * sip_address);
int yoyopod_liblinphone_answer_call(void);
int yoyopod_liblinphone_reject_call(void);
int yoyopod_liblinphone_hangup(void);
int yoyopod_liblinphone_set_muted(int32_t muted);
int yoyopod_liblinphone_send_text_message(
    const char * sip_address,
    const char * text,
    char * message_id_out,
    uint32_t message_id_out_size
);
int yoyopod_liblinphone_start_voice_recording(const char * file_path);
int yoyopod_liblinphone_stop_voice_recording(int32_t * duration_ms_out);
int yoyopod_liblinphone_cancel_voice_recording(void);
int yoyopod_liblinphone_send_voice_note(
    const char * sip_address,
    const char * file_path,
    int32_t duration_ms,
    const char * mime_type,
    char * message_id_out,
    uint32_t message_id_out_size
);
const char * yoyopod_liblinphone_last_error(void);
const char * yoyopod_liblinphone_version(void);
"""


@dataclass(frozen=True, slots=True)
class LiblinphoneNativeEvent:
    """One event drained from the native Liblinphone shim queue."""

    type: int
    registration_state: int
    call_state: int
    message_kind: int
    message_direction: int
    message_delivery_state: int
    duration_ms: int
    unread: int
    message_id: str
    peer_sip_address: str
    sender_sip_address: str
    recipient_sip_address: str
    local_file_path: str
    mime_type: str
    text: str
    reason: str


class LiblinphoneBindingError(RuntimeError):
    """Raised when the native Liblinphone shim is unavailable or fails."""


class LiblinphoneBinding:
    """Thin ABI-mode wrapper over the native Liblinphone shim."""

    def __init__(self, library_path: Path | None = None) -> None:
        self.ffi = FFI()
        self.ffi.cdef(SHIM_CDEF)
        self.library_path = library_path or self._resolve_library_path()
        if self.library_path is None:
            raise LiblinphoneBindingError(
                "Liblinphone shim library not found; run scripts/liblinphone_build.py on the target platform",
            )
        self.lib = self.ffi.dlopen(str(self.library_path))
        logger.info("Loaded Liblinphone shim from {}", self.library_path)

    @classmethod
    def try_load(cls, library_path: Path | None = None) -> "LiblinphoneBinding | None":
        """Attempt to load the native shim without raising."""

        try:
            return cls(library_path=library_path)
        except Exception as exc:
            logger.debug("Liblinphone shim not available: {}", exc)
            return None

    def _resolve_library_path(self) -> Path | None:
        env_override = os.getenv("YOYOPOD_LIBLINPHONE_SHIM_PATH")
        candidates: list[Path] = []
        if env_override:
            candidates.append(Path(env_override))

        base_dir = Path(__file__).resolve().parent
        candidates.extend(
            [
                base_dir / "native" / "build" / "libyoyopod_liblinphone_shim.so",
                base_dir / "native" / "build" / "yoyopod_liblinphone_shim.dll",
                base_dir / "native" / "build" / "libyoyopod_liblinphone_shim.dylib",
                Path.cwd() / "build" / "liblinphone" / "libyoyopod_liblinphone_shim.so",
            ]
        )

        for candidate in candidates:
            if candidate.exists():
                return candidate
        return None

    def init(self) -> None:
        if self.lib.yoyopod_liblinphone_init() != 0:
            raise LiblinphoneBindingError(self.last_error())

    def shutdown(self) -> None:
        self.lib.yoyopod_liblinphone_shutdown()

    def start(
        self,
        *,
        sip_server: str,
        sip_username: str,
        sip_password: str,
        sip_password_ha1: str,
        sip_identity: str,
        factory_config_path: str,
        transport: str,
        stun_server: str,
        conference_factory_uri: str,
        file_transfer_server_url: str,
        lime_server_url: str,
        auto_download_incoming_voice_recordings: bool,
        playback_device_id: str,
        ringer_device_id: str,
        capture_device_id: str,
        media_device_id: str,
        echo_cancellation: bool,
        mic_gain: int,
        output_volume: int,
        voice_note_store_dir: str,
    ) -> None:
        result = self.lib.yoyopod_liblinphone_start(
            self._char_arg(sip_server),
            self._char_arg(sip_username),
            self._char_arg(sip_password),
            self._char_arg(sip_password_ha1),
            self._char_arg(sip_identity),
            self._char_arg(factory_config_path),
            self._char_arg(transport),
            self._char_arg(stun_server),
            self._char_arg(conference_factory_uri),
            self._char_arg(file_transfer_server_url),
            self._char_arg(lime_server_url),
            1 if auto_download_incoming_voice_recordings else 0,
            self._char_arg(playback_device_id),
            self._char_arg(ringer_device_id),
            self._char_arg(capture_device_id),
            self._char_arg(media_device_id),
            1 if echo_cancellation else 0,
            int(mic_gain),
            int(output_volume),
            self._char_arg(voice_note_store_dir),
        )
        if result != 0:
            raise LiblinphoneBindingError(self.last_error())

    def stop(self) -> None:
        self.lib.yoyopod_liblinphone_stop()

    def iterate(self) -> None:
        self.lib.yoyopod_liblinphone_iterate()

    def poll_event(self) -> LiblinphoneNativeEvent | None:
        event_buffer = self.ffi.new("yoyopod_liblinphone_event_t *")
        if self.lib.yoyopod_liblinphone_poll_event(event_buffer) == 0:
            return None

        event = event_buffer[0]
        return LiblinphoneNativeEvent(
            type=int(event.type),
            registration_state=int(event.registration_state),
            call_state=int(event.call_state),
            message_kind=int(event.message_kind),
            message_direction=int(event.message_direction),
            message_delivery_state=int(event.message_delivery_state),
            duration_ms=int(event.duration_ms),
            unread=int(event.unread),
            message_id=self._decode_c_string(event.message_id),
            peer_sip_address=self._decode_c_string(event.peer_sip_address),
            sender_sip_address=self._decode_c_string(event.sender_sip_address),
            recipient_sip_address=self._decode_c_string(event.recipient_sip_address),
            local_file_path=self._decode_c_string(event.local_file_path),
            mime_type=self._decode_c_string(event.mime_type),
            text=self._decode_c_string(event.text),
            reason=self._decode_c_string(event.reason),
        )

    def make_call(self, sip_address: str) -> None:
        if self.lib.yoyopod_liblinphone_make_call(self._char_arg(sip_address)) != 0:
            raise LiblinphoneBindingError(self.last_error())

    def answer_call(self) -> None:
        if self.lib.yoyopod_liblinphone_answer_call() != 0:
            raise LiblinphoneBindingError(self.last_error())

    def reject_call(self) -> None:
        if self.lib.yoyopod_liblinphone_reject_call() != 0:
            raise LiblinphoneBindingError(self.last_error())

    def hangup(self) -> None:
        if self.lib.yoyopod_liblinphone_hangup() != 0:
            raise LiblinphoneBindingError(self.last_error())

    def set_muted(self, muted: bool) -> None:
        if self.lib.yoyopod_liblinphone_set_muted(1 if muted else 0) != 0:
            raise LiblinphoneBindingError(self.last_error())

    def send_text_message(self, sip_address: str, text: str) -> str:
        message_id_out = self.ffi.new("char[]", 128)
        if (
            self.lib.yoyopod_liblinphone_send_text_message(
                self._char_arg(sip_address),
                self._char_arg(text),
                message_id_out,
                128,
            )
            != 0
        ):
            raise LiblinphoneBindingError(self.last_error())
        return self.ffi.string(message_id_out).decode("utf-8", errors="replace")

    def start_voice_recording(self, file_path: str) -> None:
        if self.lib.yoyopod_liblinphone_start_voice_recording(self._char_arg(file_path)) != 0:
            raise LiblinphoneBindingError(self.last_error())

    def stop_voice_recording(self) -> int:
        duration_out = self.ffi.new("int32_t *")
        if self.lib.yoyopod_liblinphone_stop_voice_recording(duration_out) != 0:
            raise LiblinphoneBindingError(self.last_error())
        return int(duration_out[0])

    def cancel_voice_recording(self) -> None:
        if self.lib.yoyopod_liblinphone_cancel_voice_recording() != 0:
            raise LiblinphoneBindingError(self.last_error())

    def send_voice_note(
        self,
        sip_address: str,
        *,
        file_path: str,
        duration_ms: int,
        mime_type: str,
    ) -> str:
        message_id_out = self.ffi.new("char[]", 128)
        if (
            self.lib.yoyopod_liblinphone_send_voice_note(
                self._char_arg(sip_address),
                self._char_arg(file_path),
                int(duration_ms),
                self._char_arg(mime_type),
                message_id_out,
                128,
            )
            != 0
        ):
            raise LiblinphoneBindingError(self.last_error())
        return self.ffi.string(message_id_out).decode("utf-8", errors="replace")

    def last_error(self) -> str:
        raw = self.lib.yoyopod_liblinphone_last_error()
        if raw == self.ffi.NULL:
            return "unknown Liblinphone shim error"
        return self.ffi.string(raw).decode("utf-8", errors="replace")

    def version(self) -> str:
        raw = self.lib.yoyopod_liblinphone_version()
        if raw == self.ffi.NULL:
            return "unknown"
        return self.ffi.string(raw).decode("utf-8", errors="replace")

    def _char_arg(self, value: str | None):
        if not value:
            return self.ffi.NULL
        return self.ffi.new("char[]", value.encode("utf-8"))

    def _decode_c_string(self, buffer: object) -> str:
        return self.ffi.string(buffer).decode("utf-8", errors="replace")
