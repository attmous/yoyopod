"""src/yoyopod/cli/pi/gallery.py — Capture a deterministic gallery of Whisplay LVGL screens."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Callable

import typer

from yoyopod.cli.common import configure_logging

gallery_app = typer.Typer(
    name="gallery",
    help="Capture a deterministic gallery of Whisplay LVGL screens.",
    invoke_without_command=True,
    no_args_is_help=False,
)


# ---------------------------------------------------------------------------
# Fake/stub helpers (used to build deterministic screen states)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _DemoContact:
    """Minimal contact shape used by the Whisplay gallery."""

    name: str
    sip_address: str
    favorite: bool = False
    notes: str = ""

    @property
    def display_name(self) -> str:
        return self.notes or self.name


@dataclass(frozen=True, slots=True)
class _DemoPlaylistSummary:
    """Minimal playlist list item for the gallery."""

    name: str
    uri: str
    track_count: int = 0


@dataclass(frozen=True, slots=True)
class _DemoVoiceNote:
    """Minimal latest-voice-note summary."""

    local_file_path: str


@dataclass(slots=True)
class _DemoVoiceNoteDraft:
    """Minimal active draft consumed by VoiceNoteScreen."""

    recipient_address: str
    recipient_name: str
    file_path: str
    duration_ms: int
    send_state: str
    status_text: str = ""
    message_id: str = ""


class _FakePeopleDirectory:
    """Small people-directory double for Talk screens."""

    def __init__(self, contacts: list[_DemoContact]) -> None:
        self._contacts = list(contacts)

    def get_contacts(self) -> list[_DemoContact]:
        return list(self._contacts)


class _FakeMusicService:
    """Minimal local-music service used for deterministic captures."""

    def __init__(
        self,
        *,
        playlists: list[_DemoPlaylistSummary],
        recents: list[object],
    ) -> None:
        self.is_available = True
        self._playlists = list(playlists)
        self._recents = list(recents)

    def list_playlists(self, *, fetch_track_counts: bool = False) -> list[_DemoPlaylistSummary]:
        return list(self._playlists)

    def list_recent_tracks(self) -> list[object]:
        return list(self._recents)

    def load_playlist(self, _uri: str) -> bool:
        return True

    def play_recent_track(self, _uri: str) -> bool:
        return True


class _FakeCallHistoryStore:
    """Minimal call-history store for the recents screen."""

    def __init__(self, entries: list[object]) -> None:
        self._entries = list(entries)

    def list_recent(self) -> list[object]:
        return list(self._entries)

    def mark_all_seen(self) -> None:
        for entry in self._entries:
            entry.seen = True  # type: ignore[union-attr]

    def missed_count(self) -> int:
        return sum(1 for entry in self._entries if entry.is_unseen_missed)  # type: ignore[union-attr]

    def recent_preview(self) -> list[str]:
        return [entry.title for entry in self._entries[:3]]  # type: ignore[union-attr]


class _FakePowerManager:
    """Minimal power manager exposing one stable snapshot."""

    def __init__(self, snapshot: object) -> None:
        self._snapshot = snapshot

    def get_snapshot(self) -> object:
        return self._snapshot


class _FakeNetworkManager:
    """Minimal network manager for deterministic Setup captures."""

    def __init__(self, *, gps: object | None = None) -> None:
        from yoyopod.network.models import ModemPhase, ModemState, SignalInfo

        self.config = type("Config", (), {"enabled": True, "gps_enabled": True})()
        self._gps = gps
        self._state = ModemState(
            phase=ModemPhase.REGISTERED,
            signal=SignalInfo(csq=20),
            carrier="Telekom.de",
            network_type="4G",
            sim_ready=True,
            gps=gps,
        )

    @property
    def modem_state(self) -> object:
        return self._state

    def query_gps(self) -> object | None:
        self._state.gps = self._gps
        return self._gps


class _FakeVoipManager:
    """Minimal VoIP facade used by Talk and call-state captures."""

    def __init__(
        self,
        *,
        active_voice_note: _DemoVoiceNoteDraft | None = None,
        latest_notes: dict[str, _DemoVoiceNote] | None = None,
        caller_info: dict[str, str] | None = None,
        duration_seconds: int = 0,
        muted: bool = False,
    ) -> None:
        self._status = {
            "sip_identity": "sip:kid@example.com",
            "running": True,
            "registered": True,
            "registration_state": "ok",
            "call_state": "idle",
        }
        self._latest_notes = dict(latest_notes or {})
        self.active_voice_note = active_voice_note
        self._caller_info = dict(caller_info or {})
        self._duration_seconds = duration_seconds
        self.is_muted = muted

    def get_status(self) -> dict[str, object]:
        return dict(self._status)

    def latest_voice_note_for_contact(self, sip_address: str) -> _DemoVoiceNote | None:
        return self._latest_notes.get(sip_address)

    def play_latest_voice_note(self, _sip_address: str) -> bool:
        return True

    def mark_voice_notes_seen(self, _sip_address: str) -> None:
        return None

    def make_call(self, _sip_address: str, *, contact_name: str = "") -> bool:
        self._caller_info = {
            "display_name": contact_name or "Friend",
            "address": _sip_address,
        }
        self._status["call_state"] = "outgoing"
        return True

    def answer_call(self) -> bool:
        self._status["call_state"] = "active"
        return True

    def reject_call(self) -> bool:
        self._status["call_state"] = "idle"
        return True

    def hangup(self) -> bool:
        self._status["call_state"] = "idle"
        return True

    def toggle_mute(self) -> None:
        self.is_muted = not self.is_muted

    def get_caller_info(self) -> dict[str, str]:
        return dict(self._caller_info)

    def get_call_duration(self) -> int:
        return self._duration_seconds

    def play_voice_note(self, _file_path: str) -> bool:
        return True

    def start_voice_note_recording(self, recipient_address: str, recipient_name: str = "") -> bool:
        self.active_voice_note = _DemoVoiceNoteDraft(
            recipient_address=recipient_address,
            recipient_name=recipient_name,
            file_path="data/voice_notes/demo.wav",
            duration_ms=0,
            send_state="recording",
            status_text="Recording...",
        )
        return True

    def stop_voice_note_recording(self) -> _DemoVoiceNoteDraft | None:
        if self.active_voice_note is None:
            return None
        self.active_voice_note.duration_ms = 4200
        self.active_voice_note.send_state = "review"
        self.active_voice_note.status_text = "Ready to send"
        return self.active_voice_note

    def cancel_voice_note_recording(self) -> bool:
        self.active_voice_note = None
        return True

    def discard_active_voice_note(self) -> None:
        self.active_voice_note = None

    def send_active_voice_note(self) -> bool:
        if self.active_voice_note is None:
            return False
        self.active_voice_note.send_state = "sending"
        self.active_voice_note.status_text = "Sending..."
        self.active_voice_note.message_id = "demo-note"
        return True

    def get_active_voice_note(self) -> _DemoVoiceNoteDraft | None:
        return self.active_voice_note


# ---------------------------------------------------------------------------
# CaptureSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _CaptureSpec:
    """One deterministic screen capture target."""

    name: str
    build_screen: Callable[[], object]
    prepare: Callable[[object], None] | None = None


# ---------------------------------------------------------------------------
# Display / capture helpers
# ---------------------------------------------------------------------------


def _pump_display(display: object, duration_seconds: float) -> None:
    """Let LVGL flush and settle before capturing."""
    from yoyopod.ui.display import Display

    d: Display = display  # type: ignore[assignment]
    backend = d.get_ui_backend()
    if backend is None or not getattr(backend, "initialized", False):
        return

    deadline = time.monotonic() + max(0.01, duration_seconds)
    last_tick = time.monotonic()
    while time.monotonic() < deadline:
        now = time.monotonic()
        delta_ms = int(max(1.0, (now - last_tick) * 1000.0))
        last_tick = now
        backend.pump(delta_ms)
        time.sleep(0.016)


def _capture_screen(
    display: object,
    spec: _CaptureSpec,
    output_dir: Path,
    *,
    settle_seconds: float,
) -> None:
    """Render one screen state and save an LVGL readback."""
    from yoyopod.ui.display import Display

    d: Display = display  # type: ignore[assignment]
    screen = spec.build_screen()
    screen.enter()  # type: ignore[union-attr]
    try:
        if spec.prepare is not None:
            spec.prepare(screen)
        screen.render()  # type: ignore[union-attr]
        _pump_display(display, settle_seconds)

        adapter = d.get_adapter()
        save_readback = getattr(adapter, "save_screenshot_readback", None)
        save_shadow = getattr(adapter, "save_screenshot", None)
        if not callable(save_readback):
            raise RuntimeError("active display adapter does not support LVGL readback screenshots")
        if not callable(save_shadow):
            raise RuntimeError("active display adapter does not support shadow-buffer screenshots")

        output_path = output_dir / f"{spec.name}.png"
        if save_readback(str(output_path)):
            from loguru import logger

            logger.info("Captured {} via LVGL readback", output_path.name)
            return
        if save_shadow(str(output_path)):
            from loguru import logger

            logger.warning("Captured {} via shadow-buffer fallback", output_path.name)
            return
        raise RuntimeError(f"failed to save screenshot to {output_path}")
    finally:
        screen.exit()  # type: ignore[union-attr]
        backend = d.get_ui_backend()
        if backend is not None and getattr(backend, "initialized", False):
            backend.clear()
            _pump_display(display, 0.05)


# ---------------------------------------------------------------------------
# Data builders
# ---------------------------------------------------------------------------


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
                uri="track:coastline", title="Coastline", artist="Hollow Coves", album="Moments"
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


def _advance_ask_to_response(screen: object) -> None:
    """Drive AskScreen into its response state for a second capture."""
    screen.on_select()  # type: ignore[union-attr]
    screen.on_select()  # type: ignore[union-attr]
    screen.on_select()  # type: ignore[union-attr]


def _build_capture_specs(display: object) -> list[_CaptureSpec]:
    """Build the deterministic gallery sequence."""
    from yoyopod.ui.screens import (
        AskScreen,
        CallHistoryScreen,
        CallScreen,
        ContactListScreen,
        InCallScreen,
        IncomingCallScreen,
        ListenScreen,
        OutgoingCallScreen,
        PlaylistScreen,
        RecentTracksScreen,
    )

    contacts = _build_contacts()
    people_directory = _FakePeopleDirectory(contacts)
    music_service = _build_music_service()
    call_history_store = _build_call_history_store()
    power_snapshot = _build_power_snapshot()

    return [
        _CaptureSpec(
            "01_listen",
            lambda: ListenScreen(display, _build_context(), music_service=None),
        ),
        _CaptureSpec(
            "02_playlists",
            lambda: PlaylistScreen(display, _build_context(), music_service=music_service),
            prepare=lambda screen: setattr(screen, "selected_index", 1),
        ),
        _CaptureSpec(
            "03_recent",
            lambda: RecentTracksScreen(display, _build_context(), music_service=music_service),
            prepare=lambda screen: setattr(screen, "selected_index", 1),
        ),
        _CaptureSpec(
            "04_now_playing",
            lambda: _build_now_playing_screen(display, playback_state="playing"),
        ),
        _CaptureSpec(
            "04b_now_playing_paused",
            lambda: _build_now_playing_screen(display, playback_state="paused"),
        ),
        _CaptureSpec(
            "04c_now_playing_offline",
            lambda: _build_now_playing_screen(display, playback_state="offline"),
        ),
        _CaptureSpec(
            "05_talk",
            lambda: CallScreen(
                display,
                _build_context(),
                voip_manager=_FakeVoipManager(),
                people_directory=people_directory,
                call_history_store=call_history_store,
            ),
        ),
        _CaptureSpec(
            "06_talk_contact",
            lambda: _build_talk_contact_screen(display),
        ),
        _CaptureSpec(
            "07_contacts",
            lambda: ContactListScreen(
                display,
                _build_context(),
                voip_manager=_FakeVoipManager(),
                people_directory=people_directory,
            ),
            prepare=lambda screen: setattr(screen, "selected_index", 1),
        ),
        _CaptureSpec(
            "08_call_history",
            lambda: CallHistoryScreen(
                display,
                _build_context(),
                voip_manager=_FakeVoipManager(),
                call_history_store=call_history_store,
            ),
            prepare=lambda screen: setattr(screen, "selected_index", 1),
        ),
        _CaptureSpec(
            "09_voice_note_recording",
            lambda: _build_voice_note_recording_screen(display),
        ),
        _CaptureSpec(
            "09b_voice_note_review",
            lambda: _build_voice_note_review_screen(display),
        ),
        _CaptureSpec(
            "09c_voice_note_sent",
            lambda: _build_voice_note_sent_screen(display),
        ),
        _CaptureSpec(
            "10_ask_idle",
            lambda: AskScreen(display, _build_context()),
        ),
        _CaptureSpec(
            "11_ask_response",
            lambda: AskScreen(display, _build_context()),
            prepare=lambda screen: _advance_ask_to_response(screen),
        ),
        _CaptureSpec(
            "12_power",
            lambda: _build_power_screen(display, power_snapshot=power_snapshot),
        ),
        _CaptureSpec(
            "12b_gps",
            lambda: _build_power_screen(
                display,
                power_snapshot=power_snapshot,
                network_manager=_FakeNetworkManager(),
            ),
            prepare=lambda screen: setattr(screen, "page_index", 2),
        ),
        _CaptureSpec(
            "13_time",
            lambda: _build_power_screen(display, power_snapshot=power_snapshot),
            prepare=lambda screen: setattr(screen, "page_index", 1),
        ),
        _CaptureSpec(
            "14_care",
            lambda: _build_power_screen(display, power_snapshot=power_snapshot),
            prepare=lambda screen: setattr(screen, "page_index", 2),
        ),
        _CaptureSpec(
            "15_incoming_call",
            lambda: IncomingCallScreen(
                display,
                _build_context(),
                voip_manager=_FakeVoipManager(),
                caller_address="sip:mama@example.com",
                caller_name="Mama",
            ),
        ),
        _CaptureSpec(
            "16_outgoing_call",
            lambda: OutgoingCallScreen(
                display,
                _build_context(),
                voip_manager=_FakeVoipManager(
                    caller_info={
                        "display_name": "Papa",
                        "address": "sip:papa@example.com",
                    }
                ),
            ),
        ),
        _CaptureSpec(
            "17_in_call",
            lambda: InCallScreen(
                display,
                _build_context(),
                voip_manager=_FakeVoipManager(
                    caller_info={"display_name": "Mama"},
                    duration_seconds=187,
                    muted=False,
                ),
            ),
        ),
        _CaptureSpec(
            "17b_in_call_muted",
            lambda: InCallScreen(
                display,
                _build_context(),
                voip_manager=_FakeVoipManager(
                    caller_info={"display_name": "Mama"},
                    duration_seconds=187,
                    muted=True,
                ),
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------


@gallery_app.callback(invoke_without_command=True)
def gallery(
    output_dir: Annotated[
        str, typer.Option("--output-dir", help="Directory where PNG captures should be written.")
    ] = "temp/pi_gallery",
    simulate: Annotated[
        bool,
        typer.Option(
            "--simulate",
            help="Use the Whisplay adapter in simulation mode instead of driving hardware.",
        ),
    ] = False,
    settle_seconds: Annotated[
        float,
        typer.Option("--settle-seconds", help="How long to let LVGL settle before each capture."),
    ] = 0.18,
    verbose: Annotated[bool, typer.Option("--verbose", help="Enable DEBUG logging.")] = False,
) -> None:
    """Capture a deterministic gallery of Whisplay LVGL screens."""
    from loguru import logger

    from yoyopod.ui.display import Display

    configure_logging(verbose)

    output_path = Path(output_dir).expanduser().resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    display = Display(
        hardware="whisplay",
        simulate=simulate,
        whisplay_renderer="lvgl",
    )
    backend = display.get_ui_backend()
    if backend is None or not getattr(backend, "available", False):
        logger.error("LVGL backend unavailable. Build it first with `uv run yoyoctl build lvgl`.")
        raise typer.Exit(code=1)
    if not backend.initialize():
        logger.error("Failed to initialize the Whisplay LVGL backend")
        raise typer.Exit(code=1)
    display.refresh_backend_kind()

    try:
        specs = _build_capture_specs(display)
        for spec in specs:
            _capture_screen(
                display,
                spec,
                output_path,
                settle_seconds=settle_seconds,
            )
    finally:
        display.cleanup()

    saved_count = len(list(output_path.glob("*.png")))
    logger.info("Saved {} screenshots to {}", saved_count, output_path)
