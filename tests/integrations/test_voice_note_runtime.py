"""Focused tests for runtime-owned Talk and voice-note sync helpers."""

from __future__ import annotations

from types import SimpleNamespace

from yoyopod.core import AppContext
from yoyopod.integrations.call import VoiceNoteEventHandler


def test_voice_note_activity_syncs_talk_summary_without_boot_service() -> None:
    """Voice-note activity should refresh Talk context without reaching back into boot."""

    context = AppContext()
    refreshed = {"count": 0}
    app = SimpleNamespace(
        context=context,
        call_history_store=SimpleNamespace(
            missed_count=lambda: 2,
            recent_preview=lambda: ["Mama", "Baba"],
        ),
        voip_manager=SimpleNamespace(
            call_history_unread_count=lambda: 2,
            call_history_recent_preview=lambda: ("Mama", "Baba"),
            unread_voice_note_count=lambda: 3,
            latest_voice_note_summary=lambda: {
                "sip:mama@example.com": {"status": "received"}
            },
            get_active_voice_note=lambda: SimpleNamespace(
                send_state="sending",
                status_text="Uploading",
                file_path="/tmp/note.wav",
                duration_ms=3200,
            ),
        ),
        screen_manager=SimpleNamespace(
            get_current_screen=lambda: SimpleNamespace(route_name="voice_note"),
            refresh_current_screen=lambda: refreshed.__setitem__(
                "count",
                refreshed["count"] + 1,
            ),
        ),
    )

    VoiceNoteEventHandler(app).handle_voice_note_activity_changed()

    assert context.talk.missed_calls == 2
    assert context.talk.recent_calls == ["Mama", "Baba"]
    assert context.talk.unread_voice_notes == 3
    assert context.talk.latest_voice_note_by_contact == {
        "sip:mama@example.com": {"status": "received"}
    }
    assert context.talk.active_voice_note.send_state == "sending"
    assert context.talk.active_voice_note.status_text == "Uploading"
    assert context.talk.active_voice_note.file_path == "/tmp/note.wav"
    assert context.talk.active_voice_note.duration_ms == 3200
    assert refreshed["count"] == 1
