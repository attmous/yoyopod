#!/usr/bin/env python3
"""Capture a deterministic gallery of Whisplay LVGL screens."""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from yoyopy.app_context import AppContext, Playlist, Track as ContextTrack
from yoyopy.audio import MockMusicBackend, Track as PlaybackTrack
from yoyopy.audio.history import RecentTrackEntry
from yoyopy.power import BatteryState, PowerDeviceInfo, PowerSnapshot, RTCState, ShutdownState
from yoyopy.ui.display import Display
from yoyopy.ui.input import InteractionProfile
from yoyopy.ui.screens import (
    AskScreen,
    CallHistoryScreen,
    CallScreen,
    ContactListScreen,
    InCallScreen,
    IncomingCallScreen,
    ListenScreen,
    NowPlayingScreen,
    OutgoingCallScreen,
    PlaylistScreen,
    PowerScreen,
    RecentTracksScreen,
    TalkContactScreen,
    VoiceNoteScreen,
)
from yoyopy.voip.history import CallHistoryEntry


def configure_logging(verbose: bool) -> None:
    """Configure concise human-readable logging."""

    logger.remove()
    logger.add(
        sys.stderr,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
        level="DEBUG" if verbose else "INFO",
    )


@dataclass(frozen=True, slots=True)
class DemoContact:
    """Minimal contact shape used by the Whisplay gallery."""

    name: str
    sip_address: str
    favorite: bool = False
    notes: str = ""

    @property
    def display_name(self) -> str:
        return self.notes or self.name


@dataclass(frozen=True, slots=True)
class DemoPlaylistSummary:
    """Minimal playlist list item for the gallery."""

    name: str
    uri: str
    track_count: int = 0


@dataclass(frozen=True, slots=True)
class DemoVoiceNote:
    """Minimal latest-voice-note summary."""

    local_file_path: str


@dataclass(slots=True)
class DemoVoiceNoteDraft:
    """Minimal active draft consumed by VoiceNoteScreen."""

    recipient_address: str
    recipient_name: str
    file_path: str
    duration_ms: int
    send_state: str
    status_text: str = ""
    message_id: str = ""


class FakeConfigManager:
    """Small contact/config double for Talk screens."""

    def __init__(self, contacts: list[DemoContact]) -> None:
        self._contacts = list(contacts)

    def get_contacts(self) -> list[DemoContact]:
        return list(self._contacts)


class FakeMusicService:
    """Minimal local-music service used for deterministic captures."""

    def __init__(
        self,
        *,
        playlists: list[DemoPlaylistSummary],
        recents: list[RecentTrackEntry],
    ) -> None:
        self.is_available = True
        self._playlists = list(playlists)
        self._recents = list(recents)

    def list_playlists(self, *, fetch_track_counts: bool = False) -> list[DemoPlaylistSummary]:
        return list(self._playlists)

    def list_recent_tracks(self) -> list[RecentTrackEntry]:
        return list(self._recents)

    def load_playlist(self, _uri: str) -> bool:
        return True

    def play_recent_track(self, _uri: str) -> bool:
        return True


class FakeCallHistoryStore:
    """Minimal call-history store for the recents screen."""

    def __init__(self, entries: list[CallHistoryEntry]) -> None:
        self._entries = list(entries)

    def list_recent(self) -> list[CallHistoryEntry]:
        return list(self._entries)

    def mark_all_seen(self) -> None:
        for entry in self._entries:
            entry.seen = True

    def missed_count(self) -> int:
        return sum(1 for entry in self._entries if entry.is_unseen_missed)

    def recent_preview(self) -> list[str]:
        return [entry.title for entry in self._entries[:3]]


class FakePowerManager:
    """Minimal power manager exposing one stable snapshot."""

    def __init__(self, snapshot: PowerSnapshot) -> None:
        self._snapshot = snapshot

    def get_snapshot(self) -> PowerSnapshot:
        return self._snapshot


