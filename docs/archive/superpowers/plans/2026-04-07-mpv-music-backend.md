# mpv Music Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace Mopidy with an app-managed mpv process using a `MusicBackend` Protocol, saving ~50 MB RAM on Pi Zero 2W.

**Architecture:** Abstract `MusicBackend` protocol (mirroring `VoIPBackend`) with `MpvBackend` (separate process, JSON IPC over Unix socket) and `MockMusicBackend` for tests. Library/playlist scanning moves from Mopidy RPC to filesystem glob in `LocalMusicService`.

**Tech Stack:** mpv (C + ffmpeg), Unix sockets (AF_UNIX / named pipes on Windows), tinytag (pure Python tag reader), existing YoyoPod event bus and coordinator pattern.

**Spec:** `docs/archive/superpowers/specs/2026-04-07-mpv-music-backend-design.md`

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `yoyopy/audio/music/__init__.py` | Re-exports for music subpackage |
| Create | `yoyopy/audio/music/models.py` | `Track`, `Playlist`, `MusicConfig` dataclasses |
| Create | `yoyopy/audio/music/backend.py` | `MusicBackend` Protocol, `MpvBackend`, `MockMusicBackend` |
| Create | `yoyopy/audio/music/ipc.py` | `MpvIpcClient` — socket connect/send/receive/event reader thread |
| Create | `yoyopy/audio/music/process.py` | `MpvProcess` — spawn, is_alive, kill, respawn |
| Create | `tests/test_music_models.py` | Tests for `Track`, `Playlist` dataclasses |
| Create | `tests/test_mpv_ipc.py` | Tests for `MpvIpcClient` with a fake socket |
| Create | `tests/test_mpv_process.py` | Tests for `MpvProcess` spawn/kill lifecycle |
| Create | `tests/test_music_backend.py` | Tests for `MpvBackend` and `MockMusicBackend` |
| Modify | `yoyopy/audio/__init__.py` | Swap re-exports from Mopidy to music subpackage |
| Modify | `yoyopy/audio/history.py` | `MopidyTrack` → `Track` import |
| Modify | `yoyopy/audio/local_service.py` | `MopidyClient` → `MusicBackend`, add `music_dir`, filesystem scanning |
| Modify | `yoyopy/config/models.py:144-149` | Replace `mopidy_host`/`mopidy_port` with `music_dir`, `mpv_socket`, `mpv_binary`, `alsa_device` |
| Modify | `yoyopy/events.py:10,62,77-78,85,92` | `MopidyTrack` → `Track`, `"mopidy"` → `"music"` |
| Modify | `yoyopy/coordinators/runtime.py:23,86` | `mopidy_client` → `music_backend` |
| Modify | `yoyopy/coordinators/playback.py:10,47` | `MopidyTrack` → `Track` |
| Modify | `yoyopy/coordinators/call.py:183-192,247-248` | `mopidy_client` → `music_backend` |
| Modify | `yoyopy/coordinators/screen.py:42-43` | `mopidy_client` → `music_backend` |
| Modify | `yoyopy/ui/screens/navigation/hub.py:16,38,43` | `MopidyClient` → `MusicBackend` |
| Modify | `yoyopy/ui/screens/music/now_playing.py:24` | `mopidy_client` → `music_backend` |
| Modify | `yoyopy/app.py:20,128,490-504,535,556,756-767,859-867,998,1380-1419,1572-1575,1615,969` | Full Mopidy → mpv swap |
| Modify | `tests/test_local_music_service.py` | Update fakes and imports for `MusicBackend` + `Track` |
| Modify | `tests/test_app_orchestration.py` | `FakeMopidyClient` → `MockMusicBackend` |
| Modify | `tests/test_whisplay_one_button.py` | `FakeMopidyClient` → `MockMusicBackend` |
| Modify | `tests/test_now_playing_lvgl_view.py` | `FakeMopidyClient` → `MockMusicBackend` |
| Modify | `tests/test_playlist_lvgl_view.py` | `FakeMopidyClient` → `MockMusicBackend` |
| Modify | `tests/test_fsm_runtime.py:20` | `mopidy_client=None` → `music_backend=None` |
| Delete | `yoyopy/audio/mopidy_client.py` | Removed after all consumers migrated |
| Delete | `tests/test_mopidy_client.py` | Replaced by `tests/test_music_backend.py` |

---

## Task 1: Data Models (`models.py`)

**Files:**
- Create: `yoyopy/audio/music/__init__.py`
- Create: `yoyopy/audio/music/models.py`
- Create: `tests/test_music_models.py`

- [ ] **Step 1: Write failing tests for Track and Playlist**

```python
# tests/test_music_models.py
"""Tests for music data models."""

from __future__ import annotations

from pathlib import Path

from yoyopy.audio.music.models import Track, Playlist, MusicConfig


def test_track_get_artist_string_with_artists() -> None:
    track = Track(uri="/music/song.mp3", name="Song", artists=["Alice", "Bob"])
    assert track.get_artist_string() == "Alice, Bob"


def test_track_get_artist_string_empty() -> None:
    track = Track(uri="/music/song.mp3", name="Song", artists=[])
    assert track.get_artist_string() == "Unknown Artist"


def test_track_from_mpv_metadata_basic() -> None:
    track = Track.from_mpv_metadata(
        "/music/song.mp3",
        {"title": "My Song", "artist": "Alice", "album": "Debut", "duration": 180.5},
    )
    assert track.name == "My Song"
    assert track.artists == ["Alice"]
    assert track.album == "Debut"
    assert track.length == 180500
    assert track.uri == "/music/song.mp3"


def test_track_from_mpv_metadata_missing_fields() -> None:
    track = Track.from_mpv_metadata("/music/unknown.mp3", {})
    assert track.name == "unknown"
    assert track.artists == ["Unknown"]
    assert track.album == ""
    assert track.length == 0


def test_track_from_file_tags(tmp_path: Path) -> None:
    # Create a minimal test — from_file_tags falls back to filename when tinytag fails
    fake_file = tmp_path / "test_song.mp3"
    fake_file.write_bytes(b"\x00" * 100)
    track = Track.from_file_tags(fake_file)
    assert track.uri == str(fake_file)
    assert track.name == "test_song"


def test_playlist_dataclass() -> None:
    pl = Playlist(uri="/music/chill.m3u", name="chill", track_count=5)
    assert pl.name == "chill"
    assert pl.track_count == 5


def test_music_config_defaults() -> None:
    cfg = MusicConfig(music_dir=Path("/home/pi/Music"))
    assert cfg.mpv_socket == "/tmp/yoyopod-mpv.sock"
    assert cfg.mpv_binary == "mpv"
    assert cfg.alsa_device == "default"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_music_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yoyopy.audio.music'`

