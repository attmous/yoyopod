"""MusicBackend protocol, MpvBackend, and MockMusicBackend."""

from __future__ import annotations

import time
from typing import Callable, Protocol, runtime_checkable

from loguru import logger

from yoyopy.audio.music.ipc import MpvIpcClient
from yoyopy.audio.music.models import MusicConfig, Track
from yoyopy.audio.music.process import MpvProcess


@runtime_checkable
class MusicBackend(Protocol):
    """Backend contract for music playback. Mirrors VoIPBackend pattern."""

    def start(self) -> bool: ...
    def stop(self) -> None: ...

    @property
    def is_connected(self) -> bool: ...

    def play(self) -> bool: ...
    def pause(self) -> bool: ...
    def stop_playback(self) -> bool: ...
    def next_track(self) -> bool: ...
    def previous_track(self) -> bool: ...

    def set_volume(self, volume: int) -> bool: ...
    def get_volume(self) -> int | None: ...

    def set_audio_device(self, device: str) -> bool: ...

    def get_current_track(self) -> Track | None: ...
    def get_playback_state(self) -> str: ...
    def get_time_position(self) -> int: ...

    def load_tracks(self, uris: list[str]) -> bool: ...
    def load_playlist_file(self, path: str) -> bool: ...

    def on_track_change(self, callback: Callable[[Track | None], None]) -> None: ...
    def on_playback_state_change(self, callback: Callable[[str], None]) -> None: ...
    def on_connection_change(self, callback: Callable[[bool, str], None]) -> None: ...


