"""Focused tests for the Talk flow screens."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoyopod.core import AppContext
from yoyopod.integrations.call import VoiceNoteDraft
from yoyopod.integrations.call.models import (
    MessageDeliveryState,
    MessageDirection,
    MessageKind,
    VoIPMessageRecord,
)
from yoyopod.integrations.contacts.models import Contact
from yoyopod.ui.display import Display
from yoyopod.ui.screens.router import NavigationRequest
from yoyopod.ui.screens.voip.quick_call import CallScreen
from yoyopod.ui.screens.voip.talk_contact import TalkContactScreen
from yoyopod.ui.screens.voip.voice_note import (
    VoiceNoteScreen,
    build_voice_note_actions,
    build_voice_note_state_provider,
)


class FakePeopleDirectory:
    """Minimal people-directory source for Talk tests."""

    def __init__(self, contacts: list[Contact]) -> None:
        self._contacts = contacts

    def get_contacts(self) -> list[Contact]:
        return list(self._contacts)

    def get_callable_contacts(self, *, gsm_enabled: bool = False) -> list[Contact]:
        return [
            contact for contact in self._contacts if contact.is_callable(gsm_enabled=gsm_enabled)
        ]


class FakeVoIPManager:
    """Minimal VoIP manager double for Talk actions."""

    def __init__(
        self,
        *,
        make_call_result: bool = True,
        stop_send_state: str = "review",
        stop_status_text: str = "Ready to send",
    ) -> None:
        self.make_call_result = make_call_result
        self.stop_send_state = stop_send_state
        self.stop_status_text = stop_status_text
        self.make_calls: list[tuple[str, str | None]] = []
        self.started_recordings: list[tuple[str, str]] = []
        self.send_attempts = 0
        self.played_notes: list[str] = []
        self.seen_contacts: list[str] = []
        self.active_voice_note: VoiceNoteDraft | None = None
        self.latest_notes: dict[str, VoIPMessageRecord] = {}

    def make_call(self, sip_address: str, contact_name: str | None = None) -> bool:
        self.make_calls.append((sip_address, contact_name))
        return self.make_call_result

    def latest_voice_note_for_contact(self, sip_address: str) -> VoIPMessageRecord | None:
        return self.latest_notes.get(sip_address)

    def play_latest_voice_note(self, sip_address: str) -> bool:
        self.played_notes.append(sip_address)
        return True

    def play_voice_note(self, file_path: str) -> bool:
        self.played_notes.append(file_path)
        return True

    def mark_voice_notes_seen(self, sip_address: str) -> None:
        self.seen_contacts.append(sip_address)

    def start_voice_note_recording(self, recipient_address: str, recipient_name: str = "") -> bool:
        self.started_recordings.append((recipient_address, recipient_name))
        self.active_voice_note = VoiceNoteDraft(
            recipient_address=recipient_address,
            recipient_name=recipient_name,
            file_path="data/voice_notes/test.wav",
            send_state="recording",
            status_text="Recording...",
        )
        return True

    def stop_voice_note_recording(self) -> VoiceNoteDraft | None:
        if self.active_voice_note is None:
            return None
        self.active_voice_note.duration_ms = 3200
        self.active_voice_note.send_state = self.stop_send_state
        self.active_voice_note.status_text = self.stop_status_text
        return self.active_voice_note

    def cancel_voice_note_recording(self) -> bool:
        self.active_voice_note = None
        return True

    def discard_active_voice_note(self) -> None:
        self.active_voice_note = None

    def send_active_voice_note(self) -> bool:
        self.send_attempts += 1
        if self.active_voice_note is None:
            return False
        self.active_voice_note.message_id = "note-1"
        self.active_voice_note.send_state = "sending"
        self.active_voice_note.status_text = "Sending..."
        return True

    def get_active_voice_note(self) -> VoiceNoteDraft | None:
        return self.active_voice_note


@pytest.fixture
def display() -> Display:
    """Create a simulation display and clean it up after the test."""

    test_display = Display(simulate=True)
    try:
        yield test_display
    finally:
        test_display.cleanup()


def test_call_screen_builds_people_deck_from_contacts(display: Display) -> None:
    """Talk should show one person at a time with favorites first and notes as labels."""

    contacts = [
        Contact(name="Bob", sip_address="sip:bob@example.com", favorite=False, notes="Dad"),
        Contact(name="Alice", sip_address="sip:alice@example.com", favorite=True, notes="Mama"),
        Contact(name="Carol", sip_address="sip:carol@example.com", favorite=True),
    ]
    screen = CallScreen(
        display,
        AppContext(),
        contacts_provider=lambda: FakePeopleDirectory(contacts).get_callable_contacts(),
    )

    screen.enter()

    assert [person.title for person in screen.people] == ["Mama", "Carol", "Dad"]


def test_call_screen_select_opens_selected_contact(display: Display) -> None:
    """Selecting from Talk should store the contact and route to the action screen."""

    contacts = [
        Contact(name="Alice", sip_address="sip:alice@example.com", favorite=True, notes="Mama")
    ]
    context = AppContext()
    screen = CallScreen(
        display,
        context,
        contacts_provider=lambda: FakePeopleDirectory(contacts).get_callable_contacts(),
    )

    screen.enter()
    screen.on_select()

    assert context.talk.selected_contact_name == "Mama"
    assert context.talk.selected_contact_address == "sip:alice@example.com"
    assert screen.consume_navigation_request() == NavigationRequest.route("open_contact")


def test_talk_contact_screen_calls_selected_person(display: Display) -> None:
    """The contact action screen should delegate dialing without owning navigation."""

    context = AppContext()
    context.set_talk_contact(name="Mama", sip_address="sip:alice@example.com")
    voip_manager = FakeVoIPManager()
    screen = TalkContactScreen(display, context, voip_manager=voip_manager)

    screen.enter()
    screen.on_select()

    assert voip_manager.make_calls == [("sip:alice@example.com", "Mama")]
    assert screen.consume_navigation_request() is None


def test_talk_contact_screen_routes_to_voice_note(display: Display) -> None:
    """The second action should open the voice-note flow for the selected contact."""

    context = AppContext()
    context.set_talk_contact(name="Mama", sip_address="sip:alice@example.com")
    screen = TalkContactScreen(display, context, voip_manager=FakeVoIPManager())

    screen.enter()
    screen.on_advance()
    screen.on_select()

    assert context.talk.active_voice_note.recipient_name == "Mama"
    assert context.talk.active_voice_note.recipient_address == "sip:alice@example.com"
    assert screen.consume_navigation_request() == NavigationRequest.route("voice_note")


def test_talk_contact_screen_adds_play_note_action_when_latest_note_exists(
    display: Display,
) -> None:
    """Contacts with a stored incoming voice note should expose Play Note."""

    context = AppContext()
    context.set_talk_contact(name="Mama", sip_address="sip:alice@example.com")
    voip_manager = FakeVoIPManager()
    voip_manager.latest_notes["sip:alice@example.com"] = VoIPMessageRecord(
        id="note-1",
        peer_sip_address="sip:alice@example.com",
        sender_sip_address="sip:alice@example.com",
        recipient_sip_address="sip:kid@example.com",
        kind=MessageKind.VOICE_NOTE,
        direction=MessageDirection.INCOMING,
        delivery_state=MessageDeliveryState.DELIVERED,
        created_at="2026-04-06T00:00:00+00:00",
        updated_at="2026-04-06T00:00:00+00:00",
        local_file_path="data/voice_notes/incoming.wav",
        duration_ms=2100,
        unread=True,
    )
    screen = TalkContactScreen(display, context, voip_manager=voip_manager)

    assert [action.title for action in screen.actions()] == ["Call", "Voice Note", "Play Note"]

    screen.selected_index = 2
    screen.on_select()

    assert voip_manager.played_notes == ["sip:alice@example.com"]
    assert voip_manager.seen_contacts == ["sip:alice@example.com"]


def test_talk_contact_screen_keeps_rendered_selection_and_on_select_aligned(
    display: Display,
) -> None:
    """Shrinking actions should keep the highlighted and executed Talk action aligned."""

    context = AppContext()
    context.set_talk_contact(name="Mama", sip_address="sip:alice@example.com")
    voip_manager = FakeVoIPManager()
    voip_manager.latest_notes["sip:alice@example.com"] = VoIPMessageRecord(
        id="note-1",
        peer_sip_address="sip:alice@example.com",
        sender_sip_address="sip:alice@example.com",
        recipient_sip_address="sip:kid@example.com",
        kind=MessageKind.VOICE_NOTE,
        direction=MessageDirection.INCOMING,
        delivery_state=MessageDeliveryState.DELIVERED,
        created_at="2026-04-06T00:00:00+00:00",
        updated_at="2026-04-06T00:00:00+00:00",
        local_file_path="data/voice_notes/incoming.wav",
        duration_ms=2100,
        unread=True,
    )
    screen = TalkContactScreen(display, context, voip_manager=voip_manager)

    screen.selected_index = 2
    del voip_manager.latest_notes["sip:alice@example.com"]

    _titles, _subtitles, selected_index = screen.get_visible_actions()
    screen.on_select()

    assert selected_index == 1
    assert context.talk.active_voice_note.recipient_name == "Mama"
    assert context.talk.active_voice_note.recipient_address == "sip:alice@example.com"
    assert screen.consume_navigation_request() == NavigationRequest.route("voice_note")


def test_talk_contact_screen_clamps_visible_action_index(display: Display) -> None:
    """Visible Talk actions should clamp stale selection indices."""

    context = AppContext()
    context.set_talk_contact(name="Mama", sip_address="sip:alice@example.com")
    screen = TalkContactScreen(display, context, voip_manager=FakeVoIPManager())

    screen.selected_index = 9

    titles, subtitles, selected_index = screen.get_visible_actions()

    assert titles == ["Call", "Voice Note"]
    assert subtitles == ["Start a voice call", "Record a short message"]
    assert selected_index == 1


def test_voice_note_screen_records_reviews_and_sends(display: Display) -> None:
    """Voice notes should move through record, review, and sending states."""

    context = AppContext()
    voip_manager = FakeVoIPManager()
    context.set_voice_note_recipient(name="Mama", sip_address="sip:alice@example.com")
    screen = VoiceNoteScreen(
        display,
        context,
        state_provider=build_voice_note_state_provider(context=context, voip_manager=voip_manager),
        actions=build_voice_note_actions(voip_manager=voip_manager),
    )

    screen.enter()
    assert screen.current_view_model()[0] == "Voice Note"

    screen.on_ptt_press({"stage": "hold_started"})
    assert screen.current_view_model()[0] == "Recording"
    assert voip_manager.started_recordings == [("sip:alice@example.com", "Mama")]

    screen.on_ptt_release({"hold_started": True})
    assert screen.current_view_model()[0] == "Review"
    assert context.talk.active_voice_note.duration_ms == 3200

    screen.on_select()
    assert screen.current_view_model()[0] == "Sending"
    assert voip_manager.send_attempts == 1


def test_voice_note_screen_can_resolve_voice_note_actions_from_app(display: Display) -> None:
    """Voice notes should work through the owning app seam without threaded providers."""

    context = AppContext()
    voip_manager = FakeVoIPManager()
    context.set_voice_note_recipient(name="Mama", sip_address="sip:alice@example.com")
    screen = VoiceNoteScreen(
        display,
        context,
        app=SimpleNamespace(voip_manager=voip_manager),
    )

    screen.enter()
    screen.on_ptt_press({"stage": "hold_started"})
    screen.on_ptt_release({"hold_started": True})
    screen.on_select()

    assert voip_manager.started_recordings == [("sip:alice@example.com", "Mama")]
    assert screen.current_view_model()[0] == "Sending"
    assert voip_manager.send_attempts == 1


def test_voice_note_screen_propagates_failed_stop_state(display: Display) -> None:
    """Stopping a note should preserve manager failures like oversized recordings."""

    context = AppContext()
    voip_manager = FakeVoIPManager(
        stop_send_state="failed",
        stop_status_text="Note too long",
    )
    context.set_voice_note_recipient(name="Mama", sip_address="sip:alice@example.com")
    screen = VoiceNoteScreen(
        display,
        context,
        state_provider=build_voice_note_state_provider(context=context, voip_manager=voip_manager),
        actions=build_voice_note_actions(voip_manager=voip_manager),
    )

    screen.enter()
    screen.on_ptt_press({"stage": "hold_started"})
    screen.on_ptt_release({"hold_started": True})

    assert screen.current_view_model()[0] == "Couldn't Send"
    assert context.talk.active_voice_note.send_state == "failed"
    assert context.talk.active_voice_note.status_text == "Note too long"


def test_voice_note_screen_can_preview_before_sending(display: Display) -> None:
    """Review mode should let the child preview the recorded note before sending it."""

    context = AppContext()
    voip_manager = FakeVoIPManager()
    context.set_voice_note_recipient(name="Mama", sip_address="sip:alice@example.com")
    screen = VoiceNoteScreen(
        display,
        context,
        state_provider=build_voice_note_state_provider(context=context, voip_manager=voip_manager),
        actions=build_voice_note_actions(voip_manager=voip_manager),
    )

    screen.enter()
    screen.on_ptt_press({"stage": "hold_started"})
    screen.on_ptt_release({"hold_started": True})
    screen.on_advance()
    screen.on_select()

    assert voip_manager.played_notes == ["data/voice_notes/test.wav"]
    assert context.talk.active_voice_note.status_text == "Playing preview"


def test_voice_note_screen_reopens_clean_after_terminal_draft(display: Display) -> None:
    """Finished drafts for the same contact should not block starting a new note later."""

    context = AppContext()
    voip_manager = FakeVoIPManager()
    voip_manager.active_voice_note = VoiceNoteDraft(
        recipient_address="sip:alice@example.com",
        recipient_name="Mama",
        file_path="data/voice_notes/test.wav",
        send_state="sent",
        status_text="Sent",
        message_id="note-1",
        duration_ms=3200,
    )
    context.set_voice_note_recipient(name="Mama", sip_address="sip:alice@example.com")
    screen = VoiceNoteScreen(
        display,
        context,
        state_provider=build_voice_note_state_provider(context=context, voip_manager=voip_manager),
        actions=build_voice_note_actions(voip_manager=voip_manager),
    )

    screen.enter()

    assert screen.current_view_model()[0] == "Voice Note"
    assert voip_manager.active_voice_note is None
    assert context.talk.active_voice_note.send_state == "idle"


def test_voice_note_screen_render_syncs_manager_terminal_state(display: Display) -> None:
    """Render should reflect async manager state changes such as send failure or success."""

    context = AppContext()
    voip_manager = FakeVoIPManager()
    voip_manager.active_voice_note = VoiceNoteDraft(
        recipient_address="sip:alice@example.com",
        recipient_name="Mama",
        file_path="data/voice_notes/test.wav",
        send_state="sending",
        status_text="Sending...",
        message_id="note-1",
        duration_ms=3200,
    )
    context.set_voice_note_recipient(name="Mama", sip_address="sip:alice@example.com")
    screen = VoiceNoteScreen(
        display,
        context,
        state_provider=build_voice_note_state_provider(context=context, voip_manager=voip_manager),
        actions=build_voice_note_actions(voip_manager=voip_manager),
    )
    screen._ensure_lvgl_view = lambda: SimpleNamespace(sync=lambda: None)

    screen.enter()
    voip_manager.active_voice_note.send_state = "failed"
    voip_manager.active_voice_note.status_text = "Voice notes unavailable"
    screen.render()

    assert screen.current_view_model()[0] == "Couldn't Send"
    assert context.talk.active_voice_note.status_text == "Voice notes unavailable"


def test_voice_note_screen_ignores_stale_draft_for_different_recipient(display: Display) -> None:
    """Opening voice notes for contact B should not inherit contact A's stale draft state."""

    context = AppContext()
    voip_manager = FakeVoIPManager()
    voip_manager.active_voice_note = VoiceNoteDraft(
        recipient_address="sip:alice@example.com",
        recipient_name="Mama",
        file_path="data/voice_notes/alice.wav",
        send_state="sent",
        status_text="Sent",
        message_id="note-alice",
    )
    context.set_voice_note_recipient(name="Dad", sip_address="sip:bob@example.com")
    screen = VoiceNoteScreen(
        display,
        context,
        state_provider=build_voice_note_state_provider(context=context, voip_manager=voip_manager),
        actions=build_voice_note_actions(voip_manager=voip_manager),
    )

    screen.enter()

    assert screen.current_view_model()[0] == "Voice Note"
    assert context.talk.active_voice_note.send_state == "idle"
    assert context.talk.active_voice_note.status_text == ""