class FakeVoipManager:
    """Minimal VoIP facade used by Talk and call-state captures."""

    def __init__(
        self,
        *,
        active_voice_note: DemoVoiceNoteDraft | None = None,
        latest_notes: dict[str, DemoVoiceNote] | None = None,
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

    def latest_voice_note_for_contact(self, sip_address: str) -> DemoVoiceNote | None:
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
        self.active_voice_note = DemoVoiceNoteDraft(
            recipient_address=recipient_address,
            recipient_name=recipient_name,
            file_path="data/voice_notes/demo.wav",
            duration_ms=0,
            send_state="recording",
            status_text="Recording...",
        )
        return True

    def stop_voice_note_recording(self) -> DemoVoiceNoteDraft | None:
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

    def get_active_voice_note(self) -> DemoVoiceNoteDraft | None:
        return self.active_voice_note


@dataclass(frozen=True, slots=True)
class CaptureSpec:
    """One deterministic screen capture target."""

    name: str
    build_screen: Callable[[], object]
    prepare: Callable[[object], None] | None = None


def _pump_display(display: Display, duration_seconds: float) -> None:
    """Let LVGL flush and settle before capturing."""

    backend = display.get_ui_backend()
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
    display: Display,
    spec: CaptureSpec,
    output_dir: Path,
    *,
    settle_seconds: float,
) -> None:
    """Render one screen state and save an LVGL readback."""

    screen = spec.build_screen()
    screen.enter()
    try:
        if spec.prepare is not None:
            spec.prepare(screen)
        screen.render()
        _pump_display(display, settle_seconds)

        adapter = display.get_adapter()
        save_readback = getattr(adapter, "save_screenshot_readback", None)
        save_shadow = getattr(adapter, "save_screenshot", None)
        if not callable(save_readback):
            raise RuntimeError("active display adapter does not support LVGL readback screenshots")
        if not callable(save_shadow):
            raise RuntimeError("active display adapter does not support shadow-buffer screenshots")

        output_path = output_dir / f"{spec.name}.png"
        if save_readback(str(output_path)):
            logger.info("Captured {} via LVGL readback", output_path.name)
            return
        if save_shadow(str(output_path)):
            logger.warning("Captured {} via shadow-buffer fallback", output_path.name)
            return
        raise RuntimeError(f"failed to save screenshot to {output_path}")
    finally:
        screen.exit()
        backend = display.get_ui_backend()
        if backend is not None and getattr(backend, "initialized", False):
            backend.clear()
            _pump_display(display, 0.05)


def _build_context() -> AppContext:
    """Create one stable one-button app context."""

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

    demo_playlist = Playlist(
        name="Road Trip",
        tracks=[
            ContextTrack(title="Golden Hour", artist="Kacey Musgraves", duration=214.0),
            ContextTrack(title="Midnight Train", artist="Sam Smith", duration=198.0),
        ],
    )
    context.set_playlist(demo_playlist)
    context.playback.is_playing = True
    context.playback.is_paused = False
    context.playback.is_stopped = False
    context.playback.position = 74.0
    return context


def _build_contacts() -> list[DemoContact]:
    """Return a stable Talk contact list."""

    return [
        DemoContact("Hagar", "sip:hagar@example.com", favorite=True),
        DemoContact("Mama", "sip:mama@example.com", favorite=True),
        DemoContact("Papa", "sip:papa@example.com"),
        DemoContact("Auntie", "sip:auntie@example.com"),
    ]


def _build_music_service() -> FakeMusicService:
    """Return deterministic local playlist and recents data."""

    return FakeMusicService(
        playlists=[
            DemoPlaylistSummary("Morning Boost", "playlist:morning", 18),
            DemoPlaylistSummary("Arabic Favorites", "playlist:arabic", 26),
            DemoPlaylistSummary("Wind Down", "playlist:winddown", 14),
        ],
        recents=[
            RecentTrackEntry(uri="track:golden-hour", title="Golden Hour", artist="Kacey Musgraves", album="Golden Hour"),
            RecentTrackEntry(uri="track:midnight-train", title="Midnight Train", artist="Sam Smith", album="Gloria"),
            RecentTrackEntry(uri="track:coastline", title="Coastline", artist="Hollow Coves", album="Moments"),
        ],
    )


