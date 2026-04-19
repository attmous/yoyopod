"""Deterministic fixture builders for gallery captures."""

from __future__ import annotations

from datetime import datetime, timezone

from yoyopod.cli.pi.gallery.fakes import (
    _DemoContact,
    _DemoPlaylistSummary,
    _DemoVoiceNoteDraft,
    _FakeCallHistoryStore,
    _FakeMusicService,
    _FakePowerManager,
    _FakeVoipManager,
)


def _build_context() -> object:
    """Create one stable one-button app context."""
    from yoyopod.app_context import AppContext
    from yoyopod.audio.music.models import PlaybackQueue, Track
    from yoyopod.ui.input import InteractionProfile

    context = AppContext(interaction_profile=InteractionProfile.ONE_BUTTON)
    context.update_voip_status(configured=True, ready=True)
    context.update_system_status(battery=86, signal=4, connected=True)
    context.battery_charging = False
    context.external_power = False
    context.power_available = True
    context.screen_awake = True
    context.app_uptime_seconds = 3672
    context.screen_on_seconds = 1240
    context.screen_idle_seconds = 7
    context.update_call_summary(missed_calls=2, recent_calls=["Mama", "Hagar", "Papa"])
    context.update_voice_note_summary(
        unread_voice_notes=1,
        latest_voice_note_by_contact={
            "sip:hagar@example.com": {
                "unread": True,
                "direction": "incoming",
                "delivery_state": "delivered",
                "local_file_path": "data/voice_notes/hagar.wav",
            },
            "sip:mama@example.com": {
                "unread": False,
                "direction": "outgoing",
                "delivery_state": "sent",
                "local_file_path": "data/voice_notes/mama.wav",
            },
        },
    )

    demo_playlist = PlaybackQueue(
        name="Road Trip",
        tracks=[
            Track(
                uri="demo://golden-hour",
                name="Golden Hour",
                artists=["Kacey Musgraves"],
                length=214_000,
            ),
            Track(
                uri="demo://midnight-train",
                name="Midnight Train",
                artists=["Sam Smith"],
                length=198_000,
            ),
        ],
    )
    context.set_playlist(demo_playlist)
    context.playback.is_playing = True
    context.playback.is_paused = False
    context.playback.is_stopped = False
    context.playback.position = 74.0
    return context


def _build_contacts() -> list[_DemoContact]:
    """Return a stable Talk contact list."""
    return [
        _DemoContact("Hagar", "sip:hagar@example.com", favorite=True),
        _DemoContact("Mama", "sip:mama@example.com", favorite=True),
        _DemoContact("Papa", "sip:papa@example.com"),
        _DemoContact("Auntie", "sip:auntie@example.com"),
    ]


def _build_music_service() -> _FakeMusicService:
    """Return deterministic local playlist and recents data."""
    from yoyopod.audio.history import RecentTrackEntry

    return _FakeMusicService(
        playlists=[
            _DemoPlaylistSummary("Morning Boost", "playlist:morning", 18),
            _DemoPlaylistSummary("Arabic Favorites", "playlist:arabic", 26),
            _DemoPlaylistSummary("Wind Down", "playlist:winddown", 14),
        ],
        recents=[
            RecentTrackEntry(
                uri="track:golden-hour",
                title="Golden Hour",
                artist="Kacey Musgraves",
                album="Golden Hour",
            ),
            RecentTrackEntry(
                uri="track:midnight-train",
                title="Midnight Train",
                artist="Sam Smith",
                album="Gloria",
            ),
            RecentTrackEntry(
                uri="track:coastline",
                title="Coastline",
                artist="Hollow Coves",
                album="Moments",
            ),
        ],
    )


def _build_call_history_store() -> _FakeCallHistoryStore:
    """Return deterministic Talk recents."""
    from yoyopod.communication.calling.history import CallHistoryEntry

    entries = [
        CallHistoryEntry.create(
            direction="incoming",
            display_name="Mama",
            sip_address="sip:mama@example.com",
            outcome="missed",
        ),
        CallHistoryEntry.create(
            direction="outgoing",
            display_name="Papa",
            sip_address="sip:papa@example.com",
            outcome="completed",
            duration_seconds=187,
        ),
        CallHistoryEntry.create(
            direction="incoming",
            display_name="Auntie",
            sip_address="sip:auntie@example.com",
            outcome="completed",
            duration_seconds=64,
        ),
    ]
    return _FakeCallHistoryStore(entries)


def _build_power_snapshot() -> object:
    """Return one realistic power snapshot for the Setup pages."""
    from yoyopod.power import BatteryState, PowerDeviceInfo, PowerSnapshot, RTCState, ShutdownState

    checked_at = datetime.now(timezone.utc)
    return PowerSnapshot(
        available=True,
        checked_at=checked_at,
        source="pisugar",
        device=PowerDeviceInfo(model="PiSugar 3", firmware_version="1.0.23"),
        battery=BatteryState(
            level_percent=84.0,
            voltage_volts=4.11,
            charging=False,
            power_plugged=False,
            temperature_celsius=31.0,
        ),
        rtc=RTCState(
            time=checked_at,
            alarm_enabled=True,
            alarm_time=checked_at.replace(hour=7, minute=30, second=0, microsecond=0),
        ),
        shutdown=ShutdownState(
            safe_shutdown_level_percent=10.0,
            safe_shutdown_delay_seconds=20,
        ),
        error="",
    )


def _build_power_status() -> dict[str, object]:
    """Return one realistic runtime/care status payload."""
    return {
        "app_uptime_seconds": 3672,
        "screen_awake": True,
        "screen_on_seconds": 1240,
        "screen_idle_seconds": 7,
        "screen_timeout_seconds": 120,
        "warning_threshold_percent": 20,
        "critical_shutdown_percent": 10,
        "shutdown_delay_seconds": 15,
        "shutdown_pending": False,
        "watchdog_enabled": True,
        "watchdog_active": True,
        "watchdog_feed_suppressed": False,
    }


