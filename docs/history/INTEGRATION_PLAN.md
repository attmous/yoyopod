# YoYoPod VoIP + Local Music Integration Record

**Last updated:** 2026-04-07
**Status:** Historical implementation record, implemented on `main`

> Current note: this file explains the integration milestone that brought VoIP and local music into one app flow. It is useful for understanding how the current runtime came together, but it is not the primary source of truth for the current architecture. For current contracts, trust `docs/architecture/SYSTEM_ARCHITECTURE.md`, current subsystem docs, and the code under `yoyopod/`.

This document started as a plan and now serves as the completion record for the VoIP + local music integration that ships on `main`.

## What Is Implemented

- unified `YoyoPodApp` coordinator in `yoyopod/app.py`
- split orchestration models in `yoyopod/integrations/music/fsm.py` and `yoyopod/integrations/call/session.py`
- derived app runtime state in `yoyopod/core/app_state.py`
- music auto-pause on incoming call
- optional music auto-resume after call end
- screen stack transitions for incoming, outgoing, and active calls
- periodic now-playing refresh for progress updates
- simulation mode using the web server and keyboard input

## Current Implementation Map

### Coordinator

- `yoyopod/app.py`

Responsibilities:

- load config
- initialize display/input/screen infrastructure
- start VoIP and music backends
- register callbacks
- coordinate call interruption and resume behavior

### Music Layer

- `yoyopod/backends/music/mpv.py`
- `yoyopod/integrations/music/library.py`

Responsibilities:

- app-managed mpv lifecycle and JSON IPC
- playback control and property-event handling
- local playlist discovery, shuffle input, and recent-track integration

### VoIP Layer

- `yoyopod/voip/manager.py`

Responsibilities:

- Liblinphone lifecycle and iterate loop
- registration state tracking
- typed call/message event translation
- caller lookup and callback dispatch

### UI Layer

- `yoyopod/ui/display/`
- `yoyopod/ui/input/`
- `yoyopod/ui/screens/`

The older `display.py`, `screens.py`, `screen_manager.py`, and `input_handler.py` layout is no longer current.

## Integrated States

Key states used by the running app:

- `PLAYING`
- `PAUSED`
- `CALL_IDLE`
- `CALL_INCOMING`
- `CALL_OUTGOING`
- `CALL_ACTIVE`
- `PLAYING_WITH_VOIP`
- `PAUSED_BY_CALL`
- `CALL_ACTIVE_MUSIC_PAUSED`

See `yoyopod/integrations/music/fsm.py`, `yoyopod/integrations/call/session.py`, and `yoyopod/core/app_state.py` for the current transition and derived-state mapping.

## Incoming Call Flow

1. `VoIPManager` receives an incoming call event from the Liblinphone backend
2. `YoyoPodApp` pauses music if playback is active
3. state changes to `CALL_INCOMING`
4. `IncomingCallScreen` is pushed
5. answer/reject actions route back through `VoIPManager`
6. call end clears call screens and optionally resumes music

## Outgoing Call Flow

1. user navigates to contacts
2. `VoIPManager.make_call()` issues the SIP call through Liblinphone
3. outgoing and in-call screens are pushed as typed call state changes arrive
4. call end pops call screens and returns the app to the prior playback state

## Music Playback Flow

1. screen action triggers a music-backend command
2. `MpvBackend` receives push events from mpv over JSON IPC
3. `LocalMusicService` handles local playlist and filesystem browse concerns
4. callbacks refresh `NowPlayingScreen`
5. derived runtime state stays synchronized with actual playback state

## What Changed After The Original Plan

The original integration work predated later backend and UI refactors. The current code now uses:

- `InputManager` instead of `InputHandler`
- `Display` HAL instead of a single hardcoded display module
- split screen modules instead of one `screens.py`
- `MpvBackend` instead of the removed JSON-RPC music client

## Remaining Cleanup Outside Integration

The integration itself is done. Remaining repository work is separate:

- continue reducing stale historical docs
- migrate older demos and tests to current names and entry points
- keep semantic input handling on the semantic `Screen` contract; do not reintroduce button-named handlers
- reduce hardcoded hardware assumptions
