"""
Focused runtime state objects owned by ``AppContext``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from yoyopy.audio.music.models import PlaybackQueue, Track

if TYPE_CHECKING:
    from yoyopy.power import PowerSnapshot


@dataclass(slots=True)
class PlaybackState:
    """Current playback state."""

    is_playing: bool = False
    is_paused: bool = False
    is_stopped: bool = True
    position: float = 0.0
    volume: int = 50
    is_muted: bool = False


@dataclass(slots=True)
class MediaRuntimeState:
    """Shared playback session and playlist selection state."""

    playback: PlaybackState = field(default_factory=PlaybackState)
    current_playlist: PlaybackQueue | None = None
    playlists: dict[str, PlaybackQueue] = field(default_factory=dict)

    def set_playlist(self, playlist: PlaybackQueue) -> None:
        """Set the active playlist."""

        self.current_playlist = playlist

    def current_track(self) -> Track | None:
        """Return the active track from the selected playlist."""

        if self.current_playlist is None:
            return None
        return self.current_playlist.current_track()

    def play(self) -> bool:
        """Mark playback as active when a track is available."""

        if self.current_track() is None:
            return False

        self.playback.is_playing = True
        self.playback.is_paused = False
        self.playback.is_stopped = False
        return True

    def pause(self) -> None:
        """Mark playback as paused."""

        if not self.playback.is_playing:
            return

        self.playback.is_playing = False
        self.playback.is_paused = True

    def resume(self) -> None:
        """Mark playback as resumed."""

        if not self.playback.is_paused:
            return

        self.playback.is_playing = True
        self.playback.is_paused = False

    def stop(self) -> None:
        """Mark playback as stopped and reset position."""

        self.playback.is_playing = False
        self.playback.is_paused = False
        self.playback.is_stopped = True
        self.playback.position = 0.0

    def next_track(self) -> Track | None:
        """Advance the current playlist."""

        if self.current_playlist is None:
            return None
        return self.current_playlist.next_track()

    def previous_track(self) -> Track | None:
        """Move to the previous track in the current playlist."""

        if self.current_playlist is None:
            return None
        return self.current_playlist.previous_track()

    def playback_progress(self) -> float:
        """Return the active track progress from 0.0 to 1.0."""

        track = self.current_track()
        if track is None or track.length <= 0:
            return 0.0
        return min(1.0, self.playback.position / (track.length / 1000))


@dataclass(slots=True)
class PowerRuntimeState:
    """Battery and external power telemetry exposed to UI/runtime flows."""

    battery_percent: int = 100
    battery_charging: bool = False
    external_power: bool = False
    available: bool = False
    error: str = ""

    def update_battery_percent(self, percent: int) -> None:
        """Clamp and store battery percentage."""

        self.battery_percent = max(0, min(100, int(percent)))

    def update_from_snapshot(self, snapshot: "PowerSnapshot") -> None:
        """Refresh power telemetry from the latest backend snapshot."""

        self.available = snapshot.available
        self.error = snapshot.error

        if snapshot.battery.level_percent is not None:
            self.update_battery_percent(round(snapshot.battery.level_percent))

        if snapshot.battery.charging is not None:
            self.battery_charging = snapshot.battery.charging

        if snapshot.battery.power_plugged is not None:
            self.external_power = snapshot.battery.power_plugged


@dataclass(slots=True)
class NetworkRuntimeState:
    """Connectivity telemetry shown in status chrome and Setup."""

    enabled: bool = False
    signal_strength: int = 4
    connected: bool = False
    connection_type: str = "none"
    gps_has_fix: bool = False

    def update(
        self,
        *,
        enabled: bool | None = None,
        signal_bars: int | None = None,
        connection_type: str | None = None,
        connected: bool | None = None,
        gps_has_fix: bool | None = None,
    ) -> None:
        """Refresh the cached network telemetry."""

        if enabled is not None:
            self.enabled = enabled
        if signal_bars is not None:
            self.signal_strength = max(0, min(4, int(signal_bars)))
        if connection_type is not None:
            self.connection_type = connection_type
        if connected is not None:
            self.connected = connected
        if gps_has_fix is not None:
            self.gps_has_fix = gps_has_fix


@dataclass(slots=True)
class ScreenRuntimeState:
    """Runtime metrics for display activity and app uptime."""

    awake: bool = True
    idle_seconds: int = 0
    on_seconds: int = 0
    app_uptime_seconds: int = 0

    def update(
        self,
        *,
        awake: bool,
        app_uptime_seconds: float,
        on_seconds: float,
        idle_seconds: float,
    ) -> None:
        """Clamp and store display activity metrics."""

        self.awake = awake
        self.app_uptime_seconds = max(0, int(app_uptime_seconds))
        self.on_seconds = max(0, int(on_seconds))
        self.idle_seconds = max(0, int(idle_seconds))


@dataclass(slots=True)
class VoipRuntimeState:
    """App-facing VoIP availability used by chrome and routing."""

    configured: bool = False
    ready: bool = False

    def update(self, *, configured: bool, ready: bool) -> None:
        """Refresh the cached VoIP availability."""

        self.configured = configured
        self.ready = ready


@dataclass(slots=True)
class VoiceInteractionState:
    """Shared state for the active voice interaction session."""

    phase: str = "idle"
    headline: str = "Ask"
    body: str = "Ask me anything..."
    capture_in_flight: bool = False
    ptt_active: bool = False
    generation: int = 0


@dataclass(slots=True)
class VoiceState:
    """Runtime voice settings and recent voice activity."""

    commands_enabled: bool = True
    ai_requests_enabled: bool = True
    screen_read_enabled: bool = False
    stt_enabled: bool = True
    tts_enabled: bool = True
    mic_muted: bool = False
    speaker_device_id: str | None = None
    capture_device_id: str | None = None
    stt_available: bool = False
    tts_available: bool = False
    last_transcript: str = ""
    last_spoken_text: str = ""
    last_mode: str = ""
    output_volume: int = 50
    interaction: VoiceInteractionState = field(default_factory=VoiceInteractionState)


@dataclass(slots=True)
class ActiveVoiceNoteState:
    """Selected voice-note recipient plus the in-flight draft state."""

    recipient_name: str = ""
    recipient_address: str = ""
    send_state: str = "idle"
    status_text: str = ""
    file_path: str = ""
    duration_ms: int = 0

    def set_recipient(self, *, name: str, sip_address: str) -> None:
        """Store the selected recipient and reset any previous draft state."""

        self.recipient_name = name
        self.recipient_address = sip_address
        self.reset()

    def update(
        self,
        *,
        send_state: str,
        status_text: str = "",
        file_path: str = "",
        duration_ms: int = 0,
    ) -> None:
        """Refresh the active draft status."""

        self.send_state = send_state
        self.status_text = status_text
        self.file_path = file_path
        self.duration_ms = max(0, int(duration_ms))

    def reset(self) -> None:
        """Clear transient draft state while retaining the recipient."""

        self.send_state = "idle"
        self.status_text = ""
        self.file_path = ""
        self.duration_ms = 0


@dataclass(slots=True)
class TalkRuntimeState:
    """Talk flow summaries, selected contact, and voice-note draft state."""

    missed_calls: int = 0
    recent_calls: list[str] = field(default_factory=list)
    unread_voice_notes: int = 0
    latest_voice_note_by_contact: dict[str, dict[str, Any]] = field(default_factory=dict)
    selected_contact_name: str = ""
    selected_contact_address: str = ""
    active_voice_note: ActiveVoiceNoteState = field(default_factory=ActiveVoiceNoteState)

    def update_call_summary(self, *, missed_calls: int, recent_calls: list[str]) -> None:
        """Refresh Talk summary values used by hub and history flows."""

        self.missed_calls = max(0, int(missed_calls))
        self.recent_calls = list(recent_calls)

    def set_selected_contact(self, *, name: str, sip_address: str) -> None:
        """Store the currently selected Talk contact."""

        self.selected_contact_name = name
        self.selected_contact_address = sip_address

    def set_voice_note_recipient(self, *, name: str, sip_address: str) -> None:
        """Store the selected voice-note recipient and reset its draft state."""

        self.active_voice_note.set_recipient(name=name, sip_address=sip_address)

    def update_voice_note_summary(
        self,
        *,
        unread_voice_notes: int,
        latest_voice_note_by_contact: dict[str, dict[str, Any]],
    ) -> None:
        """Refresh unread counts and latest voice-note metadata."""

        self.unread_voice_notes = max(0, int(unread_voice_notes))
        self.latest_voice_note_by_contact = dict(latest_voice_note_by_contact)

    def update_active_voice_note(
        self,
        *,
        send_state: str,
        status_text: str = "",
        file_path: str = "",
        duration_ms: int = 0,
    ) -> None:
        """Refresh the active voice-note draft state."""

        self.active_voice_note.update(
            send_state=send_state,
            status_text=status_text,
            file_path=file_path,
            duration_ms=duration_ms,
        )
