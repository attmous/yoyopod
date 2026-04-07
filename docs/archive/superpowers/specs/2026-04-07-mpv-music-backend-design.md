# Replace Mopidy with mpv Music Backend

**Date:** 2026-04-07
**Status:** Design approved
**Approach:** Abstract MusicBackend protocol + MpvBackend (separate process, app-managed)

---

## Motivation

Mopidy is the heaviest single process on the Pi Zero 2W (~50-80 MB RSS). It runs its own Python runtime plus GStreamer for what is fundamentally local-file playback. Replacing it with mpv (C + ffmpeg) saves ~50 MB RAM, eliminates the 2-second polling delay for track changes, and removes a separate daemon from the deploy surface.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Player | mpv (libmpv/ffmpeg) | Mature C player, ARM NEON-optimized codecs, JSON IPC built-in |
| Process model | Separate process | Crash-isolated from UI/VoIP; matches Mopidy's current isolation |
| Architecture | `MusicBackend` Protocol | Mirrors existing `VoIPBackend` pattern; enables `MockMusicBackend` for tests |
| Process lifecycle | App-managed | mpv starts in ~50ms, no state to preserve; one fewer systemd unit |
| Library scanning | Filesystem glob in `LocalMusicService` | Replaces Mopidy's RPC-based `browse_library`; faster, no round-trips |
| Music directory | Single configured root (e.g. `/home/pi/Music`) | Sufficient for YoyoPod's local-first model |
| Tag reading | `tinytag` (pure Python) | Lightweight (~30KB), no C deps, reads ID3/Vorbis/FLAC tags |
| ALSA device switching | Runtime via `set_property audio-device` | No mpv restart needed; supports speaker/headphone switching |

## Module Layout

```
yoyopy/audio/
  __init__.py              # re-exports (updated)
  manager.py               # AudioManager (unchanged)
  history.py               # RecentTrackHistoryStore (Track rename only)
  local_service.py         # LocalMusicService (swap to MusicBackend + fs scan)
  music/
    __init__.py
    models.py              # Track, Playlist, MusicConfig
    backend.py             # MusicBackend Protocol + MpvBackend + MockMusicBackend
    ipc.py                 # MpvIpcClient (socket read/write, JSON parsing)
    process.py             # MpvProcess (spawn, health check, kill, respawn)
```

`mopidy_client.py` is deleted at the end of migration.

## Data Models

### Track (replaces MopidyTrack)

```python
@dataclass(frozen=True, slots=True)
class Track:
    uri: str
    name: str
    artists: list[str]
    album: str = ""
    length: int = 0  # milliseconds
    track_no: int | None = None

    def get_artist_string(self) -> str:
        return ", ".join(self.artists) if self.artists else "Unknown Artist"

    @classmethod
    def from_mpv_metadata(cls, path: str, metadata: dict) -> "Track":
        """Build from mpv's 'metadata' property at runtime."""
        ...

    @classmethod
    def from_file_tags(cls, path: Path) -> "Track":
        """Build from tinytag for library scanning."""
        ...
```

### Playlist (replaces MopidyPlaylist)

```python
@dataclass(frozen=True, slots=True)
class Playlist:
    uri: str
    name: str
    track_count: int = 0
```

### MusicConfig

```python
@dataclass(slots=True)
class MusicConfig:
    music_dir: Path              # e.g. /home/pi/Music
    mpv_socket: str = "/tmp/yoyopod-mpv.sock"
    mpv_binary: str = "mpv"
    alsa_device: str = "default"
```

## MusicBackend Protocol

```python
class MusicBackend(Protocol):
    # Lifecycle
    def start(self) -> bool: ...
    def stop(self) -> None: ...

    @property
    def is_connected(self) -> bool: ...  # property, not method -- matches MopidyClient.is_connected

    # Transport
    def play(self) -> bool: ...
    def pause(self) -> bool: ...
    def stop_playback(self) -> bool: ...
    def next_track(self) -> bool: ...
    def previous_track(self) -> bool: ...

    # Volume
    def set_volume(self, volume: int) -> bool: ...
    def get_volume(self) -> int | None: ...

    # Audio device
    def set_audio_device(self, device: str) -> bool: ...

    # State queries
    def get_current_track(self) -> Track | None: ...
    def get_playback_state(self) -> str: ...    # "playing" | "paused" | "stopped"
    def get_time_position(self) -> int: ...      # milliseconds

    # Queue
    def load_tracks(self, uris: list[str]) -> bool: ...
    def load_playlist_file(self, path: str) -> bool: ...

    # Callbacks
    def on_track_change(self, callback: Callable[[Track | None], None]) -> None: ...
    def on_playback_state_change(self, callback: Callable[[str], None]) -> None: ...
    def on_connection_change(self, callback: Callable[[bool, str], None]) -> None: ...
```

### Compared to MopidyClient

- **Added:** `set_audio_device()` (runtime ALSA switching), `start()`/`stop()` (lifecycle, matching VoIP pattern)
- **Removed:** `connect()` absorbed into `start()`. `browse_library()`/`get_playlists()` moved to `LocalMusicService` (filesystem scan).
- **Renamed:** `load_track_uris()` -> `load_tracks()`, `load_playlist()` -> `load_playlist_file()`

## mpv IPC Transport (ipc.py)

- Connects to Unix socket at `MusicConfig.mpv_socket`
- Sends newline-delimited JSON: `{"command": ["get_property", "pause"]}\n`
- Background reader thread splits responses (have `request_id`) from events (have `event` field)
- Exposes: `send_command(args) -> dict`, `observe_property(name)`, `on_event(callback)`

## mpv Process Management (process.py)

