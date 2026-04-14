"""Tests for focused AppContext runtime state ownership."""

from __future__ import annotations

from yoyopy.app_context import AppContext
from yoyopy.audio.music.models import PlaybackQueue, Track


def test_app_context_groups_runtime_state_by_concern() -> None:
    """The shared context should expose focused state objects for major runtime concerns."""

    context = AppContext()
    playlist = PlaybackQueue(
        name="Bedtime Mix",
        tracks=[
            Track(
                uri="demo://stars",
                name="Stars",
                artists=["Mama"],
                length=180_000,
            )
        ],
    )

    context.set_playlist(playlist)
    context.update_voip_status(configured=True, ready=False)
    context.update_network_status(
        network_enabled=True,
        signal_bars=3,
        connection_type="4g",
        connected=True,
        gps_has_fix=True,
    )
    context.update_screen_runtime(
        screen_awake=False,
        app_uptime_seconds=93.4,
        screen_on_seconds=45.1,
        idle_seconds=12.2,
    )
    context.update_call_summary(missed_calls=2, recent_calls=["Mama"])
    context.set_talk_contact(name="Mama", sip_address="sip:alice@example.com")
    context.set_voice_note_recipient(name="Mama", sip_address="sip:alice@example.com")
    context.update_active_voice_note(
        send_state="review",
        status_text="Ready to send",
        file_path="/tmp/voice-note.wav",
        duration_ms=3200,
    )

    assert context.media.current_playlist is playlist
    assert context.media.current_track() == playlist.current_track()
    assert context.voip.configured is True
    assert context.voip.ready is False
    assert context.network.enabled is True
    assert context.network.signal_strength == 3
    assert context.network.connection_type == "4g"
    assert context.network.connected is True
    assert context.network.gps_has_fix is True
    assert context.screen.awake is False
    assert context.screen.app_uptime_seconds == 93
    assert context.screen.on_seconds == 45
    assert context.screen.idle_seconds == 12
    assert context.talk.missed_calls == 2
    assert context.talk.recent_calls == ["Mama"]
    assert context.talk.selected_contact_name == "Mama"
    assert context.talk.selected_contact_address == "sip:alice@example.com"
    assert context.talk.active_voice_note.recipient_name == "Mama"
    assert context.talk.active_voice_note.recipient_address == "sip:alice@example.com"
    assert context.talk.active_voice_note.send_state == "review"
    assert context.talk.active_voice_note.status_text == "Ready to send"
    assert context.talk.active_voice_note.file_path == "/tmp/voice-note.wav"
    assert context.talk.active_voice_note.duration_ms == 3200


def test_app_context_compatibility_aliases_write_through_nested_state() -> None:
    """Legacy top-level fields should still update the focused runtime state objects."""

    context = AppContext()
    playlist = PlaybackQueue(name="Demo")

    context.current_playlist = playlist
    context.playlists = {"demo": playlist}
    context.battery_percent = 77
    context.battery_charging = True
    context.power_available = True
    context.connection_type = "wifi"
    context.network_enabled = True
    context.is_connected = True
    context.gps_has_fix = True
    context.screen_awake = False
    context.screen_on_seconds = 31
    context.screen_idle_seconds = 9
    context.app_uptime_seconds = 120
    context.talk_contact_name = "Mama"
    context.talk_contact_address = "sip:alice@example.com"
    context.voice_note_recipient_name = "Mama"
    context.voice_note_recipient_address = "sip:alice@example.com"
    context.voice_note_send_state = "sent"
    context.voice_note_status_text = "Delivered"
    context.voice_note_file_path = "/tmp/note.wav"
    context.voice_note_duration_ms = 2800
    context.cache_output_volume(64)

    assert context.media.current_playlist is playlist
    assert context.media.playlists == {"demo": playlist}
    assert context.power.battery_percent == 77
    assert context.power.battery_charging is True
    assert context.power.available is True
    assert context.network.connection_type == "wifi"
    assert context.network.enabled is True
    assert context.network.connected is True
    assert context.network.gps_has_fix is True
    assert context.screen.awake is False
    assert context.screen.on_seconds == 31
    assert context.screen.idle_seconds == 9
    assert context.screen.app_uptime_seconds == 120
    assert context.talk.selected_contact_name == "Mama"
    assert context.talk.selected_contact_address == "sip:alice@example.com"
    assert context.talk.active_voice_note.recipient_name == "Mama"
    assert context.talk.active_voice_note.recipient_address == "sip:alice@example.com"
    assert context.talk.active_voice_note.send_state == "sent"
    assert context.talk.active_voice_note.status_text == "Delivered"
    assert context.talk.active_voice_note.file_path == "/tmp/note.wav"
    assert context.talk.active_voice_note.duration_ms == 2800
    assert context.media.playback.volume == 64
    assert context.voice.output_volume == 64
