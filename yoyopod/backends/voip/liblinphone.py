"""Liblinphone-backed VoIP implementation."""

from __future__ import annotations

import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from loguru import logger

from yoyopod.backends.voip.protocol import VoIPIterateMetrics
from yoyopod.backends.voip.binding import (
    LiblinphoneBinding,
    LiblinphoneNativeEvent,
)
from yoyopod.integrations.call.models import (
    BackendStopped,
    CallState,
    CallStateChanged,
    IncomingCallDetected,
    MessageDeliveryChanged,
    MessageDirection,
    MessageDownloadCompleted,
    MessageFailed,
    MessageKind,
    MessageReceived,
    MessageDeliveryState,
    RegistrationState,
    RegistrationStateChanged,
    VoIPConfig,
    VoIPEvent,
    VoIPMessageRecord,
)


@dataclass(slots=True)
class _AlsaCaptureConfig:
    capture_raw: int


class LiblinphoneBackend:
    """Production VoIP backend driven by the native Liblinphone shim."""

    _MIN_NATIVE_ITERATE_WARNING_SECONDS = 0.15
    _MIN_EVENT_DRAIN_WARNING_SECONDS = 0.1

    def __init__(
        self,
        config: VoIPConfig,
        *,
        binding: LiblinphoneBinding | None = None,
    ) -> None:
        self.config = config
        self.binding = binding or LiblinphoneBinding.try_load()
        self.running = False
        self.event_callbacks: list[Callable[[VoIPEvent], None]] = []
        self._last_iterate_metrics: VoIPIterateMetrics | None = None
        self._binding_lock = threading.Lock()

    def on_event(self, callback: Callable[[VoIPEvent], None]) -> None:
        self.event_callbacks.append(callback)

    def start(self) -> bool:
        if self.running:
            return True

        if self.binding is None:
            logger.error("Liblinphone backend requested but native shim is unavailable")
            return False

        try:
            factory_config_path = self._resolve_factory_config_path()
            conference_factory_uri = self.config.effective_conference_factory_uri()
            file_transfer_server_url = self.config.effective_file_transfer_server_url()
            lime_server_url = self.config.effective_lime_server_url()
            with self._binding_lock:
                self.binding.init()
                self._configure_alsa_capture_path()
                if not self.config.conference_factory_uri and conference_factory_uri:
                    logger.info(
                        "Using inferred conference factory {} for hosted account {}",
                        conference_factory_uri,
                        self.config.sip_server,
                    )
                if not self.config.file_transfer_server_url and file_transfer_server_url:
                    logger.info(
                        "Using inferred file-transfer server {} for hosted account {}",
                        file_transfer_server_url,
                        self.config.sip_server,
                    )
                if not self.config.lime_server_url and lime_server_url:
                    logger.info(
                        "Using inferred LIME server {} for hosted account {}",
                        lime_server_url,
                        self.config.sip_server,
                    )
                self.binding.start(
                    sip_server=self.config.sip_server,
                    sip_username=self.config.sip_username,
                    sip_password=self.config.sip_password,
                    sip_password_ha1=self.config.sip_password_ha1,
                    sip_identity=self.config.sip_identity,
                    factory_config_path=factory_config_path,
                    transport=self.config.transport,
                    stun_server=self.config.stun_server,
                    conference_factory_uri=conference_factory_uri,
                    file_transfer_server_url=file_transfer_server_url,
                    lime_server_url=lime_server_url,
                    auto_download_incoming_voice_recordings=(
                        self.config.auto_download_incoming_voice_recordings
                    ),
                    playback_device_id=self.config.playback_dev_id,
                    ringer_device_id=self.config.ringer_dev_id,
                    capture_device_id=self.config.capture_dev_id,
                    media_device_id=self.config.media_dev_id,
                    echo_cancellation=True,
                    mic_gain=self._linphone_software_mic_gain(),
                    output_volume=self.config.output_volume,
                    voice_note_store_dir=self.config.voice_note_store_dir,
                )
            self.running = True
            logger.info("Liblinphone backend started successfully")
            return True
        except Exception as exc:
            logger.error("Failed to start Liblinphone backend: {}", exc)
            try:
                if self.binding is not None:
                    self.binding.shutdown()
            except Exception:
                logger.debug("Liblinphone shutdown after failed start also failed")
            self.running = False
            return False

    def _resolve_factory_config_path(self) -> str:
        path = Path(self.config.factory_config_path)
        if not path.is_absolute():
            repo_root = Path(__file__).resolve().parents[3]
            candidate = repo_root / path
            path = candidate if candidate.exists() else (Path.cwd() / path)
        if not path.exists():
            logger.warning("Liblinphone factory config not found at {}", path)
            return ""
        return str(path)

    def stop(self) -> None:
        if self.binding is None:
            self.running = False
            return

        try:
            with self._binding_lock:
                self.binding.stop()
        finally:
            with self._binding_lock:
                self.binding.shutdown()
            self.running = False

    def get_iterate_metrics(self) -> VoIPIterateMetrics | None:
        """Return the latest native keep-alive timing sample."""

        return self._last_iterate_metrics

    def iterate(self) -> int:
        if not self.running or self.binding is None:
            return 0

        drained_events = 0
        started_at = time.monotonic()
        native_duration_seconds = 0.0
        event_drain_started_at = started_at
        native_events: list[LiblinphoneNativeEvent] = []
        try:
            native_started_at = time.monotonic()
            with self._binding_lock:
                self.binding.iterate()
                native_duration_seconds = max(0.0, time.monotonic() - native_started_at)
                event_drain_started_at = time.monotonic()
                while True:
                    event = self.binding.poll_event()
                    if event is None:
                        break
                    native_events.append(event)

            drained_events = len(native_events)
            for event in native_events:
                self._emit_native_event(event)
        except Exception as exc:
            logger.error("Liblinphone iterate failed: {}", exc)
            self.running = False
            self._emit(BackendStopped(reason=str(exc)))
        finally:
            event_drain_duration_seconds = max(0.0, time.monotonic() - event_drain_started_at)
            total_duration_seconds = max(0.0, time.monotonic() - started_at)
            self._last_iterate_metrics = VoIPIterateMetrics(
                native_duration_seconds=native_duration_seconds,
                event_drain_duration_seconds=event_drain_duration_seconds,
                total_duration_seconds=total_duration_seconds,
                drained_events=drained_events,
            )
            self._log_iterate_warning_if_needed()
        return drained_events

    def make_call(self, sip_address: str) -> bool:
        binding = self.binding
        if binding is None:
            return False
        return self._call_binding(lambda: binding.make_call(sip_address))

    def answer_call(self) -> bool:
        binding = self.binding
        if binding is None:
            return False
        return self._call_binding(binding.answer_call)

    def reject_call(self) -> bool:
        binding = self.binding
        if binding is None:
            return False
        return self._call_binding(binding.reject_call)

    def hangup(self) -> bool:
        binding = self.binding
        if binding is None:
            return False
        return self._call_binding(binding.hangup)

    def mute(self) -> bool:
        binding = self.binding
        if binding is None:
            return False
        return self._call_binding(lambda: binding.set_muted(True))

    def unmute(self) -> bool:
        binding = self.binding
        if binding is None:
            return False
        return self._call_binding(lambda: binding.set_muted(False))

    def send_text_message(self, sip_address: str, text: str) -> str | None:
        if not self.running or self.binding is None:
            return None
        try:
            with self._binding_lock:
                return self.binding.send_text_message(sip_address, text)
        except Exception as exc:
            logger.error("Failed to send text message to {}: {}", sip_address, exc)
            return None

    def start_voice_note_recording(self, file_path: str) -> bool:
        binding = self.binding
        if binding is None:
            return False
        return self._call_binding(lambda: binding.start_voice_recording(file_path))

    def stop_voice_note_recording(self) -> int | None:
        if not self.running or self.binding is None:
            return None
        try:
            with self._binding_lock:
                return self.binding.stop_voice_recording()
        except Exception as exc:
            logger.error("Failed to stop voice-note recording: {}", exc)
            return None

    def cancel_voice_note_recording(self) -> bool:
        binding = self.binding
        if binding is None:
            return False
        return self._call_binding(binding.cancel_voice_recording)

    def send_voice_note(
        self,
        sip_address: str,
        *,
        file_path: str,
        duration_ms: int,
        mime_type: str,
    ) -> str | None:
        if not self.running or self.binding is None:
            return None
        try:
            with self._binding_lock:
                return self.binding.send_voice_note(
                    sip_address,
                    file_path=file_path,
                    duration_ms=duration_ms,
                    mime_type=mime_type,
                )
        except Exception as exc:
            logger.error("Failed to send voice note to {}: {}", sip_address, exc)
            return None

    def _call_binding(self, operation: Callable[[], None]) -> bool:
        if not self.running or self.binding is None:
            logger.error("Cannot execute VoIP operation: Liblinphone backend not running")
            return False
        try:
            with self._binding_lock:
                operation()
            return True
        except Exception as exc:
            logger.error("Liblinphone operation failed: {}", exc)
            return False

    def _log_iterate_warning_if_needed(self) -> None:
        """Surface backend-native keep-alive work when it blocks unusually long."""

        if self._last_iterate_metrics is None:
            return

        if (
            self._last_iterate_metrics.native_duration_seconds
            >= self._MIN_NATIVE_ITERATE_WARNING_SECONDS
        ):
            logger.warning(
                "VoIP keep-alive native iterate slow: native_ms={:.1f} "
                "total_ms={:.1f} drained_events={}",
                self._last_iterate_metrics.native_duration_seconds * 1000.0,
                self._last_iterate_metrics.total_duration_seconds * 1000.0,
                self._last_iterate_metrics.drained_events,
            )

        if (
            self._last_iterate_metrics.event_drain_duration_seconds
            >= self._MIN_EVENT_DRAIN_WARNING_SECONDS
        ):
            logger.warning(
                "VoIP keep-alive event drain slow: drain_ms={:.1f} "
                "total_ms={:.1f} drained_events={}",
                self._last_iterate_metrics.event_drain_duration_seconds * 1000.0,
                self._last_iterate_metrics.total_duration_seconds * 1000.0,
                self._last_iterate_metrics.drained_events,
            )

    def _emit(self, event: VoIPEvent) -> None:
        for callback in self.event_callbacks:
            try:
                callback(event)
            except Exception as exc:
                logger.error("Error in VoIP backend callback: {}", exc)

    def _emit_native_event(self, event: LiblinphoneNativeEvent) -> None:
        if event.type == 1:
            self._emit(
                RegistrationStateChanged(state=self._registration_state(event.registration_state))
            )
            return

        if event.type == 2:
            self._emit(CallStateChanged(state=self._call_state(event.call_state)))
            return

        if event.type == 3:
            self._emit(IncomingCallDetected(caller_address=event.peer_sip_address))
            return

        if event.type == 4:
            self.running = False
            self._emit(BackendStopped(reason=event.reason))
            return

        if event.type == 5:
            logger.info(
                "Liblinphone incoming message: id={} kind={} peer={} file={}",
                event.message_id,
                self._message_kind(event.message_kind).value,
                event.peer_sip_address,
                event.local_file_path,
            )
            self._emit(MessageReceived(message=self._message_record(event)))
            return

        if event.type == 6:
            logger.info(
                "Liblinphone message delivery: id={} state={} peer={} reason={}",
                event.message_id,
                self._delivery_state(event.message_delivery_state).value,
                event.peer_sip_address,
                event.reason,
            )
            self._emit(
                MessageDeliveryChanged(
                    message_id=event.message_id,
                    delivery_state=self._delivery_state(event.message_delivery_state),
                    local_file_path=event.local_file_path,
                    error=event.reason,
                )
            )
            return

        if event.type == 7:
            logger.info(
                "Liblinphone message download complete: id={} file={} mime={}",
                event.message_id,
                event.local_file_path,
                event.mime_type,
            )
            self._emit(
                MessageDownloadCompleted(
                    message_id=event.message_id,
                    local_file_path=event.local_file_path,
                    mime_type=event.mime_type,
                )
            )
            return

        if event.type == 8:
            logger.warning(
                "Liblinphone message failed: id={} reason={}",
                event.message_id,
                event.reason,
            )
            self._emit(MessageFailed(message_id=event.message_id, reason=event.reason))

    def _message_record(self, event: LiblinphoneNativeEvent) -> VoIPMessageRecord:
        timestamp = self._iso_now()
        return VoIPMessageRecord(
            id=event.message_id,
            peer_sip_address=event.peer_sip_address,
            sender_sip_address=event.sender_sip_address,
            recipient_sip_address=event.recipient_sip_address,
            kind=self._message_kind(event.message_kind),
            direction=self._message_direction(event.message_direction),
            delivery_state=self._delivery_state(event.message_delivery_state),
            created_at=timestamp,
            updated_at=timestamp,
            text=event.text,
            local_file_path=event.local_file_path,
            mime_type=event.mime_type,
            duration_ms=max(0, int(event.duration_ms)),
            unread=bool(event.unread),
        )

    @staticmethod
    def _registration_state(value: int) -> RegistrationState:
        mapping = {
            1: RegistrationState.PROGRESS,
            2: RegistrationState.OK,
            3: RegistrationState.CLEARED,
            4: RegistrationState.FAILED,
        }
        return mapping.get(value, RegistrationState.NONE)

    @staticmethod
    def _call_state(value: int) -> CallState:
        mapping = {
            1: CallState.INCOMING,
            2: CallState.OUTGOING,
            3: CallState.OUTGOING_PROGRESS,
            4: CallState.OUTGOING_RINGING,
            5: CallState.OUTGOING_EARLY_MEDIA,
            6: CallState.CONNECTED,
            7: CallState.STREAMS_RUNNING,
            8: CallState.PAUSED,
            9: CallState.PAUSED_BY_REMOTE,
            10: CallState.UPDATED_BY_REMOTE,
            11: CallState.RELEASED,
            12: CallState.ERROR,
            13: CallState.END,
        }
        return mapping.get(value, CallState.IDLE)

    @staticmethod
    def _message_kind(value: int) -> MessageKind:
        return MessageKind.VOICE_NOTE if value == 2 else MessageKind.TEXT

    @staticmethod
    def _message_direction(value: int) -> MessageDirection:
        return MessageDirection.OUTGOING if value == 2 else MessageDirection.INCOMING

    @staticmethod
    def _delivery_state(value: int) -> MessageDeliveryState:
        mapping = {
            1: MessageDeliveryState.QUEUED,
            2: MessageDeliveryState.SENDING,
            3: MessageDeliveryState.SENT,
            4: MessageDeliveryState.DELIVERED,
            5: MessageDeliveryState.FAILED,
        }
        return mapping.get(value, MessageDeliveryState.FAILED)

    @staticmethod
    def _iso_now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()

    def _configure_alsa_capture_path(self) -> None:
        mixer = self._alsa_capture_config()
        card = self._resolve_alsa_capture_card()
        commands = [
            f"amixer -c {card} sset 'Capture' {mixer.capture_raw}",
            f"amixer -c {card} sset 'ADC PCM' 195",
            f"amixer -c {card} sset 'Left Input Boost Mixer LINPUT1' 1",
            f"amixer -c {card} sset 'Right Input Boost Mixer RINPUT1' 1",
        ]

        for command in commands:
            try:
                subprocess.run(command, shell=True, capture_output=True, timeout=5, check=False)
            except Exception as exc:
                logger.warning("ALSA mixer command failed: {}: {}", command, exc)

    def _resolve_alsa_capture_card(self) -> str:
        """Resolve the ALSA card index matching the configured capture device."""

        target = self._normalize_alsa_name(self.config.capture_dev_id)
        try:
            result = subprocess.run(
                ["arecord", "-l"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except Exception as exc:
            logger.debug("Failed to inspect ALSA capture cards: {}", exc)
            return "0"

        if result.returncode == 0:
            for line in result.stdout.splitlines():
                match = re.search(r"card\s+(\d+):\s*([^\s]+)\s*\[([^\]]+)\]", line)
                if match is None:
                    continue
                card_index, short_name, long_name = match.groups()
                normalized_names = {
                    self._normalize_alsa_name(short_name),
                    self._normalize_alsa_name(long_name),
                }
                if target and target in normalized_names:
                    return card_index

            for line in result.stdout.splitlines():
                match = re.search(r"card\s+(\d+):", line)
                if match is not None:
                    return match.group(1)

        return "0"

    @staticmethod
    def _normalize_alsa_name(value: str) -> str:
        """Normalize ALSA identifiers for loose matching."""

        raw = value.strip()
        if raw.upper().startswith("ALSA:"):
            raw = raw.split(":", 1)[1]
        return "".join(ch for ch in raw.lower() if ch.isalnum())

    @staticmethod
    def _linphone_software_mic_gain() -> int:
        """Leave Liblinphone's own mic gain neutral and rely on ALSA capture tuning."""

        return 0

    def _alsa_capture_config(self) -> _AlsaCaptureConfig:
        capture_pct = min(100, max(0, self.config.mic_gain))
        return _AlsaCaptureConfig(capture_raw=int(14 + capture_pct * 0.16))