- [ ] **Step 3: Create the music subpackage and models**

```python
# yoyopy/audio/music/__init__.py
"""Music backend subpackage for YoyoPod."""

from yoyopy.audio.music.models import MusicConfig, Playlist, Track

__all__ = ["MusicConfig", "Playlist", "Track"]
```

```python
# yoyopy/audio/music/models.py
"""Data models for the music backend."""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Track:
    """One music track. Replaces MopidyTrack."""

    uri: str
    name: str
    artists: list[str]
    album: str = ""
    length: int = 0  # milliseconds
    track_no: int | None = None

    def get_artist_string(self) -> str:
        """Get comma-separated artist names."""
        return ", ".join(self.artists) if self.artists else "Unknown Artist"

    @classmethod
    def from_mpv_metadata(cls, path: str, metadata: dict) -> Track:
        """Build from mpv's 'metadata' property dict at runtime."""
        raw_duration = metadata.get("duration", 0)
        duration_ms = int(float(raw_duration) * 1000) if raw_duration else 0
        name = metadata.get("title") or Path(path).stem
        artist = metadata.get("artist") or "Unknown"
        album = metadata.get("album", "")
        track_no_raw = metadata.get("track")
        track_no = int(track_no_raw) if track_no_raw is not None else None
        return cls(
            uri=path,
            name=name,
            artists=[artist] if isinstance(artist, str) else list(artist),
            album=album,
            length=duration_ms,
            track_no=track_no,
        )

    @classmethod
    def from_file_tags(cls, path: Path) -> Track:
        """Build from file metadata tags using tinytag. Falls back to filename."""
        try:
            from tinytag import TinyTag

            tag = TinyTag.get(str(path))
            return cls(
                uri=str(path),
                name=tag.title or path.stem,
                artists=[tag.artist] if tag.artist else ["Unknown"],
                album=tag.album or "",
                length=int((tag.duration or 0) * 1000),
                track_no=int(tag.track) if tag.track is not None else None,
            )
        except Exception:
            return cls(
                uri=str(path),
                name=path.stem,
                artists=["Unknown"],
            )


@dataclass(frozen=True, slots=True)
class Playlist:
    """One M3U playlist. Replaces MopidyPlaylist."""

    uri: str
    name: str
    track_count: int = 0


def _default_mpv_socket() -> str:
    """Return the platform-appropriate default mpv IPC path."""
    if sys.platform == "win32":
        return r"\\.\pipe\yoyopod-mpv"
    return "/tmp/yoyopod-mpv.sock"


@dataclass(slots=True)
class MusicConfig:
    """Configuration for the mpv music backend."""

    music_dir: Path = Path("/home/pi/Music")
    mpv_socket: str = ""
    mpv_binary: str = "mpv"
    alsa_device: str = "default"

    def __post_init__(self) -> None:
        if not self.mpv_socket:
            self.mpv_socket = _default_mpv_socket()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_music_models.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add yoyopy/audio/music/__init__.py yoyopy/audio/music/models.py tests/test_music_models.py
git commit -m "feat(audio): add Track, Playlist, MusicConfig data models for mpv backend"
```

---

## Task 2: MpvProcess (`process.py`)

**Files:**
- Create: `yoyopy/audio/music/process.py`
- Create: `tests/test_mpv_process.py`

- [ ] **Step 1: Write failing tests for MpvProcess**

```python
# tests/test_mpv_process.py
"""Tests for mpv process lifecycle manager."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from yoyopy.audio.music.models import MusicConfig
from yoyopy.audio.music.process import MpvProcess


def _make_config(tmp_path: Path) -> MusicConfig:
    return MusicConfig(
        music_dir=tmp_path,
        mpv_socket=str(tmp_path / "mpv.sock"),
        mpv_binary="mpv",
        alsa_device="default",
    )


def test_spawn_builds_correct_command(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    proc = MpvProcess(config)
    with patch("yoyopy.audio.music.process.subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        assert proc.spawn() is True

        args = mock_popen.call_args[0][0]
        assert args[0] == "mpv"
        assert "--idle" in args
        assert "--no-video" in args
        assert f"--input-ipc-server={config.mpv_socket}" in args
        assert "--audio-device=alsa/default" in args


def test_is_alive_false_when_not_spawned(tmp_path: Path) -> None:
    proc = MpvProcess(_make_config(tmp_path))
    assert proc.is_alive() is False


def test_is_alive_true_when_running(tmp_path: Path) -> None:
    proc = MpvProcess(_make_config(tmp_path))
    with patch("yoyopy.audio.music.process.subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        proc.spawn()
        assert proc.is_alive() is True


def test_kill_terminates_and_cleans_socket(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    sock_path = Path(config.mpv_socket)
    sock_path.touch()
    proc = MpvProcess(config)
    with patch("yoyopy.audio.music.process.subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        proc.spawn()

        mock_process.poll.return_value = 0
        proc.kill()
        mock_process.terminate.assert_called_once()
        assert not sock_path.exists()


def test_respawn_kills_then_spawns(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    proc = MpvProcess(config)
    with patch("yoyopy.audio.music.process.subprocess.Popen") as mock_popen:
        mock_process = MagicMock()
        mock_process.poll.return_value = None
        mock_popen.return_value = mock_process
        proc.spawn()

        mock_process.poll.return_value = 0
        assert proc.respawn() is True
        assert mock_process.terminate.call_count == 1
        assert mock_popen.call_count == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mpv_process.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yoyopy.audio.music.process'`

- [ ] **Step 3: Implement MpvProcess**

