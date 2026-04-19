"""Focused unit tests for the extracted voice-note helper modules."""

from __future__ import annotations

from typing import cast

import pytest

from yoyopod.app_context import AppContext
from yoyopod.communication import VoIPManager
from yoyopod.communication.calling import VoiceNoteDraft
from yoyopod.ui.screens.voip.voice_note_models import (
    VoiceNoteActions,
    VoiceNoteState,
    build_voice_note_actions,
    build_voice_note_state_provider,
)
from yoyopod.ui.screens.voip.voice_note_recording import (
    VoiceNoteRecordingController,
    VoiceNoteRecordingResult,
)
from yoyopod.ui.screens.voip.voice_note_viewmodel import VoiceNoteViewModel


class FakeVoiceNoteManager:
    """Minimal manager double for voice-note helper tests."""

    def __init__(
        self,
        *,
        active_voice_note: VoiceNoteDraft | None = None,
        start_result: bool = True,
        stop_result: VoiceNoteDraft | None = None,
        preview_result: bool = True,
        send_result: bool = True,
    ) -> None:
        self.active_voice_note = active_voice_note
        self.start_result = start_result
        self.stop_result = stop_result
        self.preview_result = preview_result
        self.send_result = send_result
        self.started_recordings: list[tuple[str, str]] = []
        self.previewed_paths: list[str] = []
        self.cancel_calls = 0
        self.discard_calls = 0
        self.send_calls = 0

    def start_voice_note_recording(self, recipient_address: str, recipient_name: str = "") -> bool:
        self.started_recordings.append((recipient_address, recipient_name))
        return self.start_result

    def stop_voice_note_recording(self) -> VoiceNoteDraft | None:
        return self.stop_result

    def cancel_voice_note_recording(self) -> bool:
        self.cancel_calls += 1
        return True

    def discard_active_voice_note(self) -> None:
        self.discard_calls += 1

    def send_active_voice_note(self) -> bool:
        self.send_calls += 1
        return self.send_result

    def play_voice_note(self, file_path: str) -> bool:
        self.previewed_paths.append(file_path)
        return self.preview_result

    def get_active_voice_note(self) -> VoiceNoteDraft | None:
        return self.active_voice_note


def test_voice_note_view_model_review_actions_clamp_selected_index() -> None:
    """Review mode should expose the expected actions and clamp the selection."""

    view_model = VoiceNoteViewModel(
        state=VoiceNoteState(recipient_name="Mama", duration_ms=3200),
        flow_state="review",
        one_button_mode=False,
        selected_action_index=99,
    )

    assert view_model.current_actions_for_view() == (
        ["Send", "Play", "Again"],
        ["3s", "", ""],
        2,
    )
    assert view_model.current_action_subtitles() == [
        "Deliver this voice note",
        "Listen before sending",
        "Record a new version",
    ]
    assert view_model.current_action_icons() == ["check", "play", "close"]
    assert view_model.current_action_color_kinds() == [1, 0, 2]


@pytest.mark.parametrize(
    ("flow_state", "expected_kind"),
    [
        ("ready", 3),
        ("sending", 0),
        ("sent", 1),
        ("failed", 3),
    ],
)
def test_voice_note_view_model_primary_color_kind_matches_flow_state(
    flow_state: str,
    expected_kind: int,
) -> None:
    """The centered action color kind should remain stable across flow states."""

    view_model = VoiceNoteViewModel(
        state=VoiceNoteState(recipient_name="Mama"),
        flow_state=flow_state,
        one_button_mode=False,
    )

    assert view_model.current_primary_color_kind() == expected_kind


def test_voice_note_view_model_failed_state_uses_status_override() -> None:
    """Failed view text should prefer the provided status text."""

    view_model = VoiceNoteViewModel(
        state=VoiceNoteState(recipient_name="Mama", status_text="Try again after Wi-Fi"),
        flow_state="failed",
        one_button_mode=True,
    )

    assert view_model.current_view_model() == (
        "Couldn't Send",
        "Try again after Wi-Fi",
        "Tap next / Double choose",
        "voice_note",
    )
    assert view_model.current_status_chip() == ("Failed", 3)


def test_recording_controller_start_handles_missing_and_failed_actions() -> None:
    """Start should distinguish between missing hooks and explicit failures."""

    missing_action_controller = VoiceNoteRecordingController()
    failing_controller = VoiceNoteRecordingController(
        VoiceNoteActions(start_recording=lambda _address, _name: False)
    )

    assert missing_action_controller.start_recording(
        recipient_address="sip:alice@example.com",
        recipient_name="Mama",
    ) == VoiceNoteRecordingResult(next_state=None)
    assert failing_controller.start_recording(
        recipient_address="sip:alice@example.com",
        recipient_name="Mama",
    ) == VoiceNoteRecordingResult(
        next_state="failed",
        status_text="Couldn't start recorder",
    )


