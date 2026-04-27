"""Shared app-facing runtime context and the state objects it owns."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from loguru import logger

from yoyopod.backends.music import PlaybackQueue, Track
from yoyopod.ui.input.hal import InteractionProfile

if TYPE_CHECKING:
    from yoyopod.core.audio_volume import AudioVolumeController
    from yoyopod.integrations.power.models import PowerSnapshot

__all__ = [
    "ActiveVoiceNoteState",
    "AppContext",
    "MediaRuntimeState",
    "NetworkRuntimeState",
    "PlaybackState",
    "PowerRuntimeState",
    "ScreenRuntimeState",
    "TalkRuntimeState",
    "VoiceInteractionState",
    "VoiceState",
    "VoipRuntimeState",
]

_VOICE_UNSET = object()


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
    running: bool = False
    registration_state: str = "none"

    def update(
        self,
        *,
        configured: bool,
        ready: bool,
        running: bool | None = None,
        registration_state: str | None = None,
    ) -> None:
        """Refresh the cached VoIP availability."""

        self.configured = configured
        self.ready = ready
        if running is not None:
            self.running = running
        if registration_state is not None:
            self.registration_state = registration_state


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


class AppContext:
    """
    Shared app-facing runtime state.

    `AppContext` owns focused runtime state objects grouped by domain.
    """

    def __init__(
        self,
        interaction_profile: InteractionProfile = InteractionProfile.STANDARD,
    ) -> None:
        self.audio_volume_controller: AudioVolumeController | None = None
        self.interaction_profile = interaction_profile

        self.media = MediaRuntimeState()
        self.power = PowerRuntimeState()
        self.network = NetworkRuntimeState()
        self.screen = ScreenRuntimeState()
        self.voip = VoipRuntimeState()
        self.talk = TalkRuntimeState()
        self.voice = VoiceState(output_volume=self.media.playback.volume)

        # Existing user-tunable values still live as a simple compatibility bag.
        self.settings = {
            "brightness": 100,
            "auto_sleep_minutes": 30,
            "parental_controls_enabled": False,
            "max_volume": 80,
        }

        # Navigation history remains screen-manager-adjacent scratch state.
        self.navigation_history: list[str] = []
        self.cloud_status: dict[str, object] = {
            "device_id": "",
            "provisioning_state": "unprovisioned",
            "cloud_state": "offline",
            "config_source": "none",
            "config_version": 0,
            "backend_reachable": None,
            "last_successful_sync": None,
            "last_error_summary": "",
            "unapplied_keys": [],
        }

        logger.info("AppContext initialized")

    def set_playlist(self, playlist: PlaybackQueue) -> None:
        """Set the current playlist."""

        self.media.set_playlist(playlist)
        logger.info(f"Playlist set: {playlist.name} ({len(playlist.tracks)} tracks)")

    def get_current_track(self) -> Track | None:
        """Get the currently playing/selected track."""

        return self.media.current_track()

    def play(self) -> bool:
        """Start playback when a current track exists."""

        track = self.media.current_track()
        if track is None:
            logger.warning("Cannot play: no track selected")
            return False

        self.media.play()
        logger.info(f"Playing: {track.name}")
        return True

    def pause(self) -> None:
        """Pause playback."""

        playback = self.media.playback
        if not playback.is_playing:
            return

        self.media.pause()
        logger.info("Playback paused")

    def resume(self) -> None:
        """Resume playback."""

        playback = self.media.playback
        if not playback.is_paused:
            return

        self.media.resume()
        logger.info("Playback resumed")

    def stop(self) -> None:
        """Stop playback."""

        self.media.stop()
        logger.info("Playback stopped")

    def toggle_playback(self) -> bool:
        """Toggle between play and pause."""

        playback = self.media.playback
        if playback.is_playing:
            self.pause()
            return False
        if playback.is_paused or playback.is_stopped:
            if playback.is_stopped:
                self.play()
            else:
                self.resume()
            return True
        return False

    def cache_output_volume(self, volume: int) -> int:
        """Keep playback and voice volume caches aligned."""

        cached_volume = max(0, min(100, int(volume)))
        self.media.playback.volume = cached_volume
        self.voice.output_volume = cached_volume
        return cached_volume

    def max_output_volume(self) -> int:
        """Return the configured raw output ceiling used for the 0-10 user scale."""

        return max(0, min(100, int(self.settings.get("max_volume", 100))))

    def output_volume_level(self, volume: int | None = None) -> int:
        """Map a raw output volume to the user-facing 0-10 scale."""

        raw_volume = self.media.playback.volume if volume is None else volume
        max_volume = self.max_output_volume()
        if max_volume <= 0:
            return 0
        clamped = max(0, min(max_volume, int(raw_volume)))
        return max(0, min(10, int(round((clamped * 10) / max_volume))))

    def output_volume_from_level(self, level: int) -> int:
        """Map a user-facing 0-10 volume level to a raw output volume."""

        max_volume = self.max_output_volume()
        clamped_level = max(0, min(10, int(level)))
        if max_volume <= 0 or clamped_level == 0:
            return 0
        return max(0, min(max_volume, int(round((max_volume * clamped_level) / 10))))

    def volume_level_up(self, step: int = 1) -> int:
        """Increase volume by user-facing levels and return the raw output volume."""

        level = self.output_volume_level() + max(1, int(step))
        self.set_volume(self.output_volume_from_level(level))
        return self.media.playback.volume

    def volume_level_down(self, step: int = 1) -> int:
        """Decrease volume by user-facing levels and return the raw output volume."""

        level = self.output_volume_level() - max(1, int(step))
        self.set_volume(self.output_volume_from_level(level))
        return self.media.playback.volume

    def set_volume(self, volume: int) -> None:
        """Set playback volume while respecting the configured max volume."""

        volume = max(0, min(int(volume), self.max_output_volume()))
        if self.audio_volume_controller is not None:
            applied = self.audio_volume_controller.set_output_volume(volume)
            if not applied:
                self.cache_output_volume(volume)
        else:
            self.cache_output_volume(volume)
        logger.debug(f"Volume set to {volume}")

    def volume_up(self, step: int = 5) -> int:
        """Increase volume."""

        playback = self.media.playback
        self.set_volume(playback.volume + step)
        return playback.volume

    def volume_down(self, step: int = 5) -> int:
        """Decrease volume."""

        playback = self.media.playback
        self.set_volume(playback.volume - step)
        return playback.volume

    def next_track(self) -> Track | None:
        """Skip to the next track."""

        track = self.media.next_track()
        if track is None:
            return None

        logger.info(f"Next track: {track.name}")
        if self.media.playback.is_playing:
            self.play()
        return track

    def previous_track(self) -> Track | None:
        """Go to the previous track."""

        track = self.media.previous_track()
        if track is None:
            return None

        logger.info(f"Previous track: {track.name}")
        if self.media.playback.is_playing:
            self.play()
        return track

    def create_demo_playlist(self) -> PlaybackQueue:
        """Create a demo playlist for testing."""

        demo_tracks = [
            Track(
                uri="demo://the-adventure-begins",
                name="The Adventure Begins",
                artists=["Story Time Stories"],
                length=180_000,
            ),
            Track(
                uri="demo://journey-to-the-mountains",
                name="Journey to the Mountains",
                artists=["Story Time Stories"],
                length=240_000,
            ),
            Track(
                uri="demo://the-magic-forest",
                name="The Magic Forest",
                artists=["Bedtime Tales"],
                length=200_000,
            ),
            Track(
                uri="demo://ocean-waves-and-dreams",
                name="Ocean Waves & Dreams",
                artists=["Relaxing Sounds"],
                length=300_000,
            ),
        ]

        playlist = PlaybackQueue(name="Demo Playlist", tracks=demo_tracks)
        self.media.playlists["demo"] = playlist
        logger.info(f"Created demo playlist with {len(demo_tracks)} tracks")
        return playlist

    def get_playback_progress(self) -> float:
        """Get current playback progress as a percentage."""

        return self.media.playback_progress()

    def update_system_status(
        self,
        battery: int | None = None,
        signal: int | None = None,
        connected: bool | None = None,
    ) -> None:
        """Update simple cross-cutting status information."""

        if battery is not None:
            self.power.update_battery_percent(battery)
        if signal is not None or connected is not None:
            self.network.update(signal_bars=signal, connected=connected)

    def update_power_status(self, snapshot: "PowerSnapshot") -> None:
        """Update cached power telemetry from the latest backend snapshot."""

        self.power.update_from_snapshot(snapshot)

    def update_voip_status(
        self,
        *,
        configured: bool,
        ready: bool,
        running: bool | None = None,
        registration_state: str | None = None,
    ) -> None:
        """Update cached VoIP availability used by simplified chrome."""

        self.voip.update(
            configured=configured,
            ready=ready,
            running=running,
            registration_state=registration_state,
        )

    def update_network_status(
        self,
        *,
        network_enabled: bool | None = None,
        signal_bars: int | None = None,
        connection_type: str | None = None,
        connected: bool | None = None,
        gps_has_fix: bool | None = None,
    ) -> None:
        """Update cached network telemetry from the modem backend."""

        self.network.update(
            enabled=network_enabled,
            signal_bars=signal_bars,
            connection_type=connection_type,
            connected=connected,
            gps_has_fix=gps_has_fix,
        )

    def update_screen_runtime(
        self,
        *,
        screen_awake: bool,
        app_uptime_seconds: float,
        screen_on_seconds: float,
        idle_seconds: float,
    ) -> None:
        """Update runtime metrics for app uptime and display activity."""

        self.screen.update(
            awake=screen_awake,
            app_uptime_seconds=app_uptime_seconds,
            on_seconds=screen_on_seconds,
            idle_seconds=idle_seconds,
        )

    def update_call_summary(self, *, missed_calls: int, recent_calls: list[str]) -> None:
        """Update Talk summary state used by hub and call-related screens."""

        self.talk.update_call_summary(missed_calls=missed_calls, recent_calls=recent_calls)

    def set_talk_contact(self, *, name: str, sip_address: str) -> None:
        """Store the currently selected Talk contact."""

        self.talk.set_selected_contact(name=name, sip_address=sip_address)

    def set_voice_note_recipient(self, *, name: str, sip_address: str) -> None:
        """Store the currently selected voice-note recipient."""

        self.talk.set_voice_note_recipient(name=name, sip_address=sip_address)

    def update_voice_note_summary(
        self,
        *,
        unread_voice_notes: int,
        latest_voice_note_by_contact: dict[str, dict[str, object]],
    ) -> None:
        """Update unread counts and latest voice-note metadata exposed to Talk."""

        self.talk.update_voice_note_summary(
            unread_voice_notes=unread_voice_notes,
            latest_voice_note_by_contact=latest_voice_note_by_contact,
        )

    def update_active_voice_note(
        self,
        *,
        send_state: str,
        status_text: str = "",
        file_path: str = "",
        duration_ms: int = 0,
    ) -> None:
        """Update the active voice-note UI state for the selected recipient."""

        self.talk.update_active_voice_note(
            send_state=send_state,
            status_text=status_text,
            file_path=file_path,
            duration_ms=duration_ms,
        )

    def configure_voice(
        self,
        *,
        commands_enabled: bool | None = None,
        ai_requests_enabled: bool | None = None,
        screen_read_enabled: bool | None = None,
        stt_enabled: bool | None = None,
        tts_enabled: bool | None = None,
        speaker_device_id: str | None | object = _VOICE_UNSET,
        capture_device_id: str | None | object = _VOICE_UNSET,
    ) -> None:
        """Update persistent voice feature toggles cached in context."""

        if commands_enabled is not None:
            self.voice.commands_enabled = commands_enabled
        if ai_requests_enabled is not None:
            self.voice.ai_requests_enabled = ai_requests_enabled
        if screen_read_enabled is not None:
            self.voice.screen_read_enabled = screen_read_enabled
        if stt_enabled is not None:
            self.voice.stt_enabled = stt_enabled
        if tts_enabled is not None:
            self.voice.tts_enabled = tts_enabled
        if speaker_device_id is not _VOICE_UNSET:
            self.voice.speaker_device_id = speaker_device_id  # type: ignore[assignment]
        if capture_device_id is not _VOICE_UNSET:
            self.voice.capture_device_id = capture_device_id  # type: ignore[assignment]

    def update_voice_backend_status(self, *, stt_available: bool, tts_available: bool) -> None:
        """Update backend availability flags used by voice UI flows."""

        self.voice.stt_available = stt_available
        self.voice.tts_available = tts_available

    def set_mic_muted(self, muted: bool) -> None:
        """Cache the app-facing microphone mute state."""

        self.voice.mic_muted = muted

    def toggle_mic_muted(self) -> bool:
        """Toggle and return the cached app-facing microphone mute state."""

        self.voice.mic_muted = not self.voice.mic_muted
        return self.voice.mic_muted

    def record_voice_transcript(self, transcript: str, *, mode: str) -> None:
        """Cache the latest transcript for command or AI request flows."""

        self.voice.last_transcript = transcript.strip()
        self.voice.last_mode = mode

    def record_voice_response(self, text: str) -> None:
        """Cache the latest spoken response text."""

        self.voice.last_spoken_text = text.strip()

    def update_cloud_status(
        self,
        *,
        device_id: str,
        provisioning_state: str,
        cloud_state: str,
        config_source: str,
        config_version: int,
        backend_reachable: bool | None,
        last_successful_sync: str | None,
        last_error_summary: str,
        unapplied_keys: list[str],
    ) -> None:
        """Cache backend/provisioning state for UI and diagnostics."""

        self.cloud_status = {
            "device_id": device_id,
            "provisioning_state": provisioning_state,
            "cloud_state": cloud_state,
            "config_source": config_source,
            "config_version": int(config_version),
            "backend_reachable": backend_reachable,
            "last_successful_sync": last_successful_sync,
            "last_error_summary": last_error_summary,
            "unapplied_keys": list(unapplied_keys),
        }

    def update_voice_interaction(
        self,
        *,
        phase: str,
        headline: str,
        body: str,
        capture_in_flight: bool | None = None,
        ptt_active: bool | None = None,
        generation: int | None = None,
    ) -> None:
        """Cache the current shared voice interaction state."""

        interaction = self.voice.interaction
        interaction.phase = phase
        interaction.headline = headline
        interaction.body = body
        if capture_in_flight is not None:
            interaction.capture_in_flight = capture_in_flight
        if ptt_active is not None:
            interaction.ptt_active = ptt_active
        if generation is not None:
            interaction.generation = generation