```python
# yoyopy/audio/music/process.py
"""mpv process lifecycle manager."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from loguru import logger

from yoyopy.audio.music.models import MusicConfig


class MpvProcess:
    """Spawn, monitor, and kill an mpv process for music playback."""

    def __init__(self, config: MusicConfig) -> None:
        self.config = config
        self._process: subprocess.Popen | None = None

    def spawn(self) -> bool:
        """Launch mpv in idle mode with IPC socket."""
        if self._process is not None and self._process.poll() is None:
            logger.warning("mpv process already running (pid={})", self._process.pid)
            return True

        self._clean_stale_socket()

        cmd = [
            self.config.mpv_binary,
            "--idle",
            "--no-video",
            f"--input-ipc-server={self.config.mpv_socket}",
            f"--audio-device=alsa/{self.config.alsa_device}",
        ]

        try:
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            logger.info("mpv spawned (pid={}, socket={})", self._process.pid, self.config.mpv_socket)
            return True
        except FileNotFoundError:
            logger.error("mpv binary not found at '{}'", self.config.mpv_binary)
            return False
        except Exception as exc:
            logger.error("Failed to spawn mpv: {}", exc)
            return False

    def is_alive(self) -> bool:
        """Return True when the mpv process is running."""
        return self._process is not None and self._process.poll() is None

    def kill(self) -> None:
        """Terminate the mpv process and clean up the socket file."""
        if self._process is None:
            return

        try:
            self._process.terminate()
            self._process.wait(timeout=2.0)
        except subprocess.TimeoutExpired:
            logger.warning("mpv did not exit after SIGTERM, sending SIGKILL")
            self._process.kill()
            self._process.wait(timeout=2.0)
        except Exception as exc:
            logger.error("Error killing mpv: {}", exc)
        finally:
            self._process = None
            self._clean_stale_socket()

    def respawn(self) -> bool:
        """Kill the current process and spawn a fresh one."""
        self.kill()
        return self.spawn()

    def _clean_stale_socket(self) -> None:
        """Remove a leftover socket file if present (Unix only)."""
        if sys.platform == "win32":
            return
        sock = Path(self.config.mpv_socket)
        if sock.exists():
            try:
                sock.unlink()
            except OSError:
                pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mpv_process.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add yoyopy/audio/music/process.py tests/test_mpv_process.py
git commit -m "feat(audio): add MpvProcess for mpv lifecycle management"
```

---

## Task 3: MpvIpcClient (`ipc.py`)

**Files:**
- Create: `yoyopy/audio/music/ipc.py`
- Create: `tests/test_mpv_ipc.py`

- [ ] **Step 1: Write failing tests for MpvIpcClient**

```python
# tests/test_mpv_ipc.py
"""Tests for mpv JSON IPC client."""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

from yoyopy.audio.music.ipc import MpvIpcClient


def _make_socket_pair(tmp_path: Path) -> tuple[str, socket.socket]:
    """Create a Unix socket server for testing."""
    sock_path = str(tmp_path / "test-mpv.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(sock_path)
    server.listen(1)
    return sock_path, server


def test_connect_and_send_command(tmp_path: Path) -> None:
    sock_path, server = _make_socket_pair(tmp_path)

    def handle_client():
        conn, _ = server.accept()
        data = conn.recv(4096)
        request = json.loads(data.decode().strip())
        response = {"request_id": request["request_id"], "error": "success", "data": "0.38.0"}
        conn.sendall((json.dumps(response) + "\n").encode())
        conn.close()

    t = threading.Thread(target=handle_client, daemon=True)
    t.start()

    client = MpvIpcClient(sock_path)
    assert client.connect() is True
    result = client.send_command(["get_property", "mpv-version"])
    assert result["data"] == "0.38.0"
    client.disconnect()
    server.close()


def test_connect_fails_on_missing_socket(tmp_path: Path) -> None:
    client = MpvIpcClient(str(tmp_path / "nonexistent.sock"))
    assert client.connect() is False


def test_event_callback_fires(tmp_path: Path) -> None:
    sock_path, server = _make_socket_pair(tmp_path)
    events_received: list[dict] = []

    def handle_client():
        conn, _ = server.accept()
        event = {"event": "file-loaded"}
        conn.sendall((json.dumps(event) + "\n").encode())
        # Keep connection alive briefly so reader thread can process
        import time
        time.sleep(0.2)
        conn.close()

    t = threading.Thread(target=handle_client, daemon=True)
    t.start()

    client = MpvIpcClient(sock_path)
    client.on_event(events_received.append)
    client.connect()
    client.start_reader()

    import time
    time.sleep(0.3)

    client.disconnect()
    server.close()

    assert len(events_received) >= 1
    assert events_received[0]["event"] == "file-loaded"


def test_disconnect_is_safe_when_not_connected(tmp_path: Path) -> None:
    client = MpvIpcClient(str(tmp_path / "no.sock"))
    client.disconnect()  # Should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mpv_ipc.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yoyopy.audio.music.ipc'`

- [ ] **Step 3: Implement MpvIpcClient**