def test_recording_controller_stop_propagates_draft_send_state() -> None:
    """Stopping a recording should preserve the draft state and status text."""

    review_draft = VoiceNoteDraft(
        recipient_address="sip:alice@example.com",
        recipient_name="Mama",
        file_path="/tmp/note.wav",
        send_state="review",
        status_text="Ready to send",
    )
    failed_draft = VoiceNoteDraft(
        recipient_address="sip:alice@example.com",
        recipient_name="Mama",
        file_path="/tmp/note.wav",
        send_state="failed",
        status_text="Note too long",
    )
    review_controller = VoiceNoteRecordingController(
        VoiceNoteActions(stop_recording=lambda: review_draft)
    )
    failed_state_controller = VoiceNoteRecordingController(
        VoiceNoteActions(stop_recording=lambda: failed_draft)
    )
    missing_draft_controller = VoiceNoteRecordingController(
        VoiceNoteActions(stop_recording=lambda: None)
    )

    assert review_controller.stop_recording() == VoiceNoteRecordingResult(
        next_state="review",
        status_text="Ready to send",
    )
    assert failed_state_controller.stop_recording() == VoiceNoteRecordingResult(
        next_state="failed",
        status_text="Note too long",
    )
    assert missing_draft_controller.stop_recording() == VoiceNoteRecordingResult(
        next_state="failed",
        status_text="Couldn't save note",
    )


def test_recording_controller_cancel_returns_ready_and_calls_cancel() -> None:
    """Cancel should always return the ready transition and invoke the cancel hook."""

    cancel_called = False

    def cancel_recording() -> bool:
        nonlocal cancel_called
        cancel_called = True
        return True

    controller = VoiceNoteRecordingController(VoiceNoteActions(cancel_recording=cancel_recording))

    assert controller.cancel_recording() == VoiceNoteRecordingResult(next_state="ready")
    assert cancel_called is True


def test_build_voice_note_state_provider_reads_context_without_manager() -> None:
    """The state provider should mirror the active context when no manager is present."""

    context = AppContext()
    context.set_voice_note_recipient(name="Mama", sip_address="sip:alice@example.com")
    context.update_active_voice_note(
        send_state="review",
        status_text="Ready to send",
        file_path="/tmp/note.wav",
        duration_ms=3200,
    )

    provider = build_voice_note_state_provider(context=context)

    assert provider() == VoiceNoteState(
        recipient_name="Mama",
        recipient_address="sip:alice@example.com",
        send_state="review",
        status_text="Ready to send",
        file_path="/tmp/note.wav",
        duration_ms=3200,
    )


def test_build_voice_note_state_provider_ignores_stale_manager_draft() -> None:
    """A draft for another recipient should not leak into the current voice-note flow."""

    context = AppContext()
    context.set_voice_note_recipient(name="Dad", sip_address="sip:bob@example.com")
    manager = FakeVoiceNoteManager(
        active_voice_note=VoiceNoteDraft(
            recipient_address="sip:alice@example.com",
            recipient_name="Mama",
            file_path="/tmp/alice.wav",
            send_state="review",
            status_text="Ready to send",
            duration_ms=2800,
        )
    )

    provider = build_voice_note_state_provider(
        context=context,
        voip_manager=cast(VoIPManager, manager),
    )

    assert provider() == VoiceNoteState(
        recipient_name="Dad",
        recipient_address="sip:bob@example.com",
    )


def test_build_voice_note_actions_forwards_manager_calls_and_status_updates() -> None:
    """The built actions should remain a thin adapter over the manager surface."""

    active_draft = VoiceNoteDraft(
        recipient_address="sip:alice@example.com",
        recipient_name="Mama",
        file_path="/tmp/note.wav",
    )
    stopped_draft = VoiceNoteDraft(
        recipient_address="sip:alice@example.com",
        recipient_name="Mama",
        file_path="/tmp/note.wav",
        send_state="review",
    )
    manager = FakeVoiceNoteManager(
        active_voice_note=active_draft,
        stop_result=stopped_draft,
    )

    actions = build_voice_note_actions(voip_manager=cast(VoIPManager, manager))

    assert actions.start_recording is not None
    assert actions.stop_recording is not None
    assert actions.discard_active_draft is not None
    assert actions.send_active_draft is not None
    assert actions.preview_draft is not None
    assert actions.set_draft_status_text is not None

    assert actions.start_recording("sip:alice@example.com", "Mama") is True
    assert manager.started_recordings == [("sip:alice@example.com", "Mama")]
    assert actions.stop_recording() is stopped_draft
    assert actions.preview_draft("/tmp/note.wav") is True
    assert manager.previewed_paths == ["/tmp/note.wav"]
    actions.set_draft_status_text("Playing preview")
    assert manager.active_voice_note is not None
    assert manager.active_voice_note.status_text == "Playing preview"
    assert actions.send_active_draft() is True
    assert manager.send_calls == 1
    actions.discard_active_draft()
    assert manager.discard_calls == 1