```python
class MpvProcess:
    def spawn(self) -> bool:
        """Launch: mpv --idle --no-video --input-ipc-server=<sock> --audio-device=alsa/<dev>"""

    def is_alive(self) -> bool:
        """Check process.poll() is None"""

    def kill(self) -> None:
        """SIGTERM, wait 2s, SIGKILL if needed. Clean up socket file."""

    def respawn(self) -> bool:
        """kill() then spawn()"""
```

## MpvBackend Composition

1. `start()` -> `MpvProcess.spawn()` -> `MpvIpcClient.connect()` -> subscribe to mpv events (`file-loaded`, `pause`, `unpause`, `end-file`) -> fire `on_connection_change(True)`
2. Transport methods -> `ipc.send_command(...)`
3. Track/state changes arrive as pushed events on the reader thread -> fire registered callbacks (no more 2-second polling)
4. `stop()` -> `MpvIpcClient.disconnect()` -> `MpvProcess.kill()`

### Recovery

`MpvBackend.is_connected()` checks both socket liveness and `MpvProcess.is_alive()`. The existing recovery pattern in `app.py` calls `start()` again, which does `respawn()` + reconnect.

## LocalMusicService Changes

### Constructor

```python
class LocalMusicService:
    def __init__(
        self,
        music_backend: MusicBackend | None,
        music_dir: Path,
        recent_store: RecentTrackHistoryStore | None = None,
    ) -> None:
```

### Library/playlist scanning (new)

```python
def list_playlists(self) -> list[Playlist]:
    """Scan music_dir for M3U files. Count lines to get track_count."""
    return [
        Playlist(uri=str(p), name=p.stem,
                 track_count=sum(1 for ln in p.read_text().splitlines()
                                 if ln.strip() and not ln.startswith("#")))
        for p in self.music_dir.glob("**/*.m3u")
    ]

def _collect_local_track_uris(self) -> list[str]:
    """Scan music_dir for audio files."""
    uris = []
    for ext in ("*.mp3", "*.flac", "*.ogg", "*.wav"):
        uris.extend(str(p) for p in self.music_dir.glob(f"**/{ext}"))
    return uris
```

### URI scheme change

- Old: `local:track:file.mp3`, `m3u:playlist.m3u`
- New: plain filesystem paths `/home/pi/Music/file.mp3`
- `is_local_track_uri()` / `is_local_playlist_uri()` update to check path prefix under `music_dir`
- Existing recent-track history with old `local:` URIs will no longer match. Acceptable for a backend swap.

## App Integration Surface

### app.py

- Replace `MopidyClient` construction with `MpvBackend` construction
- Spawn mpv via `MpvProcess` instead of connecting to external Mopidy daemon
- `_attempt_mopidy_recovery` -> `_attempt_music_recovery` (same pattern, calls `backend.start()`)
- `RecoveryAttemptCompletedEvent(manager="mopidy")` -> `manager="music"`

### coordinators/runtime.py

- `mopidy_client: MopidyClient | None` -> `music_backend: MusicBackend | None`
- `call.py` and `screen.py`: change field name. Method signatures identical.

### events.py

- `TrackChangedEvent.track: MopidyTrack` -> `Track`
- `RecoveryAttemptCompletedEvent.manager` literal: `"mopidy"` -> `"music"`
- `PlaybackStateChangedEvent` / `MusicAvailabilityChangedEvent` unchanged

### config/models.py

- `AppAudioConfig.mopidy_host` / `mopidy_port` -> `music_dir`, `mpv_socket`, `mpv_binary`, `alsa_device`
- Env vars: `YOYOPOD_MUSIC_DIR`, `YOYOPOD_MPV_SOCKET`, `YOYOPOD_MPV_BINARY`, `YOYOPOD_ALSA_DEVICE`

### Screens (hub.py, now_playing.py)

- Import rename only: `MopidyClient` -> `MusicBackend`, `MopidyTrack` -> `Track`
- No logic changes

### Tests

- `test_mopidy_client.py` -> `test_mpv_backend.py` (rewrite against MockMusicBackend)
- Other test files: import renames only

### Deleted

- `yoyopy/audio/mopidy_client.py`
- Mopidy config entries in `config/yoyopod_config.yaml`
- Mopidy references in deploy scripts / systemd

## Pi Deployment

```bash
# Install mpv on Pi (one-time)
sudo apt install mpv

# mpv is app-managed, no systemd unit needed
# YoyoPod spawns: mpv --idle --no-video --input-ipc-server=/tmp/yoyopod-mpv.sock --audio-device=alsa/<device>
```

## RAM Impact

| | Before (Mopidy) | After (mpv) |
|---|---|---|
| Music process RSS | 50-80 MB | 15-30 MB |
| Total app footprint | ~145-195 MB | ~110-145 MB |
| Free headroom (of 416 MB) | ~220-270 MB | ~270-305 MB |

## Event Model Improvement

Mopidy required 2-second polling for track/state changes. mpv pushes events over the IPC socket:

- `file-loaded` -> track changed
- `pause` / `unpause` -> playback state changed
- `end-file` -> track ended
- `property-change` (observed) -> metadata/volume/position updates

Callbacks fire instantly instead of up to 2 seconds late.

## Simulation Mode (Windows/macOS)

mpv uses named pipes on Windows (`\\.\pipe\yoyopod-mpv`) instead of Unix sockets. `MpvProcess` and `MpvIpcClient` must handle this:

- `MpvProcess.spawn()` passes `--input-ipc-server=\\.\pipe\yoyopod-mpv` on Windows
- `MpvIpcClient` connects via `open()` on a named pipe (Windows) or `socket.AF_UNIX` (Linux/macOS)
- `MusicConfig.mpv_socket` default adjusts per platform

This keeps `--simulate` mode working on dev machines.
