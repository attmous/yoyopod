"""In-memory VoIP backend used for tests and offline services."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from yoyopod.backends.voip.protocol import VoIPIterateMetrics
from yoyopod.integrations.call.models import VoIPEvent


class MockVoIPBackend:
    """Simple in-memory backend used for unit tests."""

    def __init__(self, start_result: bool = True) -> None:
        self.start_result = start_result
        self.running = False
        self.commands: list[str] = []
        self.event_callbacks: list[Callable[[VoIPEvent], None]] = []
        self.make_call_result = True
        self.answer_result = True
        self.reject_result = True
        self.hangup_result = True
        self.mute_result = True
        self.unmute_result = True
        self.recording_active = False
        self.recording_path = ""
        self.recording_duration_ms = 1500
        self.next_text_message_id = "mock-text-1"
        self.next_voice_note_id = "mock-note-1"

    def on_event(self, callback: Callable[[VoIPEvent], None]) -> None:
        self.event_callbacks.append(callback)

    def emit(self, event: VoIPEvent) -> None:
        for callback in self.event_callbacks:
            callback(event)

    def start(self) -> bool:
        self.running = self.start_result
        return self.start_result

    def stop(self) -> None:
        self.running = False
        self.recording_active = False

    def iterate(self) -> int:
        return 0

    def get_iterate_metrics(self) -> VoIPIterateMetrics | None:
        return None

    def make_call(self, sip_address: str) -> bool:
        self.commands.append(f"call {sip_address}")
        return self.make_call_result

    def answer_call(self) -> bool:
        self.commands.append("answer")
        return self.answer_result

    def reject_call(self) -> bool:
        self.commands.append("decline")
        return self.reject_result

    def hangup(self) -> bool:
        self.commands.append("terminate")
        return self.hangup_result

    def mute(self) -> bool:
        self.commands.append("mute")
        return self.mute_result

    def unmute(self) -> bool:
        self.commands.append("unmute")
        return self.unmute_result

    def send_text_message(self, sip_address: str, text: str) -> str | None:
        self.commands.append(f"text {sip_address} {text}")
        return self.next_text_message_id

    def start_voice_note_recording(self, file_path: str) -> bool:
        self.recording_active = True
        self.recording_path = file_path
        self.commands.append(f"record-start {file_path}")
        return True

    def stop_voice_note_recording(self) -> int | None:
        if not self.recording_active:
            return None
        self.recording_active = False
        self.commands.append("record-stop")
        return self.recording_duration_ms

    def cancel_voice_note_recording(self) -> bool:
        self.recording_active = False
        self.commands.append("record-cancel")
        return True

    def send_voice_note(
        self,
        sip_address: str,
        *,
        file_path: str,
        duration_ms: int,
        mime_type: str,
    ) -> str | None:
        self.commands.append(
            f"voice-note {sip_address} {Path(file_path).name} {duration_ms} {mime_type}"
        )
        return self.next_voice_note_id
