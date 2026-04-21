# Phase A — Plan 5: Music Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate local music playback (mpv-backed) into the new integration architecture. First integration to exercise the `focus` arbiter — `music.play` acquires focus, `AudioFocusLostEvent` auto-pauses playback.

**Architecture:** `MpvBackend` (+ `process.py`, `ipc.py`) moves to `src/yoyopod/backends/music/`. `LocalMusicService` becomes `src/yoyopod/integrations/music/library.py`. `PlaybackCoordinator` deleted. State entities mirror backend status; focus-loss subscriber handles auto-pause.

**Tech Stack:** Python 3.12+, pytest, uv, existing mpv IPC.

**Spec reference:** spec §3.2, §5 (music entities), §7 (music commands), §9.1/§9.2 (fate of MpvBackend + LocalMusicService + PlaybackCoordinator + MusicFSM).

**Prerequisite:** Plans 1-4 executed; `focus` integration available.

---

## File Structure

### Files to create

- `src/yoyopod/backends/music/__init__.py`
- `src/yoyopod/backends/music/mpv.py` (moved from `src/yoyopod/audio/music/backend.py`)
- `src/yoyopod/backends/music/process.py` (moved)
- `src/yoyopod/backends/music/ipc.py` (moved)
- `src/yoyopod/backends/music/models.py` (moved from `src/yoyopod/audio/music/models.py`)
- `src/yoyopod/integrations/music/__init__.py`
- `src/yoyopod/integrations/music/commands.py`
- `src/yoyopod/integrations/music/events.py`
- `src/yoyopod/integrations/music/handlers.py`
- `src/yoyopod/integrations/music/library.py` (moved from `src/yoyopod/audio/local_service.py`)
- `src/yoyopod/integrations/music/history.py` (moved from `src/yoyopod/audio/history.py`)
- `tests/integrations/test_music.py`

### Files to delete

- `src/yoyopod/audio/music/` (the whole subpackage — all files moved)
- `src/yoyopod/audio/manager.py` (if exists and is a thin shim)
- `src/yoyopod/audio/local_service.py` (moved)
- `src/yoyopod/audio/history.py` (moved)
- `src/yoyopod/coordinators/playback.py`
- Legacy `MusicFSM` lives in `src/yoyopod/fsm.py` — that file is deleted in Plan 8's final sweep, not here.

### Files that stay

- `src/yoyopod/audio/volume.py`, `src/yoyopod/audio/volume_controller.py` — shared ALSA volume control — stay under `audio/` for now (used by both music and call ring tone). They may be re-homed later.

---

## Task 1: Branch state verification

- [ ] **Step 1.1: Confirm Plans 1-4 complete**

```bash
git log --oneline -20
ls src/yoyopod/integrations/
uv run pytest tests/ -q
```

Expected: 9 integrations exist (power, network, location, contacts, cloud, focus, diagnostics, screen, voice); all tests green.

---

## Task 2: Relocate mpv backend

- [ ] **Step 2.1: Move files under `backends/music/`**

```bash
mkdir -p src/yoyopod/backends/music
git mv src/yoyopod/audio/music/backend.py src/yoyopod/backends/music/mpv.py
git mv src/yoyopod/audio/music/process.py src/yoyopod/backends/music/process.py
git mv src/yoyopod/audio/music/ipc.py src/yoyopod/backends/music/ipc.py
git mv src/yoyopod/audio/music/models.py src/yoyopod/backends/music/models.py
```

- [ ] **Step 2.2: Update internal imports**

Grep:
```bash
grep -rn "from yoyopod.audio.music" src/yoyopod/backends/music/
```

Rewrite each occurrence to `from yoyopod.backends.music.<name>`.

- [ ] **Step 2.3: Create `src/yoyopod/backends/music/__init__.py`**

```python
"""MpvBackend and media models."""

from __future__ import annotations

from yoyopod.backends.music.mpv import MpvBackend, MusicBackend
from yoyopod.backends.music.models import MusicConfig, Playlist, Track

__all__ = ["MpvBackend", "MusicBackend", "Track", "Playlist", "MusicConfig"]
```

- [ ] **Step 2.4: Delete `src/yoyopod/audio/music/__init__.py`**