```python
# yoyopy/audio/music/ipc.py
"""mpv JSON IPC client over Unix socket."""

from __future__ import annotations

import json
import socket
import sys
import threading
from typing import Any, Callable

from loguru import logger


class MpvIpcClient:
    """Low-level client for mpv's JSON IPC protocol."""

    def __init__(self, socket_path: str) -> None:
        self.socket_path = socket_path
        self._sock: socket.socket | None = None
        self._lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._reader_stop = threading.Event()
        self._request_id = 0
        self._pending: dict[int, threading.Event] = {}
        self._responses: dict[int, dict] = {}
        self._event_callbacks: list[Callable[[dict], None]] = []

    def connect(self) -> bool:
        """Connect to the mpv IPC socket."""
        try:
            if sys.platform == "win32":
                # Windows named pipe — open as a file
                self._sock = open(self.socket_path, "r+b", buffering=0)  # type: ignore[assignment]
                logger.info("Connected to mpv named pipe: {}", self.socket_path)
                return True

            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(self.socket_path)
            sock.settimeout(5.0)
            self._sock = sock
            logger.info("Connected to mpv IPC: {}", self.socket_path)
            return True
        except Exception as exc:
            logger.error("Failed to connect to mpv IPC at {}: {}", self.socket_path, exc)
            self._sock = None
            return False

    def disconnect(self) -> None:
        """Close the socket and stop the reader thread."""
        self._reader_stop.set()
        if self._reader_thread is not None:
            self._reader_thread.join(timeout=2.0)
            self._reader_thread = None

        if self._sock is not None:
            try:
                self._sock.close()
            except Exception:
                pass
            self._sock = None

    @property
    def connected(self) -> bool:
        """Return True when the socket is open."""
        return self._sock is not None

    def send_command(self, args: list, timeout: float = 5.0) -> dict:
        """Send a command and wait for the response."""
        with self._lock:
            self._request_id += 1
            req_id = self._request_id

        ready = threading.Event()
        self._pending[req_id] = ready

        payload = json.dumps({"command": args, "request_id": req_id}) + "\n"
        try:
            self._sock.sendall(payload.encode())  # type: ignore[union-attr]
        except Exception as exc:
            self._pending.pop(req_id, None)
            raise ConnectionError(f"Failed to send mpv command: {exc}") from exc

        if not ready.wait(timeout):
            self._pending.pop(req_id, None)
            raise TimeoutError(f"mpv command timed out: {args}")

        return self._responses.pop(req_id, {})

    def observe_property(self, name: str, observe_id: int | None = None) -> None:
        """Ask mpv to push property-change events for the named property."""
        oid = observe_id if observe_id is not None else hash(name) & 0x7FFFFFFF
        self.send_command(["observe_property", oid, name])

    def on_event(self, callback: Callable[[dict], None]) -> None:
        """Register a callback for mpv events."""
        self._event_callbacks.append(callback)

    def start_reader(self) -> None:
        """Start the background thread that reads responses and events."""
        if self._reader_thread is not None:
            return
        self._reader_stop.clear()
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="mpv-ipc-reader"
        )
        self._reader_thread.start()

    def _reader_loop(self) -> None:
        """Read newline-delimited JSON from the socket."""
        buffer = ""
        while not self._reader_stop.is_set():
            try:
                chunk = self._sock.recv(4096)  # type: ignore[union-attr]
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        msg = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if "request_id" in msg:
                        req_id = msg["request_id"]
                        self._responses[req_id] = msg
                        event = self._pending.pop(req_id, None)
                        if event is not None:
                            event.set()
                    elif "event" in msg:
                        for cb in self._event_callbacks:
                            try:
                                cb(msg)
                            except Exception as exc:
                                logger.error("mpv event callback error: {}", exc)
            except socket.timeout:
                continue
            except Exception:
                if not self._reader_stop.is_set():
                    logger.warning("mpv IPC reader disconnected")
                break
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mpv_ipc.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add yoyopy/audio/music/ipc.py tests/test_mpv_ipc.py
git commit -m "feat(audio): add MpvIpcClient for mpv JSON IPC protocol"
```

---

## Task 4: MusicBackend Protocol, MpvBackend, MockMusicBackend (`backend.py`)

**Files:**
- Create: `yoyopy/audio/music/backend.py`
- Create: `tests/test_music_backend.py`

- [ ] **Step 1: Write failing tests for MockMusicBackend and MusicBackend contract**

```python
# tests/test_music_backend.py
"""Tests for MusicBackend protocol and MockMusicBackend."""

from __future__ import annotations

from yoyopy.audio.music.backend import MockMusicBackend, MusicBackend
from yoyopy.audio.music.models import Track


def test_mock_backend_satisfies_protocol() -> None:
    backend: MusicBackend = MockMusicBackend()
    assert backend.start() is True
    assert backend.is_connected is True


def test_mock_backend_transport_controls() -> None:
    backend = MockMusicBackend()
    backend.start()
    assert backend.play() is True
    assert backend.pause() is True
    assert backend.stop_playback() is True
    assert backend.next_track() is True
    assert backend.previous_track() is True


def test_mock_backend_volume() -> None:
    backend = MockMusicBackend()
    backend.start()
    assert backend.set_volume(75) is True
    assert backend.get_volume() == 75


def test_mock_backend_audio_device() -> None:
    backend = MockMusicBackend()
    backend.start()
    assert backend.set_audio_device("alsa/hw:1,0") is True


def test_mock_backend_load_tracks() -> None:
    backend = MockMusicBackend()
    backend.start()
    assert backend.load_tracks(["/music/a.mp3", "/music/b.mp3"]) is True
    assert "load_tracks" in backend.commands[-1]


def test_mock_backend_load_playlist_file() -> None:
    backend = MockMusicBackend()
    backend.start()
    assert backend.load_playlist_file("/music/chill.m3u") is True


def test_mock_backend_playback_state() -> None:
    backend = MockMusicBackend()
    backend.start()
    assert backend.get_playback_state() == "stopped"
    backend.play()
    assert backend.get_playback_state() == "playing"
    backend.pause()
    assert backend.get_playback_state() == "paused"


def test_mock_backend_track_change_callback() -> None:
    backend = MockMusicBackend()
    received: list[Track | None] = []
    backend.on_track_change(received.append)
    track = Track(uri="/music/a.mp3", name="A", artists=["X"])
    backend.emit_track_change(track)
    assert received == [track]


def test_mock_backend_playback_state_callback() -> None:
    backend = MockMusicBackend()
    received: list[str] = []
    backend.on_playback_state_change(received.append)
    backend.emit_playback_state_change("playing")
    assert received == ["playing"]


def test_mock_backend_connection_callback() -> None:
    backend = MockMusicBackend()
    received: list[tuple[bool, str]] = []
    backend.on_connection_change(lambda ok, reason: received.append((ok, reason)))
    backend.emit_connection_change(True, "connected")
    assert received == [(True, "connected")]


def test_mock_backend_stop() -> None:
    backend = MockMusicBackend()
    backend.start()
    backend.stop()
    assert backend.is_connected is False


def test_mock_backend_get_current_track() -> None:
    backend = MockMusicBackend()
    assert backend.get_current_track() is None
    track = Track(uri="/music/a.mp3", name="A", artists=["X"])
    backend.current_track = track
    assert backend.get_current_track() == track


def test_mock_backend_get_time_position() -> None:
    backend = MockMusicBackend()
    assert backend.get_time_position() == 0
    backend.time_position = 5000
    assert backend.get_time_position() == 5000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_music_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'yoyopy.audio.music.backend'`

- [ ] **Step 3: Implement MusicBackend, MpvBackend, and MockMusicBackend**

