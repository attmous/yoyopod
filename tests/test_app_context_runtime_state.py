"""Tests for focused AppContext runtime state ownership."""

from __future__ import annotations

from yoyopod.app_context import AppContext
from yoyopod.audio.music.models import PlaybackQueue, Track


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
    context.update_voip_status(
        configured=True,
        ready=False,
        running=True,
        registration_state="progress",
    )
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
    assert context.voip.running is True
    assert context.voip.registration_state == "progress"
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


def test_app_context_nested_state_fields_are_mutable() -> None:
    """Focused runtime state objects should remain mutable for call sites that own them."""

    context = AppContext()
    playlist = PlaybackQueue(name="Demo")

    context.media.current_playlist = playlist
    context.media.playlists = {"demo": playlist}
    context.power.battery_percent = 77
    context.power.battery_charging = True
    context.power.available = True
    context.network.connection_type = "wifi"
    context.network.enabled = True
    context.network.connected = True
    context.network.gps_has_fix = True
    context.screen.awake = False
    context.screen.on_seconds = 31
    context.screen.idle_seconds = 9
    context.screen.app_uptime_seconds = 120
    context.talk.selected_contact_name = "Mama"
    context.talk.selected_contact_address = "sip:alice@example.com"
    context.talk.active_voice_note.recipient_name = "Mama"
    context.talk.active_voice_note.recipient_address = "sip:alice@example.com"
    context.talk.active_voice_note.send_state = "sent"
    context.talk.active_voice_note.status_text = "Delivered"
    context.talk.active_voice_note.file_path = "/tmp/note.wav"
    context.talk.active_voice_note.duration_ms = 2800
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