class MpvBackend:
    """Production music backend driven by an app-managed mpv process."""

    _STARTUP_CONNECT_RETRIES = 30
    _STARTUP_CONNECT_DELAY = 0.1
    _STARTUP_SPAWN_ATTEMPTS = 4

    def __init__(self, config: MusicConfig) -> None:
        self.config = config
        self._process = MpvProcess(config)
        self._ipc = MpvIpcClient(config.mpv_socket)
        self._connected = False
        self._current_track: Track | None = None
        self._playback_state = "stopped"
        self._event_handler_registered = False
        self._cached_path: str | None = None
        self._cached_metadata: dict[str, object] = {}
        self._cached_duration: object | None = None
        self._cached_media_title: str | None = None

        self._track_change_callbacks: list[Callable[[Track | None], None]] = []
        self._playback_state_callbacks: list[Callable[[str], None]] = []
        self._connection_change_callbacks: list[Callable[[bool, str], None]] = []

    def start(self) -> bool:
        """Spawn mpv, connect IPC, subscribe to events."""
        for attempt in range(1, self._STARTUP_SPAWN_ATTEMPTS + 1):
            if not self._process.spawn():
                return False

            for _ in range(self._STARTUP_CONNECT_RETRIES):
                if self._ipc.connect():
                    break
                time.sleep(self._STARTUP_CONNECT_DELAY)
            else:
                self._process.kill()
                if attempt == self._STARTUP_SPAWN_ATTEMPTS:
                    logger.error(
                        "Failed to connect to mpv IPC after {} spawn attempts",
                        self._STARTUP_SPAWN_ATTEMPTS,
                    )
                    return False
                logger.warning(
                    "mpv IPC did not become ready on spawn attempt {}/{}; retrying",
                    attempt,
                    self._STARTUP_SPAWN_ATTEMPTS,
                )
                continue
            break

        if not self._event_handler_registered:
            self._ipc.on_event(self._handle_mpv_event)
            self._event_handler_registered = True
        self._ipc.start_reader()

        try:
            self._ipc.observe_property("media-title", 1)
            self._ipc.observe_property("metadata", 2)
            self._ipc.observe_property("pause", 3)
            self._ipc.observe_property("idle-active", 4)
            self._ipc.observe_property("duration", 5)
            self._ipc.observe_property("path", 6)
        except Exception as exc:
            logger.warning("Failed to observe mpv properties: {}", exc)

        self._connected = True
        self._fire_connection_change(True, "connected")
        logger.info("MpvBackend started")
        return True

    def stop(self) -> None:
        """Disconnect IPC and kill mpv."""
        self._connected = False
        self._clear_track_cache()
        self._ipc.disconnect()
        self._process.kill()
        self._fire_connection_change(False, "stopped")

    @property
    def is_connected(self) -> bool:
        return self._connected and self._process.is_alive() and self._ipc.connected

    def play(self) -> bool:
        return self._set_property("pause", False)

    def pause(self) -> bool:
        return self._set_property("pause", True)

    def stop_playback(self) -> bool:
        return self._command(["stop"])

    def next_track(self) -> bool:
        return self._command(["playlist-next"])

    def previous_track(self) -> bool:
        return self._command(["playlist-prev"])

    def set_volume(self, volume: int) -> bool:
        return self._set_property("volume", max(0, min(100, volume)))

    def get_volume(self) -> int | None:
        volume = self._get_property("volume")
        return int(volume) if volume is not None else None

    def set_audio_device(self, device: str) -> bool:
        return self._set_property("audio-device", device)

    def get_current_track(self) -> Track | None:
        if self._current_track is None and self.is_connected:
            self._refresh_current_track_snapshot()
        return self._current_track

    def get_playback_state(self) -> str:
        return self._playback_state

    def get_time_position(self) -> int:
        pos = self._get_property("time-pos")
        if pos is not None:
            return int(float(pos) * 1000)
        return 0

    def load_tracks(self, uris: list[str]) -> bool:
        if not uris:
            return False
        try:
            if not self._command(["loadfile", uris[0], "replace"]):
                return False
            for uri in uris[1:]:
                if not self._command(["loadfile", uri, "append"]):
                    return False
            return True
        except Exception as exc:
            logger.error("Failed to load tracks: {}", exc)
            return False

    def load_playlist_file(self, path: str) -> bool:
        return self._command(["loadlist", path, "replace"])

    def on_track_change(self, callback: Callable[[Track | None], None]) -> None:
        self._track_change_callbacks.append(callback)

    def on_playback_state_change(self, callback: Callable[[str], None]) -> None:
        self._playback_state_callbacks.append(callback)

    def on_connection_change(self, callback: Callable[[bool, str], None]) -> None:
        self._connection_change_callbacks.append(callback)

    def _command(self, args: list[object]) -> bool:
        try:
            result = self._ipc.send_command(args)
            return result.get("error") == "success"
        except Exception as exc:
            logger.error("mpv command {} failed: {}", args, exc)
            self._check_connection()
            return False

    def _set_property(self, name: str, value: object) -> bool:
        return self._command(["set_property", name, value])

    def _get_property(self, name: str) -> object | None:
        try:
            result = self._ipc.send_command(["get_property", name])
            if result.get("error") == "success":
                return result.get("data")
        except Exception:
            pass
        return None

    def _handle_mpv_event(self, event: dict[str, object]) -> None:
        event_name = event.get("event", "")

        if event_name == "file-loaded":
            self._sync_track_from_cache()
            self._update_playback_state("playing")
        elif event_name in ("pause", "unpause"):
            paused = event_name == "pause"
            self._update_playback_state("paused" if paused else "playing")
        elif event_name == "end-file":
            reason = event.get("reason", "")
            if reason == "eof":
                pass
            else:
                self._update_playback_state("stopped")
                self._update_track(None)
        elif event_name == "property-change":
            prop_name = event.get("name", "")
            if prop_name == "path":
                path = event.get("data")
                self._cached_path = str(path) if path else None
                self._sync_track_from_cache()
            elif prop_name == "metadata":
                metadata = event.get("data")
                self._cached_metadata = metadata if isinstance(metadata, dict) else {}
                self._sync_track_from_cache()
            elif prop_name == "duration":
                self._cached_duration = event.get("data")
                self._sync_track_from_cache()
            elif prop_name == "media-title":
                media_title = event.get("data")
                self._cached_media_title = str(media_title) if media_title else None
                self._sync_track_from_cache()
            elif prop_name == "pause":
                paused = event.get("data", False)
                self._update_playback_state("paused" if paused else "playing")
            elif prop_name == "idle-active":
                if event.get("data"):
                    self._update_playback_state("stopped")
                    self._clear_track_cache()
                    self._update_track(None)

    def _refresh_current_track_snapshot(self) -> None:
        """Query mpv for track properties from a non-reader thread."""
        path = self._get_property("path")
        metadata = self._get_property("metadata") or {}
        duration = self._get_property("duration")
        media_title = self._get_property("media-title")

        self._cached_path = str(path) if path else None
        self._cached_metadata = metadata if isinstance(metadata, dict) else {}
        self._cached_duration = duration
        self._cached_media_title = str(media_title) if media_title else None
        self._sync_track_from_cache()

    def _sync_track_from_cache(self) -> None:
        """Build the current track from the latest observed mpv properties."""
        if not self._cached_path:
            return

        metadata = dict(self._cached_metadata)
        if self._cached_duration is not None:
            metadata["duration"] = self._cached_duration
        if self._cached_media_title and not metadata.get("title"):
            metadata["title"] = self._cached_media_title

        track = Track.from_mpv_metadata(self._cached_path, metadata)
        self._update_track(track)

    def _clear_track_cache(self) -> None:
        """Clear cached track properties after stop/end-of-playback."""
        self._cached_path = None
        self._cached_metadata = {}
        self._cached_duration = None
        self._cached_media_title = None

    def _update_track(self, track: Track | None) -> None:
        if track != self._current_track:
            self._current_track = track
            for cb in self._track_change_callbacks:
                try:
                    cb(track)
                except Exception as exc:
                    logger.error("Track change callback error: {}", exc)

    def _update_playback_state(self, state: str) -> None:
        if state != self._playback_state:
            self._playback_state = state
            for cb in self._playback_state_callbacks:
                try:
                    cb(state)
                except Exception as exc:
                    logger.error("Playback state callback error: {}", exc)

    def _fire_connection_change(self, connected: bool, reason: str) -> None:
        for cb in self._connection_change_callbacks:
            try:
                cb(connected, reason)
            except Exception as exc:
                logger.error("Connection change callback error: {}", exc)

    def _check_connection(self) -> None:
        if not self._process.is_alive() or not self._ipc.connected:
            if self._connected:
                self._connected = False
                self._fire_connection_change(False, "connection_lost")