```python
# yoyopy/audio/music/backend.py
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

    _STARTUP_CONNECT_RETRIES = 10
    _STARTUP_CONNECT_DELAY = 0.1

    def __init__(self, config: MusicConfig) -> None:
        self.config = config
        self._process = MpvProcess(config)
        self._ipc = MpvIpcClient(config.mpv_socket)
        self._connected = False
        self._current_track: Track | None = None
        self._playback_state: str = "stopped"

        self._track_change_callbacks: list[Callable[[Track | None], None]] = []
        self._playback_state_callbacks: list[Callable[[str], None]] = []
        self._connection_change_callbacks: list[Callable[[bool, str], None]] = []

    def start(self) -> bool:
        """Spawn mpv, connect IPC, subscribe to events."""
        if not self._process.spawn():
            return False

        # mpv needs a moment to create the socket after spawning
        for _ in range(self._STARTUP_CONNECT_RETRIES):
            if self._ipc.connect():
                break
            time.sleep(self._STARTUP_CONNECT_DELAY)
        else:
            logger.error("Failed to connect to mpv IPC after spawn")
            self._process.kill()
            return False

        self._ipc.on_event(self._handle_mpv_event)
        self._ipc.start_reader()

        # Subscribe to property changes for track metadata
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
        return self._get_property("volume")

    def set_audio_device(self, device: str) -> bool:
        return self._set_property("audio-device", device)

    def get_current_track(self) -> Track | None:
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
            self._command(["loadfile", uris[0], "replace"])
            for uri in uris[1:]:
                self._command(["loadfile", uri, "append"])
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

    def _command(self, args: list) -> bool:
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

    def _handle_mpv_event(self, event: dict) -> None:
        event_name = event.get("event", "")

        if event_name == "file-loaded":
            self._refresh_current_track()
            self._update_playback_state("playing")
        elif event_name in ("pause", "unpause"):
            paused = event_name == "pause"
            self._update_playback_state("paused" if paused else "playing")
        elif event_name == "end-file":
            reason = event.get("reason", "")
            if reason == "eof":
                pass  # mpv auto-advances playlist
            else:
                self._update_playback_state("stopped")
                self._update_track(None)
        elif event_name == "property-change":
            prop_name = event.get("name", "")
            if prop_name in ("media-title", "metadata", "path"):
                self._refresh_current_track()
            elif prop_name == "pause":
                paused = event.get("data", False)
                self._update_playback_state("paused" if paused else "playing")
            elif prop_name == "idle-active":
                if event.get("data"):
                    self._update_playback_state("stopped")
                    self._update_track(None)

    def _refresh_current_track(self) -> None:
        path = self._get_property("path")
        metadata = self._get_property("metadata") or {}
        duration = self._get_property("duration")
        if path:
            if duration is not None:
                metadata["duration"] = duration
            track = Track.from_mpv_metadata(str(path), metadata if isinstance(metadata, dict) else {})
            self._update_track(track)

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
        self.time_position: int = 0
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

    # Test helpers
    def emit_track_change(self, track: Track | None) -> None:
        for cb in self._track_change_callbacks:
            cb(track)

    def emit_playback_state_change(self, state: str) -> None:
        for cb in self._playback_state_callbacks:
            cb(state)

    def emit_connection_change(self, connected: bool, reason: str) -> None:
        for cb in self._connection_change_callbacks:
            cb(connected, reason)
```

- [ ] **Step 4: Update `yoyopy/audio/music/__init__.py` to export backend types**

```python
# yoyopy/audio/music/__init__.py
"""Music backend subpackage for YoyoPod."""

from yoyopy.audio.music.backend import MockMusicBackend, MpvBackend, MusicBackend
from yoyopy.audio.music.models import MusicConfig, Playlist, Track

__all__ = [
    "MockMusicBackend",
    "MpvBackend",
    "MusicBackend",
    "MusicConfig",
    "Playlist",
    "Track",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_music_backend.py -v`
Expected: All 14 tests PASS

- [ ] **Step 6: Commit**

```bash
git add yoyopy/audio/music/backend.py yoyopy/audio/music/__init__.py tests/test_music_backend.py
git commit -m "feat(audio): add MusicBackend protocol, MpvBackend, and MockMusicBackend"
```

---

## Task 5: Migrate Core Types and Events

**Files:**
- Modify: `yoyopy/audio/__init__.py`
- Modify: `yoyopy/audio/history.py`
- Modify: `yoyopy/events.py`
- Modify: `yoyopy/coordinators/runtime.py`
- Modify: `yoyopy/coordinators/playback.py`

- [ ] **Step 1: Run the full test suite to establish baseline**

Run: `uv run pytest -q`
Expected: All existing tests PASS (baseline before migration edits)

- [ ] **Step 2: Update `yoyopy/audio/__init__.py`**

Replace the Mopidy re-exports with the new music subpackage types:

```python
# yoyopy/audio/__init__.py
"""
Audio management for YoyoPod.

Provides audio playback, volume control, and device management.
"""

from yoyopy.audio.history import RecentTrackEntry, RecentTrackHistoryStore
from yoyopy.audio.local_service import LocalLibraryItem, LocalMusicService
from yoyopy.audio.manager import AudioManager, AudioDevice
from yoyopy.audio.music import MusicBackend, MockMusicBackend, MpvBackend, Track, Playlist, MusicConfig

__all__ = [
    'AudioDevice',
    'AudioManager',
    'LocalLibraryItem',
    'LocalMusicService',
    'MockMusicBackend',
    'MpvBackend',
    'MusicBackend',
    'MusicConfig',
    'Playlist',
    'RecentTrackEntry',
    'RecentTrackHistoryStore',
    'Track',
]
```

- [ ] **Step 3: Update `yoyopy/audio/history.py`**

Change `MopidyTrack` import to `Track`:

Line 12: `from yoyopy.audio.mopidy_client import MopidyTrack` → `from yoyopy.audio.music.models import Track`

Line 44: `def from_track(cls, track: MopidyTrack)` → `def from_track(cls, track: Track)`

Line 108: `def record_track(self, track: MopidyTrack)` → `def record_track(self, track: Track)`

- [ ] **Step 4: Update `yoyopy/events.py`**

Line 10: `from yoyopy.audio.mopidy_client import MopidyTrack` → `from yoyopy.audio.music.models import Track`

Line 62: `manager: Literal["mopidy"]` → `manager: Literal["music"]`

Line 78: `track: Optional[MopidyTrack]` → `track: Optional[Track]`

- [ ] **Step 5: Update `yoyopy/coordinators/runtime.py`**

Line 23: `from yoyopy.audio.mopidy_client import MopidyClient` → `from yoyopy.audio.music.backend import MusicBackend`

Line 86: `mopidy_client: MopidyClient | None` → `music_backend: MusicBackend | None`

- [ ] **Step 6: Update `yoyopy/coordinators/playback.py`**