```bash
git rm src/yoyopod/audio/music/__init__.py
```

- [ ] **Step 2.5: Update external imports of `yoyopod.audio.music.*`**

```bash
grep -rn "from yoyopod.audio.music" src/ tests/
```

Rewrite each to `from yoyopod.backends.music`. Some tests like `tests/test_music_backend.py` will need updating.

- [ ] **Step 2.6: Run affected tests**

```bash
uv run pytest tests/test_music_backend.py -v
```

Expected: pass (adapter still works; just new import paths).

- [ ] **Step 2.7: Commit**

```bash
git add -A
git commit -m "refactor(music): move MpvBackend + mpv adapters to src/yoyopod/backends/music/

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Move `LocalMusicService` under `integrations/music/library.py`

- [ ] **Step 3.1: Relocate**

```bash
mkdir -p src/yoyopod/integrations/music
git mv src/yoyopod/audio/local_service.py src/yoyopod/integrations/music/library.py
git mv src/yoyopod/audio/history.py src/yoyopod/integrations/music/history.py
```

- [ ] **Step 3.2: Update imports**

Grep + rewrite:
```bash
grep -rn "from yoyopod.audio.local_service\|from yoyopod.audio.history\|from yoyopod.audio import.*LocalMusicService\|from yoyopod.audio import.*RecentTrackHistoryStore" src/ tests/
```

Rewrite to `from yoyopod.integrations.music.library import LocalMusicService` and `from yoyopod.integrations.music.history import RecentTrackHistoryStore`.

- [ ] **Step 3.3: Commit**

```bash
git add -A
git commit -m "refactor(music): LocalMusicService + RecentTrackHistoryStore into integrations/music/

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Write music commands + events

- [ ] **Step 4.1: Create `src/yoyopod/integrations/music/commands.py`**

```python
"""Typed commands for the music integration."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlayCommand:
    """Start playback of the given URI; acquires audio focus."""

    track_uri: str
    start_position_seconds: float = 0.0


@dataclass(frozen=True, slots=True)
class PauseCommand:
    """Pause playback without releasing focus."""


@dataclass(frozen=True, slots=True)
class ResumeCommand:
    """Resume paused playback (re-acquires focus if lost)."""


@dataclass(frozen=True, slots=True)
class StopCommand:
    """Stop playback and release focus."""


@dataclass(frozen=True, slots=True)
class NextCommand:
    """Skip to next track in current playlist."""


@dataclass(frozen=True, slots=True)
class PrevCommand:
    """Skip to previous track."""


@dataclass(frozen=True, slots=True)
class SeekCommand:
    """Seek to absolute position in seconds."""

    position_seconds: float


@dataclass(frozen=True, slots=True)
class SetVolumeCommand:
    """Set playback volume percent (0-100)."""

    percent: int
```

- [ ] **Step 4.2: Create `src/yoyopod/integrations/music/events.py`**

```python
"""Music-specific domain events."""

from __future__ import annotations

from dataclasses import dataclass

from yoyopod.backends.music.models import Track


@dataclass(frozen=True, slots=True)
class TrackPlaybackCompletedEvent:
    """Published when a track finishes playing (end-of-file)."""

    track: Track | None
```

- [ ] **Step 4.3: Commit**

```bash
git add src/yoyopod/integrations/music/commands.py src/yoyopod/integrations/music/events.py
git commit -m "feat(integrations/music): typed commands + domain events

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Write music handlers + setup

- [ ] **Step 5.1: Create `src/yoyopod/integrations/music/handlers.py`**

```python
"""State-update handlers for the music integration."""

from __future__ import annotations

from typing import Any


def apply_playback_state_to_state(app: Any, state: str, reason: str = "") -> None:
    """state is one of 'idle', 'playing', 'paused'."""
    app.states.set(
        "music.state",
        state,
        attrs={"reason": reason} if reason else None,
    )


def apply_track_to_state(app: Any, track: Any | None) -> None:
    """Mirror the current track into state."""
    if track is None:
        app.states.set("music.track", None)
        return
    app.states.set(
        "music.track",
        track,
        attrs={
            "title": getattr(track, "name", "") or getattr(track, "title", ""),
            "artist": getattr(track, "artist", ""),
            "duration_seconds": float(getattr(track, "duration_seconds", 0.0) or 0.0),
            "path": getattr(track, "path", ""),
        },
    )


