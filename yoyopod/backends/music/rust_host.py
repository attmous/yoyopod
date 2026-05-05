"""MusicBackend adapter backed by the Rust media host worker."""

from __future__ import annotations

import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from loguru import logger

from yoyopod.backends.music.models import MusicConfig, Playlist, Track
from yoyopod.core.workers import WorkerProcessConfig

_STARTUP_COMMANDS = frozenset({"media.configure", "media.start"})


@dataclass(frozen=True, slots=True)
class PreparedRemoteAsset:
    path: str
    cache_hit: bool


@dataclass(slots=True)
class _PendingWorkerRequest:
    request_id: str
    expected_type: str
    timeout_seconds: float
    send_lock: threading.Lock = field(default_factory=threading.Lock)
    event: threading.Event = field(default_factory=threading.Event)
    result: dict[str, Any] | None = None
    error: BaseException | None = None


class RustHostBackend:
    """Music backend facade backed by the Rust media host worker."""

    owns_library_state = True

    def __init__(
        self,
        config: MusicConfig,
        *,
        worker_supervisor: Any,
        worker_path: str,
        scheduler: Any | None = None,
        domain: str = "media",
        env: dict[str, str] | None = None,
        cwd: str | None = None,
    ) -> None:
        self.config = config
        self.worker_supervisor = worker_supervisor
        self.worker_path = worker_path
        self.scheduler = scheduler
        self.domain = domain
        self.env = env
        self.cwd = cwd
        self.running = False
        self._connected = False
        self._starting = False
        self._start_lock = threading.Lock()
        self._warm_start_thread: threading.Thread | None = None
        self._warm_start_pending = False
        self._registered_with_supervisor = False
        self._request_counter = 0
        self._pending_commands: dict[str, str] = {}
        self._pending_requests: dict[str, _PendingWorkerRequest] = {}
        self._request_lock = threading.Lock()
        self._startup_commands_sent = False
        self._ready_seen = False
        self._reconfigure_on_ready = False
        self._stopping = False
        self._current_track: Track | None = None
        self._playback_state = "stopped"
        self._time_position_ms = 0
        self._volume_percent = 100
        self._library_state_ready = False
        self._playlists: list[Playlist] = []
        self._recent_tracks: list[Any] = []
        self._menu_items: list[Any] = []
        self._track_change_callbacks: list[Callable[[Track | None], None]] = []
        self._playback_state_callbacks: list[Callable[[str], None]] = []
        self._connection_change_callbacks: list[Callable[[bool, str], None]] = []

    def start(self) -> bool:
        if self.running:
            return True

        register = getattr(self.worker_supervisor, "register", None)
        start = getattr(self.worker_supervisor, "start", None)
        if not callable(register) or not callable(start):
            logger.error("Rust media host supervisor is unavailable")
            return False

        with self._start_lock:
            if self.running:
                return True
            self._starting = True
            try:
                if not self._registered_with_supervisor:
                    register(
                        self.domain,
                        WorkerProcessConfig(
                            name=self.domain,
                            argv=[self.worker_path],
                            cwd=self.cwd,
                            env=self._process_env(),
                        ),
                    )
                    self._registered_with_supervisor = True
                if not bool(start(self.domain)):
                    return False
                if not self._send_startup_commands():
                    self._stop_after_startup_command_failure(
                        "startup_command_failed",
                        notify_connection_change=False,
                    )
                    return False
            except Exception as exc:
                logger.error("Rust media host start failed: {}", exc)
                self.running = False
                return False
            finally:
                self._starting = False

        self.running = True
        return True

    def warm_start(self) -> None:
        if self.running or self.startup_in_progress:
            return

        scheduler = self.scheduler
        post = getattr(scheduler, "post", None)
        if callable(post):
            with self._start_lock:
                if self.running or self._starting or self._warm_start_pending:
                    return
                self._warm_start_pending = True
            post(self._run_warm_start_on_main)
            return

        existing = self._warm_start_thread
        if existing is not None and existing.is_alive():
            return

        def _run() -> None:
            try:
                self.start()
            finally:
                self._warm_start_thread = None

        thread = threading.Thread(target=_run, daemon=True, name="rust-media-host-warm-start")
        self._warm_start_thread = thread
        thread.start()

    def stop(self) -> None:
        if not (self.running or self._registered_with_supervisor):
            return

        self._stopping = True
        try:
            if self._registered_with_supervisor:
                self._send("media.shutdown", {})
                stop = getattr(self.worker_supervisor, "stop", None)
                if callable(stop):
                    stop(self.domain, grace_seconds=1.0)
        finally:
            self._pending_commands.clear()
            self._startup_commands_sent = False
            self._ready_seen = False
            self._reconfigure_on_ready = False
            self._starting = False
            self.running = False
            self._warm_start_pending = False
            self._stopping = False
            self._mark_connection(False, "stopped")
            self._current_track = None
            self._playback_state = "stopped"
            self._time_position_ms = 0
            self._library_state_ready = False

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def startup_in_progress(self) -> bool:
        thread = self._warm_start_thread
        return self._starting or self._warm_start_pending or (
            thread is not None and thread.is_alive()
        )

    @property
    def library_state_ready(self) -> bool:
        return self._library_state_ready

    def play(self) -> bool:
        return self._send("media.play", {})

    def pause(self) -> bool:
        return self._send("media.pause", {})

    def stop_playback(self) -> bool:
        return self._send("media.stop_playback", {})

    def next_track(self) -> bool:
        return self._send("media.next_track", {})

    def previous_track(self) -> bool:
        return self._send("media.previous_track", {})

    def set_volume(self, volume: int) -> bool:
        normalized = max(0, min(100, int(volume)))
        if self._send("media.set_volume", {"volume": normalized}):
            self._volume_percent = normalized
            return True
        return False

    def get_volume(self) -> int | None:
        return self._volume_percent

    def set_audio_device(self, device: str) -> bool:
        return self._send("media.set_audio_device", {"device": device})

    def get_current_track(self) -> Track | None:
        return self._current_track

    def get_playback_state(self) -> str:
        return self._playback_state

    def get_time_position(self) -> int:
        return self._time_position_ms

    def load_tracks(self, uris: list[str]) -> bool:
        if not uris:
            return False
        return self._send("media.load_tracks", {"uris": list(uris)})

    def load_playlist_file(self, path: str) -> bool:
        return self._send("media.load_playlist", {"path": path})

    def shuffle_all(self) -> bool:
        return self._send("media.shuffle_all", {})

    def play_recent_track(self, track_uri: str) -> bool:
        return self._send("media.play_recent_track", {"track_uri": track_uri})

    def list_playlists(self, fetch_track_counts: bool = False) -> list[Playlist]:
        del fetch_track_counts
        return list(self._playlists)

    def playlist_count(self) -> int:
        return len(self._playlists)

    def list_recent_tracks(self, limit: int | None = None) -> list[Any]:
        entries = list(self._recent_tracks)
        if limit is None:
            return entries
        return entries[: max(0, int(limit))]

    def menu_items(self) -> list[Any]:
        return list(self._menu_items)

    def prepare_remote_playback_asset(
        self,
        *,
        track_id: str,
        media_url: str,
        checksum_sha256: str | None = None,
        extension: str = ".mp3",
        timeout_seconds: float | None = None,
    ) -> PreparedRemoteAsset:
        payload = self._request_result(
            "media.prepare_remote_asset",
            {
                "track_id": track_id,
                "media_url": media_url,
                "checksum_sha256": checksum_sha256,
                "extension": extension,
            },
            timeout_seconds=timeout_seconds,
        )
        return PreparedRemoteAsset(
            path=str(payload.get("path", "") or ""),
            cache_hit=bool(payload.get("cache_hit", False)),
        )

    def import_remote_media_asset(
        self,
        *,
        track_id: str,
        cached_path: str,
        title: str | None = None,
        filename: str | None = None,
        timeout_seconds: float | None = None,
    ) -> str:
        payload = self._request_result(
            "media.import_remote_asset",
            {
                "track_id": track_id,
                "cached_path": cached_path,
                "title": title,
                "filename": filename,
            },
            timeout_seconds=timeout_seconds,
        )
        return str(payload.get("path", "") or "")

    def on_track_change(self, callback: Callable[[Track | None], None]) -> None:
        self._track_change_callbacks.append(callback)

    def on_playback_state_change(self, callback: Callable[[str], None]) -> None:
        self._playback_state_callbacks.append(callback)

    def on_connection_change(self, callback: Callable[[bool, str], None]) -> None:
        self._connection_change_callbacks.append(callback)

    def handle_worker_message(self, event: Any) -> None:
        if getattr(event, "domain", self.domain) != self.domain:
            return

        payload = getattr(event, "payload", {}) or {}
        request_id = getattr(event, "request_id", None)
        kind = getattr(event, "kind", "event")
        event_type = getattr(event, "type", "")
        if kind == "result":
            if self._complete_pending_request_result(
                request_id=request_id,
                event_type=event_type,
                payload=payload,
            ):
                return
            self._pending_commands.pop(request_id, None)
            return
        if kind == "error":
            if self._complete_pending_request_error(
                request_id=request_id,
                payload=payload,
            ):
                return
            self._handle_worker_error(payload, request_id=request_id)
            return
        if kind != "event":
            return
        if event_type == "media.ready":
            self._handle_worker_ready()
            return
        if event_type == "media.snapshot":
            self._apply_snapshot(payload)

    def handle_worker_state_change(self, event: Any) -> None:
        if getattr(event, "domain", self.domain) != self.domain:
            return

        state = str(getattr(event, "state", "") or "")
        reason = str(getattr(event, "reason", "") or state)
        if state == "running":
            if self._ready_seen:
                self._reconfigure_on_ready = True
            return
        if state in {"degraded", "disabled", "stopped"}:
            self._reconfigure_on_ready = not self._stopping and state != "stopped"
            if self._stopping:
                self.running = False
                return
            self.running = False
            self._mark_connection(False, reason)

    def _send(self, message_type: str, payload: dict[str, Any]) -> bool:
        return self._send_with_request_id(message_type, payload) is not None

    def _send_with_request_id(self, message_type: str, payload: dict[str, Any]) -> str | None:
        send_command = getattr(self.worker_supervisor, "send_command", None)
        if not callable(send_command):
            return None
        request_id = self._next_request_id(message_type)
        try:
            sent = bool(
                send_command(
                    self.domain,
                    type=message_type,
                    payload=payload,
                    request_id=request_id,
                )
            )
        except Exception as exc:
            logger.error("Rust media host command {} failed: {}", message_type, exc)
            return None
        if sent:
            self._pending_commands[request_id] = message_type
            return request_id
        return None

    def _request_result(
        self,
        message_type: str,
        payload: dict[str, Any],
        *,
        timeout_seconds: float | None,
    ) -> dict[str, Any]:
        scheduler = self.scheduler
        send_request = getattr(self.worker_supervisor, "send_request", None)
        if scheduler is None or not callable(getattr(scheduler, "run_on_main", None)):
            raise RuntimeError("Rust media host scheduler is unavailable for blocking requests")
        if not callable(send_request):
            raise RuntimeError("Rust media host supervisor cannot send tracked requests")

        main_thread_id = getattr(scheduler, "main_thread_id", None)
        if main_thread_id is not None and threading.get_ident() == main_thread_id:
            raise RuntimeError("Rust media host blocking requests cannot run on the main thread")

        normalized_timeout = 30.0 if timeout_seconds is None else max(0.1, float(timeout_seconds))
        request_id = self._next_request_id(message_type)
        pending = _PendingWorkerRequest(
            request_id=request_id,
            expected_type=message_type,
            timeout_seconds=normalized_timeout,
        )
        with self._request_lock:
            self._pending_requests[request_id] = pending

        def _send_on_main() -> None:
            with pending.send_lock:
                with self._request_lock:
                    if self._pending_requests.get(request_id) is not pending:
                        return
                try:
                    sent = bool(
                        send_request(
                            self.domain,
                            type=message_type,
                            payload=payload,
                            request_id=request_id,
                            timeout_seconds=normalized_timeout,
                        )
                    )
                except Exception as exc:
                    self._complete_pending_request_once(
                        pending,
                        error=RuntimeError(str(exc) or "media worker unavailable"),
                    )
                    return
                if not sent:
                    self._complete_pending_request_once(
                        pending,
                        error=RuntimeError("media worker unavailable"),
                    )

        scheduler.run_on_main(_send_on_main)
        completed = pending.event.wait(normalized_timeout + 0.05)
        with pending.send_lock:
            with self._request_lock:
                self._pending_requests.pop(request_id, None)
        if not completed:
            raise TimeoutError(f"media worker request {request_id} timed out")
        if pending.error is not None:
            raise pending.error
        return pending.result or {}

    def _config_payload(self) -> dict[str, Any]:
        payload = asdict(self.config)
        payload["music_dir"] = str(self.config.music_dir)
        return payload

    def _process_env(self) -> dict[str, str] | None:
        if self.env is None:
            return None
        merged = dict(os.environ)
        merged.update(self.env)
        return merged

    def _send_startup_commands(self) -> bool:
        if not self._send("media.configure", self._config_payload()):
            return False
        if not self._send("media.start", {}):
            return False
        self._startup_commands_sent = True
        return True

    def _handle_worker_ready(self) -> None:
        if self._reconfigure_on_ready or not self._startup_commands_sent:
            if not self._send_startup_commands():
                self._stop_after_startup_command_failure("worker_ready_reconfigure_failed")
                return
            self.running = True
        self._ready_seen = True
        self._reconfigure_on_ready = False

    def _handle_worker_error(self, payload: dict[str, Any], *, request_id: str | None) -> None:
        command = self._pending_commands.pop(request_id, None) if request_id is not None else None
        reason = _worker_error_reason(payload, command=command)
        if command in _STARTUP_COMMANDS or command is None:
            self._stop_after_startup_command_failure(reason)
            return
        logger.warning("Rust media host command failed: {}", reason)

    def _stop_after_startup_command_failure(
        self,
        reason: str,
        *,
        notify_connection_change: bool = True,
    ) -> None:
        stop = getattr(self.worker_supervisor, "stop", None)
        if self._registered_with_supervisor and callable(stop):
            was_stopping = self._stopping
            self._stopping = True
            try:
                stop(self.domain, grace_seconds=1.0)
            except Exception as exc:
                logger.warning(
                    "Rust media host failed to stop worker after startup command failure {}: {}",
                    reason,
                    exc,
                )
            finally:
                self._stopping = was_stopping
        self._pending_commands.clear()
        with self._request_lock:
            pending_requests = list(self._pending_requests.values())
            self._pending_requests.clear()
        self._startup_commands_sent = False
        self._ready_seen = False
        self._reconfigure_on_ready = False
        self._starting = False
        self._warm_start_pending = False
        self.running = False
        self._library_state_ready = False
        for pending in pending_requests:
            self._complete_pending_request_once(
                pending,
                error=RuntimeError(reason),
            )
        if notify_connection_change:
            self._mark_connection(False, reason)

    def _apply_snapshot(self, payload: dict[str, Any]) -> None:
        next_track = _track_from_payload(payload.get("current_track"))
        next_state = _playback_state_from_payload(payload.get("playback_state"))
        next_connected = bool(payload.get("connected", False))
        next_reason = str(payload.get("backend_state", "") or "snapshot")
        next_time_position_ms = _int_payload(payload.get("time_position_ms"))
        next_volume = _int_payload(payload.get("volume_percent"))
        if next_volume == 0 and "volume_percent" not in payload:
            next_volume = _int_payload(payload.get("default_volume"))
        next_playlists = _playlists_from_payload(payload.get("playlists"))
        next_recent_tracks = _recent_tracks_from_payload(payload.get("recent_tracks"))
        next_menu_items = _menu_items_from_payload(payload.get("library_menu"))

        if next_connected != self._connected:
            self._mark_connection(next_connected, next_reason)
        self._time_position_ms = next_time_position_ms
        if next_volume >= 0:
            self._volume_percent = next_volume
        self._library_state_ready = True
        self._playlists = next_playlists
        self._recent_tracks = next_recent_tracks
        self._menu_items = next_menu_items

        if next_track != self._current_track:
            self._current_track = next_track
            for callback in list(self._track_change_callbacks):
                callback(next_track)

        if next_state != self._playback_state:
            self._playback_state = next_state
            for callback in list(self._playback_state_callbacks):
                callback(next_state)

    def _mark_connection(self, connected: bool, reason: str) -> None:
        if self._connected == connected:
            return
        self._connected = connected
        for callback in list(self._connection_change_callbacks):
            callback(connected, reason)

    def _next_request_id(self, message_type: str) -> str:
        self._request_counter += 1
        command_name = message_type.replace(".", "_")
        return f"{self.domain}-{command_name}-{self._request_counter}"

    def _complete_pending_request_result(
        self,
        *,
        request_id: str | None,
        event_type: str,
        payload: dict[str, Any],
    ) -> bool:
        if request_id is None:
            return False
        with self._request_lock:
            pending = self._pending_requests.get(request_id)
        if pending is None or pending.expected_type != event_type:
            return False
        self._complete_pending_request_once(pending, result=payload)
        return True

    def _complete_pending_request_error(
        self,
        *,
        request_id: str | None,
        payload: dict[str, Any],
    ) -> bool:
        if request_id is None:
            return False
        with self._request_lock:
            pending = self._pending_requests.get(request_id)
        if pending is None:
            return False
        self._complete_pending_request_once(
            pending,
            error=RuntimeError(_worker_error_reason(payload, command=pending.expected_type)),
        )
        return True

    def _complete_pending_request_once(
        self,
        pending: _PendingWorkerRequest,
        *,
        result: dict[str, Any] | None = None,
        error: BaseException | None = None,
    ) -> None:
        if pending.event.is_set():
            return
        pending.result = result
        pending.error = error
        pending.event.set()

    def _run_warm_start_on_main(self) -> None:
        try:
            if not self._warm_start_pending:
                return
            self.start()
        finally:
            self._warm_start_pending = False