def _build_call_history_store() -> FakeCallHistoryStore:
    """Return deterministic Talk recents."""

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
    return FakeCallHistoryStore(entries)


def _build_power_snapshot() -> PowerSnapshot:
    """Return one realistic power snapshot for the Setup pages."""

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


def _build_talk_contact_screen(display: Display) -> TalkContactScreen:
    """Build a Talk contact screen with a latest-note action."""

    context = _build_context()
    context.set_talk_contact(name="Mama", sip_address="sip:mama@example.com")
    return TalkContactScreen(
        display,
        context,
        voip_manager=FakeVoipManager(
            latest_notes={"sip:mama@example.com": DemoVoiceNote("data/voice_notes/mama.wav")}
        ),
    )


def _build_voice_note_review_screen(display: Display) -> VoiceNoteScreen:
    """Build the voice-note review state."""

    context = _build_context()
    context.set_voice_note_recipient(name="Mama", sip_address="sip:mama@example.com")
    draft = DemoVoiceNoteDraft(
        recipient_address="sip:mama@example.com",
        recipient_name="Mama",
        file_path="data/voice_notes/mama.wav",
        duration_ms=4200,
        send_state="review",
        status_text="Ready to send",
    )
    return VoiceNoteScreen(
        display,
        context,
        voip_manager=FakeVoipManager(active_voice_note=draft),
    )


def _build_now_playing_backend(*, playback_state: str) -> MockMusicBackend:
    """Return a deterministic backend state for now-playing captures."""

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


def _advance_ask_to_response(screen: object) -> None:
    """Drive AskScreen into its response state for a second capture."""

    screen.on_select()
    screen.on_select()
    screen.on_select()