Line 10: `from yoyopy.audio.mopidy_client import MopidyTrack` → `from yoyopy.audio.music.models import Track`

Line 47: `def publish_track_change(self, track: MopidyTrack | None)` → `def publish_track_change(self, track: Track | None)`

- [ ] **Step 7: Run the test suite**

Run: `uv run pytest -q`
Expected: Some tests will FAIL due to downstream references to `mopidy_client` — that's expected and will be fixed in Tasks 6-8.

- [ ] **Step 8: Commit the core type migration**

```bash
git add yoyopy/audio/__init__.py yoyopy/audio/history.py yoyopy/events.py yoyopy/coordinators/runtime.py yoyopy/coordinators/playback.py
git commit -m "refactor(audio): migrate core types from MopidyTrack to Track"
```

---

## Task 6: Migrate LocalMusicService

**Files:**
- Modify: `yoyopy/audio/local_service.py`

- [ ] **Step 1: Rewrite local_service.py to use MusicBackend and filesystem scanning**

Replace the full file content. Key changes:
- Constructor takes `MusicBackend | None` and `Path` for `music_dir`
- `list_playlists()` scans filesystem for M3U files
- `_collect_local_track_uris()` globs filesystem for audio files
- URI validation checks path prefix instead of scheme prefix

```python
# yoyopy/audio/local_service.py
"""Local-first music facade backed by MusicBackend and filesystem scanning."""

from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from yoyopy.audio.history import RecentTrackEntry, RecentTrackHistoryStore
from yoyopy.audio.music.backend import MusicBackend
from yoyopy.audio.music.models import Playlist, Track

AUDIO_EXTENSIONS = ("*.mp3", "*.flac", "*.ogg", "*.wav", "*.m4a", "*.opus")


@dataclass(frozen=True, slots=True)
class LocalLibraryItem:
    """One entry in the local Listen landing menu."""

    key: str
    title: str
    subtitle: str


class LocalMusicService:
    """App-facing local music operations backed by MusicBackend + filesystem."""

    def __init__(
        self,
        music_backend: MusicBackend | None,
        music_dir: Path = Path("/home/pi/Music"),
        recent_store: RecentTrackHistoryStore | None = None,
    ) -> None:
        self.music_backend = music_backend
        self.music_dir = music_dir
        self.recent_store = recent_store

    @property
    def is_available(self) -> bool:
        """Return True when the music backend is connected."""
        return bool(self.music_backend and self.music_backend.is_connected)

    def is_local_track_uri(self, uri: str) -> bool:
        """Return True when the URI is a path under the music directory."""
        try:
            return Path(uri).is_relative_to(self.music_dir)
        except (ValueError, TypeError):
            return False

    def is_local_playlist_uri(self, uri: str) -> bool:
        """Return True when the URI is an M3U file under the music directory."""
        try:
            p = Path(uri)
            return p.suffix.lower() == ".m3u" and p.is_relative_to(self.music_dir)
        except (ValueError, TypeError):
            return False

    def menu_items(self) -> list[LocalLibraryItem]:
        """Return the static local-first Listen landing menu."""
        return [
            LocalLibraryItem("playlists", "Playlists", "Saved mixes"),
            LocalLibraryItem("recent", "Recent", "Played lately"),
            LocalLibraryItem("shuffle", "Shuffle", "Start something fun"),
        ]

    def list_playlists(self) -> list[Playlist]:
        """Scan music_dir for M3U files."""
        if not self.music_dir.is_dir():
            return []

        playlists = []
        for p in sorted(self.music_dir.glob("**/*.m3u")):
            try:
                lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
                track_count = sum(1 for ln in lines if ln.strip() and not ln.startswith("#"))
            except OSError:
                track_count = 0
            playlists.append(Playlist(uri=str(p), name=p.stem, track_count=track_count))
        return playlists

    def playlist_count(self) -> int:
        """Return the number of local playlists."""
        return len(self.list_playlists())

    def load_playlist(self, playlist_uri: str) -> bool:
        """Load and play one local playlist."""
        if self.music_backend is None or not self.is_local_playlist_uri(playlist_uri):
            return False
        return self.music_backend.load_playlist_file(playlist_uri)

    def list_recent_tracks(self, limit: int | None = None) -> list[RecentTrackEntry]:
        """Return the current persistent local recent-track list."""
        if self.recent_store is None:
            return []
        return self.recent_store.list_recent(limit)

    def play_recent_track(self, track_uri: str) -> bool:
        """Replace the tracklist with one local track and start playback."""
        if self.music_backend is None or not self.is_local_track_uri(track_uri):
            return False
        return self.music_backend.load_tracks([track_uri])

    def record_recent_track(self, track: Track | None) -> None:
        """Persist one local track play event when it belongs to the local library."""
        if track is None or not self.is_local_track_uri(track.uri) or self.recent_store is None:
            return
        self.recent_store.record_track(track)

    def shuffle_all(self) -> bool:
        """Build a shuffled queue from the local file library and start playback."""
        if self.music_backend is None:
            return False

        track_uris = self._collect_local_track_uris()
        if not track_uris:
            logger.warning("Shuffle requested, but no local tracks were found")
            return False

        random.shuffle(track_uris)
        return self.music_backend.load_tracks(track_uris)

    def _collect_local_track_uris(self) -> list[str]:
        """Scan the music directory for audio files."""
        if not self.music_dir.is_dir():
            return []

        tracks: list[str] = []
        seen: set[str] = set()
        for ext in AUDIO_EXTENSIONS:
            for p in self.music_dir.glob(f"**/{ext}"):
                s = str(p)
                if s not in seen:
                    seen.add(s)
                    tracks.append(s)
        return tracks
```

- [ ] **Step 2: Commit**

```bash
git add yoyopy/audio/local_service.py
git commit -m "refactor(audio): migrate LocalMusicService from Mopidy to MusicBackend + filesystem"
```

---

## Task 7: Migrate Coordinators, Screens, and Config

**Files:**
- Modify: `yoyopy/coordinators/call.py`
- Modify: `yoyopy/coordinators/screen.py`
- Modify: `yoyopy/ui/screens/navigation/hub.py`
- Modify: `yoyopy/ui/screens/music/now_playing.py`
- Modify: `yoyopy/config/models.py`

- [ ] **Step 1: Update `yoyopy/coordinators/call.py`**

