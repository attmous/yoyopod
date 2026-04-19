"""
Compatibility wrapper around focused YoyoPod runtime state objects.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from yoyopod.audio.music.models import PlaybackQueue, Track
from yoyopod.runtime_state import (
    ActiveVoiceNoteState,
    MediaRuntimeState,
    NetworkRuntimeState,
    PlaybackState,
    PowerRuntimeState,
    ScreenRuntimeState,
    TalkRuntimeState,
    VoiceInteractionState,
    VoiceState,
    VoipRuntimeState,
)
from yoyopod.ui.input.hal import InteractionProfile

if TYPE_CHECKING:
    from yoyopod.audio.manager import AudioManager
    from yoyopod.audio.volume_controller import AudioVolumeController
    from yoyopod.power import PowerSnapshot

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


class AppContext:
    """
    Shared app-facing runtime state.

    `AppContext` now owns focused runtime state objects and keeps a light
    compatibility surface for existing callers that still read or write the
    old top-level fields.
    """

    def __init__(
        self,
        audio_manager: "AudioManager | None" = None,
        interaction_profile: InteractionProfile = InteractionProfile.STANDARD,
    ) -> None:
        self.audio_manager = audio_manager
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

    @property
    def playback(self) -> PlaybackState:
        """Expose playback state for existing callers."""

        return self.media.playback

    @playback.setter
    def playback(self, value: PlaybackState) -> None:
        self.media.playback = value

    @property
    def current_playlist(self) -> PlaybackQueue | None:
        """Expose the active playlist for existing callers."""

        return self.media.current_playlist

    @current_playlist.setter
    def current_playlist(self, value: PlaybackQueue | None) -> None:
        self.media.current_playlist = value

    @property
    def playlists(self) -> dict[str, PlaybackQueue]:
        """Expose cached playlists for existing callers."""

        return self.media.playlists

    @playlists.setter
    def playlists(self, value: dict[str, PlaybackQueue]) -> None:
        self.media.playlists = value

    @property
    def battery_percent(self) -> int:
        return self.power.battery_percent

    @battery_percent.setter
    def battery_percent(self, value: int) -> None:
        self.power.update_battery_percent(value)

    @property
    def battery_charging(self) -> bool:
        return self.power.battery_charging

    @battery_charging.setter
    def battery_charging(self, value: bool) -> None:
        self.power.battery_charging = value

    @property
    def external_power(self) -> bool:
        return self.power.external_power

    @external_power.setter
    def external_power(self, value: bool) -> None:
        self.power.external_power = value

    @property
    def power_available(self) -> bool:
        return self.power.available

    @power_available.setter
    def power_available(self, value: bool) -> None:
        self.power.available = value

    @property
    def power_error(self) -> str:
        return self.power.error

    @power_error.setter
    def power_error(self, value: str) -> None:
        self.power.error = value

    @property
    def voip_configured(self) -> bool:
        return self.voip.configured

    @voip_configured.setter
    def voip_configured(self, value: bool) -> None:
        self.voip.configured = value

    @property
    def voip_ready(self) -> bool:
        return self.voip.ready

    @voip_ready.setter
    def voip_ready(self, value: bool) -> None:
        self.voip.ready = value

    @property
    def screen_awake(self) -> bool:
        return self.screen.awake

    @screen_awake.setter
    def screen_awake(self, value: bool) -> None:
        self.screen.awake = value

    @property
    def screen_idle_seconds(self) -> int:
        return self.screen.idle_seconds

    @screen_idle_seconds.setter
    def screen_idle_seconds(self, value: int) -> None:
        self.screen.idle_seconds = max(0, int(value))

    @property
    def screen_on_seconds(self) -> int:
        return self.screen.on_seconds

    @screen_on_seconds.setter
    def screen_on_seconds(self, value: int) -> None:
        self.screen.on_seconds = max(0, int(value))

    @property
    def app_uptime_seconds(self) -> int:
        return self.screen.app_uptime_seconds

    @app_uptime_seconds.setter
    def app_uptime_seconds(self, value: int) -> None:
        self.screen.app_uptime_seconds = max(0, int(value))

    @property
    def signal_strength(self) -> int:
        return self.network.signal_strength

    @signal_strength.setter
    def signal_strength(self, value: int) -> None:
        self.network.signal_strength = max(0, min(4, int(value)))

    @property
    def is_connected(self) -> bool:
        return self.network.connected

    @is_connected.setter
    def is_connected(self, value: bool) -> None:
        self.network.connected = value

    @property
    def connection_type(self) -> str:
        return self.network.connection_type

    @connection_type.setter
    def connection_type(self, value: str) -> None:
        self.network.connection_type = value

    @property
    def network_enabled(self) -> bool:
        return self.network.enabled

    @network_enabled.setter
    def network_enabled(self, value: bool) -> None:
        self.network.enabled = value

    @property
    def gps_has_fix(self) -> bool:
        return self.network.gps_has_fix

    @gps_has_fix.setter
    def gps_has_fix(self, value: bool) -> None:
        self.network.gps_has_fix = value

    @property
    def missed_calls(self) -> int:
        return self.talk.missed_calls

    @missed_calls.setter
    def missed_calls(self, value: int) -> None:
        self.talk.missed_calls = max(0, int(value))

    @property
    def recent_calls(self) -> list[str]:
        return self.talk.recent_calls

    @recent_calls.setter
    def recent_calls(self, value: list[str]) -> None:
        self.talk.recent_calls = list(value)

    @property
    def unread_voice_notes(self) -> int:
        return self.talk.unread_voice_notes

    @unread_voice_notes.setter
    def unread_voice_notes(self, value: int) -> None:
        self.talk.unread_voice_notes = max(0, int(value))

    @property
    def latest_voice_note_by_contact(self) -> dict[str, dict[str, object]]:
        return self.talk.latest_voice_note_by_contact

    @latest_voice_note_by_contact.setter
    def latest_voice_note_by_contact(self, value: dict[str, dict[str, object]]) -> None:
        self.talk.latest_voice_note_by_contact = dict(value)

    @property
    def talk_contact_name(self) -> str:
        return self.talk.selected_contact_name

    @talk_contact_name.setter
    def talk_contact_name(self, value: str) -> None:
        self.talk.selected_contact_name = value

    @property
    def talk_contact_address(self) -> str:
        return self.talk.selected_contact_address

    @talk_contact_address.setter
    def talk_contact_address(self, value: str) -> None:
        self.talk.selected_contact_address = value

    @property
    def voice_note_recipient_name(self) -> str:
        return self.talk.active_voice_note.recipient_name

    @voice_note_recipient_name.setter
    def voice_note_recipient_name(self, value: str) -> None:
        self.talk.active_voice_note.recipient_name = value

    @property
    def voice_note_recipient_address(self) -> str:
        return self.talk.active_voice_note.recipient_address

    @voice_note_recipient_address.setter
    def voice_note_recipient_address(self, value: str) -> None:
        self.talk.active_voice_note.recipient_address = value

    @property
    def voice_note_send_state(self) -> str:
        return self.talk.active_voice_note.send_state

    @voice_note_send_state.setter
    def voice_note_send_state(self, value: str) -> None:
        self.talk.active_voice_note.send_state = value

    @property
    def voice_note_status_text(self) -> str:
        return self.talk.active_voice_note.status_text

    @voice_note_status_text.setter
    def voice_note_status_text(self, value: str) -> None:
        self.talk.active_voice_note.status_text = value

    @property
    def voice_note_file_path(self) -> str:
        return self.talk.active_voice_note.file_path

    @voice_note_file_path.setter
    def voice_note_file_path(self, value: str) -> None:
        self.talk.active_voice_note.file_path = value

    @property
    def voice_note_duration_ms(self) -> int:
        return self.talk.active_voice_note.duration_ms

    @voice_note_duration_ms.setter
    def voice_note_duration_ms(self, value: int) -> None:
        self.talk.active_voice_note.duration_ms = max(0, int(value))

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

        if not self.playback.is_playing:
            return

        self.media.pause()
        logger.info("Playback paused")

    def resume(self) -> None:
        """Resume playback."""

        if not self.playback.is_paused:
            return

        self.media.resume()
        logger.info("Playback resumed")

    def stop(self) -> None:
        """Stop playback."""

        self.media.stop()
        logger.info("Playback stopped")

    def toggle_playback(self) -> bool:
        """Toggle between play and pause."""

        if self.playback.is_playing:
            self.pause()
            return False
        if self.playback.is_paused or self.playback.is_stopped:
            if self.playback.is_stopped:
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
        if self.audio_manager is not None:
            self.audio_manager.volume = cached_volume
        return cached_volume

    def set_volume(self, volume: int) -> None:
        """Set playback volume while respecting the configured max volume."""

        max_volume = self.settings.get("max_volume", 100)
        volume = max(0, min(int(volume), int(max_volume)))
        if self.audio_volume_controller is not None:
            applied = self.audio_volume_controller.set_output_volume(volume)
            if not applied:
                self.cache_output_volume(volume)
        else:
            self.cache_output_volume(volume)
        logger.debug(f"Volume set to {volume}")

    def volume_up(self, step: int = 5) -> int:
        """Increase volume."""

        self.set_volume(self.playback.volume + step)
        return self.playback.volume

    def volume_down(self, step: int = 5) -> int:
        """Decrease volume."""

        self.set_volume(self.playback.volume - step)
        return self.playback.volume

    def next_track(self) -> Track | None:
        """Skip to the next track."""

        track = self.media.next_track()
        if track is None:
            return None

        logger.info(f"Next track: {track.name}")
        if self.playback.is_playing:
            self.play()
        return track

    def previous_track(self) -> Track | None:
        """Go to the previous track."""

        track = self.media.previous_track()
        if track is None:
            return None

        logger.info(f"Previous track: {track.name}")
        if self.playback.is_playing:
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