def apply_backend_availability_to_state(app: Any, available: bool, reason: str = "") -> None:
    app.states.set("music.backend_available", bool(available), attrs={"reason": reason} if reason else None)


def apply_volume_to_state(app: Any, percent: int) -> None:
    app.states.set("music.volume_percent", max(0, min(100, int(percent))))
```

- [ ] **Step 5.2: Create `src/yoyopod/integrations/music/__init__.py`**

```python
"""Music integration: mpv playback, library, playlists, focus-coordinated pause/resume."""

from __future__ import annotations

from typing import Any

from loguru import logger

from yoyopod.integrations.focus.arbiter import release_focus, request_focus
from yoyopod.integrations.focus.events import AudioFocusLostEvent
from yoyopod.integrations.music.commands import (
    NextCommand,
    PauseCommand,
    PlayCommand,
    PrevCommand,
    ResumeCommand,
    SeekCommand,
    SetVolumeCommand,
    StopCommand,
)
from yoyopod.integrations.music.handlers import (
    apply_backend_availability_to_state,
    apply_playback_state_to_state,
    apply_track_to_state,
    apply_volume_to_state,
)

_STATE_KEY = "_music_integration"


def setup(app: Any, backend: Any | None = None, library: Any | None = None) -> None:
    if backend is None:
        from yoyopod.backends.music import MpvBackend
        backend = MpvBackend(app.config.audio)

    if library is None:
        from yoyopod.integrations.music.library import LocalMusicService
        from yoyopod.integrations.music.history import RecentTrackHistoryStore
        recent_store = RecentTrackHistoryStore(app.config.audio)
        library = LocalMusicService(app.config.audio, recent_store=recent_store)

    # Start the backend.
    started = backend.start()
    apply_backend_availability_to_state(app, started, reason="start" if started else "start_failed")
    if started:
        apply_playback_state_to_state(app, "idle")
        apply_volume_to_state(app, int(getattr(app.config.audio, "default_volume", 70)))

    # Backend callback: playback state.
    def on_backend_playback_state(state: str) -> None:
        app.scheduler.run_on_main(
            lambda s=state: apply_playback_state_to_state(app, s)
        )

    # Backend callback: track change.
    def on_backend_track_change(track: Any | None) -> None:
        app.scheduler.run_on_main(lambda t=track: apply_track_to_state(app, t))
        if track is not None:
            app.scheduler.run_on_main(lambda t=track: library.record_recent_track(t))

    # Backend callback: connectivity/availability.
    def on_backend_availability(available: bool, reason: str = "") -> None:
        app.scheduler.run_on_main(
            lambda a=available, r=reason: apply_backend_availability_to_state(app, a, r)
        )

    # Register callbacks with the backend.
    backend.on_playback_state_change(on_backend_playback_state)
    backend.on_track_change(on_backend_track_change)
    backend.on_availability_change(on_backend_availability)

    # Subscribe to focus loss → auto-pause playback.
    def on_focus_lost(ev: AudioFocusLostEvent) -> None:
        if ev.owner != "music":
            return
        if app.states.get_value("music.state") == "playing":
            logger.info("Music auto-pausing due to focus loss to {}", ev.preempted_by)
            backend.pause()

    app.bus.subscribe(AudioFocusLostEvent, on_focus_lost)

    # Commands.
    def handle_play(cmd: PlayCommand) -> None:
        request_focus(app, "music")
        backend.play(cmd.track_uri, start_position=cmd.start_position_seconds)

    def handle_pause(_cmd: PauseCommand) -> None:
        backend.pause()

    def handle_resume(_cmd: ResumeCommand) -> None:
        request_focus(app, "music")
        backend.resume()

    def handle_stop(_cmd: StopCommand) -> None:
        backend.stop()
        release_focus(app, "music")

    def handle_next(_cmd: NextCommand) -> None:
        backend.next_track()

    def handle_prev(_cmd: PrevCommand) -> None:
        backend.prev_track()

    def handle_seek(cmd: SeekCommand) -> None:
        backend.seek(cmd.position_seconds)

    def handle_set_volume(cmd: SetVolumeCommand) -> None:
        backend.set_volume(cmd.percent)
        apply_volume_to_state(app, cmd.percent)

    app.services.register("music", "play", handle_play)
    app.services.register("music", "pause", handle_pause)
    app.services.register("music", "resume", handle_resume)
    app.services.register("music", "stop", handle_stop)
    app.services.register("music", "next", handle_next)
    app.services.register("music", "prev", handle_prev)
    app.services.register("music", "seek", handle_seek)
    app.services.register("music", "set_volume", handle_set_volume)

    setattr(app, _STATE_KEY, {"backend": backend, "library": library})