Line 183-184: `self.runtime.mopidy_client.get_playback_state()` / `if self.runtime.mopidy_client and self.runtime.mopidy_client.is_connected` → `self.runtime.music_backend.get_playback_state()` / `if self.runtime.music_backend and self.runtime.music_backend.is_connected`

Line 191-192: `if self.runtime.mopidy_client:` / `self.runtime.mopidy_client.pause()` → `if self.runtime.music_backend:` / `self.runtime.music_backend.pause()`

Line 247-248: `if self.runtime.mopidy_client:` / `self.runtime.mopidy_client.play()` → `if self.runtime.music_backend:` / `self.runtime.music_backend.play()`

- [ ] **Step 2: Update `yoyopy/coordinators/screen.py`**

Line 42-43: `if self.runtime.mopidy_client and self.runtime.mopidy_client.is_connected:` / `playback_state = self.runtime.mopidy_client.get_playback_state()` → `if self.runtime.music_backend and self.runtime.music_backend.is_connected:` / `playback_state = self.runtime.music_backend.get_playback_state()`

- [ ] **Step 3: Update `yoyopy/ui/screens/navigation/hub.py`**

Line 16: `from yoyopy.audio.mopidy_client import MopidyClient` → `from yoyopy.audio.music.backend import MusicBackend`

Line 38: `mopidy_client: Optional["MopidyClient"] = None,` → `music_backend: Optional["MusicBackend"] = None,`

Line 43: `self.mopidy_client = mopidy_client` → `self.music_backend = music_backend`

All remaining references to `self.mopidy_client` in the file → `self.music_backend`

- [ ] **Step 4: Update `yoyopy/ui/screens/music/now_playing.py`**

Line 24: `mopidy_client=None,` → `music_backend=None,`

All references to `self.mopidy_client` → `self.music_backend`

- [ ] **Step 5: Update `yoyopy/config/models.py`**

Replace lines 148-149:

```python
    mopidy_host: str = config_value(default="localhost", env="YOYOPOD_MOPIDY_HOST")
    mopidy_port: int = config_value(default=6680, env="YOYOPOD_MOPIDY_PORT")
```

With:

```python
    music_dir: str = config_value(default="/home/pi/Music", env="YOYOPOD_MUSIC_DIR")
    mpv_socket: str = config_value(default="", env="YOYOPOD_MPV_SOCKET")
    mpv_binary: str = config_value(default="mpv", env="YOYOPOD_MPV_BINARY")
    alsa_device: str = config_value(default="default", env="YOYOPOD_ALSA_DEVICE")
```

- [ ] **Step 6: Commit**

```bash
git add yoyopy/coordinators/call.py yoyopy/coordinators/screen.py yoyopy/ui/screens/navigation/hub.py yoyopy/ui/screens/music/now_playing.py yoyopy/config/models.py
git commit -m "refactor: migrate coordinators, screens, and config from Mopidy to mpv"
```

---

## Task 8: Migrate app.py

**Files:**
- Modify: `yoyopy/app.py`

- [ ] **Step 1: Update imports (line 20)**

```python
from yoyopy.audio import LocalMusicService, MopidyClient, RecentTrackHistoryStore
```
→
```python
from yoyopy.audio import LocalMusicService, RecentTrackHistoryStore
from yoyopy.audio.music import MpvBackend, MusicConfig
```

- [ ] **Step 2: Update instance variable (line 128)**

`self.mopidy_client: Optional[MopidyClient] = None` → `self.music_backend: Optional[MpvBackend] = None`

- [ ] **Step 3: Update recovery state (line 198)**

`self._mopidy_recovery = _RecoveryState()` → `self._music_recovery = _RecoveryState()`

- [ ] **Step 4: Update `_init_managers()` music section (lines 490-504)**

Replace:
```python
            logger.info("  - MopidyClient")
            mopidy_host = (
                self.app_settings.audio.mopidy_host if self.app_settings else "localhost"
            )
            mopidy_port = self.app_settings.audio.mopidy_port if self.app_settings else 6680
            self.mopidy_client = MopidyClient(host=mopidy_host, port=mopidy_port)
            self.local_music_service = LocalMusicService(
                self.mopidy_client,
                recent_store=self.recent_track_store,
            )
            if self.mopidy_client.connect():
                logger.info("    ✓ Mopidy connected successfully")
                self.mopidy_client.start_polling()
            else:
                logger.warning("    ⚠ Mopidy connection failed (VoIP-only mode)")
```

With:
```python
            logger.info("  - MpvBackend")
            audio_cfg = self.app_settings.audio if self.app_settings else None
            music_config = MusicConfig(
                music_dir=Path(audio_cfg.music_dir) if audio_cfg else Path("/home/pi/Music"),
                mpv_socket=audio_cfg.mpv_socket if audio_cfg and audio_cfg.mpv_socket else "",
                mpv_binary=audio_cfg.mpv_binary if audio_cfg else "mpv",
                alsa_device=audio_cfg.alsa_device if audio_cfg else "default",
            )
            self.music_backend = MpvBackend(music_config)
            self.local_music_service = LocalMusicService(
                self.music_backend,
                music_dir=music_config.music_dir,
                recent_store=self.recent_track_store,
            )
            if self.music_backend.start():
                logger.info("    ✓ mpv music backend started")
            else:
                logger.warning("    ⚠ mpv backend failed to start (VoIP-only mode)")
```

- [ ] **Step 5: Update `_setup_screens()` — hub and now_playing construction (lines 535, 556)**

Line 535: `mopidy_client=self.mopidy_client,` → `music_backend=self.music_backend,`

Line 556: `mopidy_client=self.mopidy_client,` → `music_backend=self.music_backend,`

- [ ] **Step 6: Update `_ensure_coordinators()` (line 998)**

`mopidy_client=self.mopidy_client,` → `music_backend=self.music_backend,`

- [ ] **Step 7: Update `_setup_music_callbacks()` (lines 756-767)**

Replace:
```python
        if not self.mopidy_client:
            logger.warning("  MopidyClient not available, skipping callbacks")
            return

        self._ensure_coordinators()
        self.mopidy_client.on_track_change(self.playback_coordinator.publish_track_change)
        self.mopidy_client.on_playback_state_change(
            self.playback_coordinator.publish_playback_state_change
        )
        self.mopidy_client.on_connection_change(
            self.playback_coordinator.publish_availability_change
        )
```