class MockMusicBackend:
    """In-memory music backend for unit tests."""

    def __init__(self) -> None:
        self._connected = False
        self._playback_state = "stopped"
        self._volume = 70
        self.current_track: Track | None = None
        self.time_position = 0
        self.commands: list[str] = []
        self._track_change_callbacks: list[Callable[[Track | None], None]] = []
        self._playback_state_callbacks: list[Callable[[str], None]] = []
        self._connection_change_callbacks: list[Callable[[bool, str], None]] = []

    def start(self) -> bool:
        self._connected = True
        return True

    def stop(self) -> None:
        self._connected = False
        self._playback_state = "stopped"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def play(self) -> bool:
        self._playback_state = "playing"
        self.commands.append("play")
        return True

    def pause(self) -> bool:
        self._playback_state = "paused"
        self.commands.append("pause")
        return True

    def stop_playback(self) -> bool:
        self._playback_state = "stopped"
        self.commands.append("stop")
        return True

    def next_track(self) -> bool:
        self.commands.append("next")
        return True

    def previous_track(self) -> bool:
        self.commands.append("previous")
        return True

    def set_volume(self, volume: int) -> bool:
        self._volume = volume
        self.commands.append(f"volume:{volume}")
        return True

    def get_volume(self) -> int | None:
        return self._volume

    def set_audio_device(self, device: str) -> bool:
        self.commands.append(f"audio-device:{device}")
        return True

    def get_current_track(self) -> Track | None:
        return self.current_track

    def get_playback_state(self) -> str:
        return self._playback_state

    def get_time_position(self) -> int:
        return self.time_position

    def load_tracks(self, uris: list[str]) -> bool:
        self.commands.append(f"load_tracks:{len(uris)}")
        return True

    def load_playlist_file(self, path: str) -> bool:
        self.commands.append(f"load_playlist:{path}")
        return True

    def on_track_change(self, callback: Callable[[Track | None], None]) -> None:
        self._track_change_callbacks.append(callback)

    def on_playback_state_change(self, callback: Callable[[str], None]) -> None:
        self._playback_state_callbacks.append(callback)

    def on_connection_change(self, callback: Callable[[bool, str], None]) -> None:
        self._connection_change_callbacks.append(callback)

    def emit_track_change(self, track: Track | None) -> None:
        for cb in self._track_change_callbacks:
            cb(track)

    def emit_playback_state_change(self, state: str) -> None:
        for cb in self._playback_state_callbacks:
            cb(state)

    def emit_connection_change(self, connected: bool, reason: str) -> None:
        for cb in self._connection_change_callbacks:
            cb(connected, reason)