def teardown(app: Any) -> None:
    state = getattr(app, _STATE_KEY, None)
    if state is None:
        return
    try:
        state["backend"].stop()
        state["backend"].shutdown()
    except Exception as exc:
        logger.error("MpvBackend shutdown: {}", exc)
    delattr(app, _STATE_KEY)
```

- [ ] **Step 5.3: Create `tests/integrations/test_music.py`**

```python
from dataclasses import dataclass, field

import pytest

from yoyopod.core.testing import build_test_app
from yoyopod.integrations.focus import setup as setup_focus, teardown as teardown_focus
from yoyopod.integrations.focus.arbiter import request_focus
from yoyopod.integrations.focus.events import AudioFocusLostEvent
from yoyopod.integrations.music import setup as setup_music, teardown as teardown_music
from yoyopod.integrations.music.commands import (
    PauseCommand,
    PlayCommand,
    ResumeCommand,
    SetVolumeCommand,
    StopCommand,
)


@dataclass
class _FakeMpvBackend:
    playback_state_cb: callable = None
    track_cb: callable = None
    availability_cb: callable = None
    play_calls: list[str] = field(default_factory=list)
    pause_calls: int = 0
    stop_calls: int = 0
    resume_calls: int = 0

    def start(self):
        return True

    def stop(self):
        self.stop_calls += 1
        if self.playback_state_cb:
            self.playback_state_cb("idle")

    def shutdown(self):
        pass

    def pause(self):
        self.pause_calls += 1
        if self.playback_state_cb:
            self.playback_state_cb("paused")

    def resume(self):
        self.resume_calls += 1
        if self.playback_state_cb:
            self.playback_state_cb("playing")

    def play(self, uri, start_position=0.0):
        self.play_calls.append(uri)
        if self.playback_state_cb:
            self.playback_state_cb("playing")

    def next_track(self):
        pass

    def prev_track(self):
        pass

    def seek(self, pos):
        pass

    def set_volume(self, percent):
        pass

    def on_playback_state_change(self, cb):
        self.playback_state_cb = cb

    def on_track_change(self, cb):
        self.track_cb = cb

    def on_availability_change(self, cb):
        self.availability_cb = cb


@dataclass
class _FakeLibrary:
    recent: list = field(default_factory=list)

    def record_recent_track(self, track):
        self.recent.append(track)


@pytest.fixture
def app_with_music():
    app = build_test_app()
    backend = _FakeMpvBackend()
    library = _FakeLibrary()
    app.config = type("C", (), {"audio": type("AC", (), {"default_volume": 70})()})()
    app.register_integration("focus", setup=lambda a: setup_focus(a), teardown=lambda a: teardown_focus(a))
    app.register_integration(
        "music",
        setup=lambda a: setup_music(a, backend=backend, library=library),
        teardown=lambda a: teardown_music(a),
    )
    app.setup()
    yield app, backend, library
    app.stop()


def test_setup_initial_state(app_with_music):
    app, _, _ = app_with_music
    assert app.states.get_value("music.state") == "idle"
    assert app.states.get_value("music.backend_available") is True
    assert app.states.get_value("music.volume_percent") == 70


def test_play_acquires_focus_and_updates_state(app_with_music):
    app, backend, _ = app_with_music
    app.services.call("music", "play", PlayCommand(track_uri="local:t.mp3"))
    app.drain()

    assert backend.play_calls == ["local:t.mp3"]
    assert app.states.get_value("music.state") == "playing"
    assert app.states.get_value("focus.owner") == "music"