With:
```python
        if not self.music_backend:
            logger.warning("  MusicBackend not available, skipping callbacks")
            return

        self._ensure_coordinators()
        self.music_backend.on_track_change(self.playback_coordinator.publish_track_change)
        self.music_backend.on_playback_state_change(
            self.playback_coordinator.publish_playback_state_change
        )
        self.music_backend.on_connection_change(
            self.playback_coordinator.publish_availability_change
        )
```

- [ ] **Step 8: Update recovery handler (lines 854-874)**

Replace `"mopidy"` with `"music"`, `self._mopidy_recovery` with `self._music_recovery`, `self.mopidy_client` with `self.music_backend`, and remove the `start_polling()` call (mpv uses push events, no polling):

```python
    def _handle_recovery_attempt_completed_event(
        self,
        event: RecoveryAttemptCompletedEvent,
    ) -> None:
        if event.manager != "music":
            return

        self._music_recovery.in_flight = False
        if self._stopping:
            return

        self._finalize_recovery_attempt(
            "Music",
            self._music_recovery,
            event.recovered,
            event.recovery_now,
        )
```

- [ ] **Step 9: Update recovery attempt methods (lines 1380-1419)**

Replace `_attempt_mopidy_recovery`, `_start_mopidy_recovery_worker`, `_run_mopidy_recovery_attempt` with:

```python
    def _attempt_music_recovery(self, recovery_now: float) -> None:
        """Reconnect the music backend when it becomes unavailable."""
        if self.music_backend is None:
            return

        if self.music_backend.is_connected:
            self._music_recovery.reset()
            return

        if self._music_recovery.in_flight:
            return

        if recovery_now < self._music_recovery.next_attempt_at:
            return

        logger.info("Attempting music backend recovery")
        self._music_recovery.in_flight = True
        self._start_music_recovery_worker(recovery_now)

    def _start_music_recovery_worker(self, recovery_now: float) -> None:
        worker = threading.Thread(
            target=self._run_music_recovery_attempt,
            args=(recovery_now,),
            daemon=True,
            name="music-recovery",
        )
        worker.start()

    def _run_music_recovery_attempt(self, recovery_now: float) -> None:
        recovered = False
        if not self._stopping and self.music_backend is not None:
            recovered = self.music_backend.start()

        self.event_bus.publish(
            RecoveryAttemptCompletedEvent(
                manager="music",
                recovered=recovered,
                recovery_now=recovery_now,
            )
        )
```

- [ ] **Step 10: Update shutdown (lines 1572-1575)**

Replace:
```python
        if self.mopidy_client:
            logger.info("  - Stopping music polling")
            self.mopidy_client.stop_polling()
            self.mopidy_client.cleanup()
```

With:
```python
        if self.music_backend:
            logger.info("  - Stopping music backend")
            self.music_backend.stop()
```

- [ ] **Step 11: Update `get_status()` and snapshot references (lines 969, 1615)**

All references to `self.mopidy_client` → `self.music_backend`, `self.mopidy_client.is_connected` → `self.music_backend.is_connected`.

Also update the call to `_attempt_mopidy_recovery` in the coordinator tick to `_attempt_music_recovery`.

- [ ] **Step 12: Commit**

```bash
git add yoyopy/app.py
git commit -m "refactor(app): replace MopidyClient with MpvBackend"
```

---

## Task 9: Migrate Tests

**Files:**
- Modify: `tests/test_fsm_runtime.py`
- Modify: `tests/test_local_music_service.py`
- Modify: `tests/test_app_orchestration.py`
- Modify: `tests/test_whisplay_one_button.py`
- Modify: `tests/test_now_playing_lvgl_view.py`
- Modify: `tests/test_playlist_lvgl_view.py`
- Delete: `tests/test_mopidy_client.py`

- [ ] **Step 1: Update `tests/test_fsm_runtime.py`**

Line 20: `mopidy_client=None,` → `music_backend=None,`

- [ ] **Step 2: Update `tests/test_local_music_service.py`**

Replace `FakeMopidyClient` with `MockMusicBackend`. Replace `MopidyTrack` with `Track`. Update `LocalMusicService` construction to pass `music_dir` and `music_backend`. Update URI assertions from `local:track:` to filesystem paths. Replace `fetch_track_counts` parameter usage (no longer needed).

- [ ] **Step 3: Update `tests/test_app_orchestration.py`**

Replace `FakeMopidyClient` / `FakeRecoveringMopidyClient` with `MockMusicBackend`. Update field names from `mopidy_client` to `music_backend`. Update `"mopidy"` to `"music"` in recovery events.

- [ ] **Step 4: Update `tests/test_whisplay_one_button.py`**

Replace all `FakeMopidyClient` usage with `MockMusicBackend`. Update constructor kwargs from `mopidy_client=` to `music_backend=`. Update `LocalMusicService` construction.

- [ ] **Step 5: Update `tests/test_now_playing_lvgl_view.py`**

Replace `FakeMopidyClient` with `MockMusicBackend`. Update `mopidy_client=` to `music_backend=`.

- [ ] **Step 6: Update `tests/test_playlist_lvgl_view.py`**

Replace `FakeMopidyClient` with `MockMusicBackend`. Update `LocalMusicService` construction.

- [ ] **Step 7: Delete `tests/test_mopidy_client.py`**

```bash
git rm tests/test_mopidy_client.py
```

- [ ] **Step 8: Run the full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS

- [ ] **Step 9: Commit**

```bash
git add tests/
git commit -m "test: migrate all tests from MopidyClient to MockMusicBackend"
```

---

## Task 10: Delete Mopidy and Final Verification

**Files:**
- Delete: `yoyopy/audio/mopidy_client.py`

- [ ] **Step 1: Delete the old Mopidy client**

```bash
git rm yoyopy/audio/mopidy_client.py
```

- [ ] **Step 2: Search for any remaining Mopidy references**

Run: `grep -ri "mopidy" yoyopy/ tests/ --include="*.py" -l`
Expected: No results (or only doc strings / comments that are acceptable)

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS

- [ ] **Step 4: Run compile check**

Run: `python -m compileall yoyopy tests`
Expected: No compilation errors

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: remove mopidy_client.py — mpv migration complete"
```

---

## Task 11: Add tinytag Dependency

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Add tinytag to dependencies**

Run: `uv add tinytag`

- [ ] **Step 2: Verify install**

Run: `uv sync --extra dev`

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest -q`
Expected: All tests PASS

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "deps: add tinytag for local music file tag reading"
```