def _track_from_payload(value: object) -> Track | None:
    if not isinstance(value, dict):
        return None
    uri = str(value.get("uri", "") or "").strip()
    if not uri:
        return None
    artists = value.get("artists", [])
    if not isinstance(artists, list):
        artists = []
    return Track(
        uri=uri,
        name=str(value.get("name", "") or Path(uri).stem),
        artists=[str(artist) for artist in artists if str(artist)],
        album=str(value.get("album", "") or ""),
        length=_int_payload(value.get("length_ms")),
        track_no=_optional_int_payload(value.get("track_no")),
    )


def _playback_state_from_payload(value: object) -> str:
    normalized = str(value or "stopped").strip().lower()
    if normalized in {"playing", "paused"}:
        return normalized
    return "stopped"


def _playlists_from_payload(value: object) -> list[Playlist]:
    if not isinstance(value, list):
        return []
    playlists: list[Playlist] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri", "") or "").strip()
        if not uri:
            continue
        playlists.append(
            Playlist(
                uri=uri,
                name=str(item.get("name", "") or Path(uri).stem),
                track_count=_int_payload(item.get("track_count")),
            )
        )
    return playlists


def _recent_tracks_from_payload(value: object) -> list[Any]:
    if not isinstance(value, list):
        return []
    from yoyopod.integrations.music.history import RecentTrackEntry

    entries: list[RecentTrackEntry] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        uri = str(item.get("uri", "") or "").strip()
        if not uri:
            continue
        entries.append(
            RecentTrackEntry(
                uri=uri,
                title=str(item.get("title", "Unknown Track")),
                artist=str(item.get("artist", "Unknown Artist")),
                album=str(item.get("album", "") or ""),
                played_at=str(item.get("played_at", "") or ""),
            )
        )
    return entries


def _menu_items_from_payload(value: object) -> list[Any]:
    if not isinstance(value, list):
        return []
    from yoyopod.integrations.music.library import LocalLibraryItem

    items: list[LocalLibraryItem] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "") or "").strip()
        if not key:
            continue
        items.append(
            LocalLibraryItem(
                key=key,
                title=str(item.get("title", "") or key),
                subtitle=str(item.get("subtitle", "") or ""),
            )
        )
    return items


def _int_payload(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _optional_int_payload(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _worker_error_reason(payload: dict[str, Any], *, command: str | None) -> str:
    code = str(payload.get("code", "worker_error")).strip() or "worker_error"
    message = str(payload.get("message", "")).strip()
    prefix = f"{command} {code}" if command else code
    if message:
        return f"{prefix}: {message}"
    return prefix


def default_worker_path() -> str:
    """Return the default Rust media host worker binary path."""

    return os.environ.get(
        "YOYOPOD_RUST_MEDIA_HOST_WORKER",
        "yoyopod_rs/media/build/yoyopod-media-host",
    ).strip()


__all__ = ["PreparedRemoteAsset", "RustHostBackend", "default_worker_path"]