def test_pause_does_not_release_focus(app_with_music):
    app, _, _ = app_with_music
    app.services.call("music", "play", PlayCommand(track_uri="local:t.mp3"))
    app.drain()
    app.services.call("music", "pause", PauseCommand())
    app.drain()

    assert app.states.get_value("music.state") == "paused"
    assert app.states.get_value("focus.owner") == "music"  # still held


def test_resume_reacquires_focus(app_with_music):
    app, _, _ = app_with_music
    app.services.call("music", "play", PlayCommand(track_uri="local:t.mp3"))
    app.drain()
    app.services.call("music", "pause", PauseCommand())
    app.drain()
    # Simulate some other owner taking focus.
    request_focus(app, "call")
    app.drain()
    app.services.call("music", "resume", ResumeCommand())
    app.drain()

    assert app.states.get_value("focus.owner") == "music"


def test_stop_releases_focus(app_with_music):
    app, _, _ = app_with_music
    app.services.call("music", "play", PlayCommand(track_uri="local:t.mp3"))
    app.drain()
    app.services.call("music", "stop", StopCommand())
    app.drain()

    assert app.states.get_value("music.state") == "idle"
    assert app.states.get_value("focus.owner") is None


def test_focus_loss_auto_pauses_playback(app_with_music):
    app, backend, _ = app_with_music
    app.services.call("music", "play", PlayCommand(track_uri="local:t.mp3"))
    app.drain()

    app.bus.publish(AudioFocusLostEvent(owner="music", preempted_by="call"))
    app.drain()

    assert backend.pause_calls == 1
    assert app.states.get_value("music.state") == "paused"


def test_set_volume_updates_state(app_with_music):
    app, _, _ = app_with_music
    app.services.call("music", "set_volume", SetVolumeCommand(percent=50))
    assert app.states.get_value("music.volume_percent") == 50
```

- [ ] **Step 5.4: Run, commit**

```bash
uv run pytest tests/integrations/test_music.py -v
uv run black src/yoyopod/integrations/music/ tests/integrations/test_music.py
uv run ruff check src/yoyopod/integrations/music/ tests/integrations/test_music.py
uv run mypy src/yoyopod/integrations/music/
git add -A
git commit -m "feat(integrations/music): playback + library + focus-coordinated pause/resume

Acquires focus on play/resume; pause leaves focus held; stop releases.
AudioFocusLostEvent subscriber auto-pauses when another owner takes focus.
First integration to exercise the cross-domain focus pattern.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Delete `PlaybackCoordinator`

- [ ] **Step 6.1: Enumerate and delete**

```bash
grep -rn "PlaybackCoordinator" src/ tests/
git rm src/yoyopod/coordinators/playback.py
```

Update `src/yoyopod/coordinators/__init__.py` if it re-exports `PlaybackCoordinator`; remove that line.

Stub `src/yoyopod/app.py` references (they'll be removed in Plan 8).

- [ ] **Step 6.2: Run CI gate**

```bash
uv run python scripts/quality.py ci
```

- [ ] **Step 6.3: Commit**

```bash
git add -A
git commit -m "refactor(music): delete PlaybackCoordinator

Replaced by integrations/music/ setup + handlers.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Final verification

- [ ] **Step 7.1: Structure**

```bash
ls src/yoyopod/integrations/music/
ls src/yoyopod/backends/music/
```

Expected music integration: `__init__.py`, `commands.py`, `events.py`, `handlers.py`, `library.py`, `history.py`.
Backend: `__init__.py`, `mpv.py`, `process.py`, `ipc.py`, `models.py`.

- [ ] **Step 7.2: CI gate**

```bash
uv run python scripts/quality.py ci
```

Expected: all green.

---

## Definition of Done

- `integrations/music/` complete.
- `backends/music/` populated with relocated mpv code.
- Music commands exercise focus correctly (play/resume acquire; stop releases; focus loss auto-pauses).
- `PlaybackCoordinator` deleted.
- All tests green.

---

## What's next (Plan 6)

`call` — the biggest single migration. VoIPManager's 618 LOC split into `integrations/call/` with `handlers.py`, `messaging.py`, `voice_notes.py`, `history.py`. Uses focus (call pre-empts music).

---

*End of implementation plan.*