def _build_talk_contact_screen(display: object) -> object:
    """Build the main Talk contact-action screen."""
    from yoyopod.ui.screens import TalkContactScreen

    context = _build_context()
    context.set_talk_contact(name="Mama", sip_address="sip:mama@example.com")  # type: ignore[union-attr]
    return TalkContactScreen(
        display,
        context,
        voip_manager=_FakeVoipManager(),
    )


def _build_voice_note_recording_screen(display: object) -> object:
    """Build the voice-note recording state."""
    from yoyopod.ui.screens import VoiceNoteScreen
    from yoyopod.ui.screens.voip.voice_note import (
        build_voice_note_actions,
        build_voice_note_state_provider,
    )

    context = _build_context()
    context.set_voice_note_recipient(name="Mama", sip_address="sip:mama@example.com")  # type: ignore[union-attr]
    draft = _DemoVoiceNoteDraft(
        recipient_address="sip:mama@example.com",
        recipient_name="Mama",
        file_path="data/voice_notes/mama.wav",
        duration_ms=3200,
        send_state="recording",
        status_text="Recording...",
    )
    voip_manager = _FakeVoipManager(active_voice_note=draft)
    return VoiceNoteScreen(
        display,
        context,
        state_provider=build_voice_note_state_provider(
            context=context,
            voip_manager=voip_manager,
        ),
        actions=build_voice_note_actions(voip_manager=voip_manager),
    )


def _build_voice_note_review_screen(display: object) -> object:
    """Build the voice-note review state."""
    from yoyopod.ui.screens import VoiceNoteScreen
    from yoyopod.ui.screens.voip.voice_note import (
        build_voice_note_actions,
        build_voice_note_state_provider,
    )

    context = _build_context()
    context.set_voice_note_recipient(name="Mama", sip_address="sip:mama@example.com")  # type: ignore[union-attr]
    draft = _DemoVoiceNoteDraft(
        recipient_address="sip:mama@example.com",
        recipient_name="Mama",
        file_path="data/voice_notes/mama.wav",
        duration_ms=4200,
        send_state="review",
        status_text="Ready to send",
    )
    voip_manager = _FakeVoipManager(active_voice_note=draft)
    return VoiceNoteScreen(
        display,
        context,
        state_provider=build_voice_note_state_provider(
            context=context,
            voip_manager=voip_manager,
        ),
        actions=build_voice_note_actions(voip_manager=voip_manager),
    )


def _build_voice_note_sent_screen(display: object) -> object:
    """Build the voice-note sent state."""
    from yoyopod.ui.screens import VoiceNoteScreen
    from yoyopod.ui.screens.voip.voice_note import (
        build_voice_note_actions,
        build_voice_note_state_provider,
    )

    context = _build_context()
    context.set_voice_note_recipient(name="Mama", sip_address="sip:mama@example.com")  # type: ignore[union-attr]
    draft = _DemoVoiceNoteDraft(
        recipient_address="sip:mama@example.com",
        recipient_name="Mama",
        file_path="data/voice_notes/mama.wav",
        duration_ms=4200,
        send_state="sent",
        status_text="Sent",
        message_id="demo-note",
    )
    voip_manager = _FakeVoipManager(active_voice_note=draft)
    return VoiceNoteScreen(
        display,
        context,
        state_provider=build_voice_note_state_provider(
            context=context,
            voip_manager=voip_manager,
        ),
        actions=build_voice_note_actions(voip_manager=voip_manager),
    )


def _build_now_playing_backend(*, playback_state: str) -> object:
    """Return a deterministic backend state for now-playing captures."""
    from yoyopod.audio import MockMusicBackend
    from yoyopod.audio.music.models import Track as PlaybackTrack

    backend = MockMusicBackend()
    if playback_state != "offline":
        backend.start()
        backend.current_track = PlaybackTrack(
            uri="/music/golden-hour.mp3",
            name="Golden Hour",
            artists=["Kacey Musgraves"],
            length=214000,
        )
        backend.time_position = 74000
        if playback_state == "playing":
            backend.play()
        elif playback_state == "paused":
            backend.pause()
    return backend


def _build_now_playing_screen(display: object, *, playback_state: str) -> object:
    """Build a now-playing screen wired through the playback facade seam."""

    from yoyopod.ui.screens import NowPlayingScreen
    from yoyopod.ui.screens.music.now_playing import (
        build_now_playing_actions,
        build_now_playing_state_provider,
    )

    context = _build_context()
    backend = _build_now_playing_backend(playback_state=playback_state)
    return NowPlayingScreen(
        display,
        context,
        state_provider=build_now_playing_state_provider(
            context=context,
            music_backend=backend,
        ),
        actions=build_now_playing_actions(
            context=context,
            music_backend=backend,
        ),
    )


def _build_power_screen(
    display: object,
    *,
    power_snapshot: object,
    network_manager: object | None = None,
) -> object:
    """Build a Setup screen wired through the prepared power facade seam."""

    from yoyopod.ui.screens import PowerScreen
    from yoyopod.ui.screens.system.power import (
        build_power_screen_actions,
        build_power_screen_state_provider,
    )

    context = _build_context()
    return PowerScreen(
        display,
        context,
        state_provider=build_power_screen_state_provider(
            power_manager=_FakePowerManager(power_snapshot),
            network_manager=network_manager,
            status_provider=_build_power_status,
        ),
        actions=build_power_screen_actions(network_manager=network_manager),
    )