def build_capture_specs(display: Display) -> list[CaptureSpec]:
    """Build the deterministic gallery sequence."""

    contacts = _build_contacts()
    config_manager = FakeConfigManager(contacts)
    music_service = _build_music_service()
    call_history_store = _build_call_history_store()
    power_snapshot = _build_power_snapshot()

    return [
        CaptureSpec(
            "01_listen",
            lambda: ListenScreen(display, _build_context(), music_service=None),
        ),
        CaptureSpec(
            "02_playlists",
            lambda: PlaylistScreen(display, _build_context(), music_service=music_service),
            prepare=lambda screen: setattr(screen, "selected_index", 1),
        ),
        CaptureSpec(
            "03_recent",
            lambda: RecentTracksScreen(display, _build_context(), music_service=music_service),
            prepare=lambda screen: setattr(screen, "selected_index", 1),
        ),
        CaptureSpec(
            "04_now_playing",
            lambda: NowPlayingScreen(
                display,
                _build_context(),
                music_backend=_build_now_playing_backend(playback_state="playing"),
            ),
        ),
        CaptureSpec(
            "04b_now_playing_paused",
            lambda: NowPlayingScreen(
                display,
                _build_context(),
                music_backend=_build_now_playing_backend(playback_state="paused"),
            ),
        ),
        CaptureSpec(
            "04c_now_playing_offline",
            lambda: NowPlayingScreen(
                display,
                _build_context(),
                music_backend=_build_now_playing_backend(playback_state="offline"),
            ),
        ),
        CaptureSpec(
            "05_talk",
            lambda: CallScreen(
                display,
                _build_context(),
                voip_manager=FakeVoipManager(),
                config_manager=config_manager,
                call_history_store=call_history_store,
            ),
        ),
        CaptureSpec(
            "06_talk_contact",
            lambda: _build_talk_contact_screen(display),
        ),
        CaptureSpec(
            "07_contacts",
            lambda: ContactListScreen(
                display,
                _build_context(),
                voip_manager=FakeVoipManager(),
                config_manager=config_manager,
            ),
            prepare=lambda screen: setattr(screen, "selected_index", 1),
        ),
        CaptureSpec(
            "08_call_history",
            lambda: CallHistoryScreen(
                display,
                _build_context(),
                voip_manager=FakeVoipManager(),
                call_history_store=call_history_store,
            ),
            prepare=lambda screen: setattr(screen, "selected_index", 1),
        ),
        CaptureSpec(
            "09_voice_note_review",
            lambda: _build_voice_note_review_screen(display),
            prepare=lambda screen: setattr(screen, "_selected_action_index", 1),
        ),
        CaptureSpec(
            "10_ask_idle",
            lambda: AskScreen(display, _build_context()),
        ),
        CaptureSpec(
            "11_ask_response",
            lambda: AskScreen(display, _build_context()),
            prepare=lambda screen: _advance_ask_to_response(screen),
        ),
        CaptureSpec(
            "12_power",
            lambda: PowerScreen(
                display,
                _build_context(),
                power_manager=FakePowerManager(power_snapshot),
                status_provider=_build_power_status,
            ),
        ),
        CaptureSpec(
            "13_time",
            lambda: PowerScreen(
                display,
                _build_context(),
                power_manager=FakePowerManager(power_snapshot),
                status_provider=_build_power_status,
            ),
            prepare=lambda screen: setattr(screen, "page_index", 1),
        ),
        CaptureSpec(
            "14_care",
            lambda: PowerScreen(
                display,
                _build_context(),
                power_manager=FakePowerManager(power_snapshot),
                status_provider=_build_power_status,
            ),
            prepare=lambda screen: setattr(screen, "page_index", 2),
        ),
        CaptureSpec(
            "15_incoming_call",
            lambda: IncomingCallScreen(
                display,
                _build_context(),
                voip_manager=FakeVoipManager(),
                caller_address="sip:mama@example.com",
                caller_name="Mama",
            ),
        ),
        CaptureSpec(
            "16_outgoing_call",
            lambda: OutgoingCallScreen(
                display,
                _build_context(),
                voip_manager=FakeVoipManager(
                    caller_info={
                        "display_name": "Papa",
                        "address": "sip:papa@example.com",
                    }
                ),
            ),
        ),
        CaptureSpec(
            "17_in_call",
            lambda: InCallScreen(
                display,
                _build_context(),
                voip_manager=FakeVoipManager(
                    caller_info={"display_name": "Mama"},
                    duration_seconds=187,
                    muted=False,
                ),
            ),
        ),
    ]


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        default="temp/pi_gallery",
        help="Directory where PNG captures should be written",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="Use the Whisplay adapter in simulation mode instead of driving hardware",
    )
    parser.add_argument(
        "--settle-seconds",
        type=float,
        default=0.18,
        help="How long to let LVGL settle before each capture",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging",
    )
    return parser


def main() -> int:
    """CLI entry point."""

    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.verbose)

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    display = Display(
        hardware="whisplay",
        simulate=args.simulate,
        whisplay_renderer="lvgl",
    )
    backend = display.get_ui_backend()
    if backend is None or not getattr(backend, "available", False):
        raise SystemExit(
            "LVGL backend unavailable. Build it first with `uv run python scripts/lvgl_build.py`."
        )
    if not backend.initialize():
        raise SystemExit("Failed to initialize the Whisplay LVGL backend")
    display.refresh_backend_kind()

    try:
        for spec in build_capture_specs(display):
            _capture_screen(
                display,
                spec,
                output_dir,
                settle_seconds=args.settle_seconds,
            )
    finally:
        display.cleanup()

    logger.info("Saved {} screenshots to {}", len(list(output_dir.glob('*.png'))), output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
