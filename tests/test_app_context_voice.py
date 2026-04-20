"""Tests for AppContext voice runtime state."""

from __future__ import annotations

from yoyopod.core import AppContext


def test_app_context_tracks_voice_volume_and_toggles() -> None:
    """Voice runtime state should stay aligned with app-facing volume and toggles."""

    context = AppContext()

    assert context.voice.output_volume == 50
    assert context.voice.commands_enabled is True
    assert context.voice.screen_read_enabled is False

    context.set_volume(64)
    context.configure_voice(commands_enabled=False, screen_read_enabled=True, tts_enabled=False)
    toggled = context.toggle_mic_muted()
    context.record_voice_transcript("call mom", mode="voice_commands")
    context.record_voice_response("Calling mom")
    context.update_voice_backend_status(stt_available=True, tts_available=False)

    assert context.voice.output_volume == 64
    assert context.voice.commands_enabled is False
    assert context.voice.screen_read_enabled is True
    assert context.voice.tts_enabled is False
    assert toggled is True
    assert context.voice.mic_muted is True
    assert context.voice.last_transcript == "call mom"
    assert context.voice.last_mode == "voice_commands"
    assert context.voice.last_spoken_text == "Calling mom"
    assert context.voice.stt_available is True
    assert context.voice.tts_available is False
