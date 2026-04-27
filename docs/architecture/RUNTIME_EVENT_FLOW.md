# Runtime Event Flow and Main-Thread Ownership

**Last updated:** 2026-04-21  
**Status:** Current implementation on `main`

This document maps how runtime events move through the current app and which layer owns each decision.

It is intentionally descriptive, not aspirational. If code and docs disagree, trust the code under `yoyopod/`.

## Big picture

The runtime has one main thread, centered on `YoyoPodApp`.

Background or device-facing code does not usually mutate UI state directly. Instead, it either:

1. schedules a main-thread task through `MainThreadScheduler`, or
2. publishes a typed event onto `Bus` from already-main-thread code.

`RuntimeLoopService.run_iteration()` then drains scheduler tasks first, drains bus events second, and lets the extracted runtime owners update FSM state, screens, and shared context.

## Dispatch rules

`Bus.publish()` is main-thread-only.

That means background timing follows one rule:

- backend callbacks schedule their handling through `MainThreadScheduler`
- scheduled handlers may then publish typed events onto `Bus`
- the next main-thread iteration drains scheduler tasks before it drains bus events

This is the real current behavior, not an implementation detail to ignore while debugging.

## Ownership map

### `YoyoPodApp`

Owns:
- process-wide composition root
- the single `Bus`
- the shared `MainThreadScheduler`
- shared managers, screens, FSM instances, and runtime services
- app-level event handlers that still write directly into `AppContext`
- the main-thread loop through `RuntimeLoopService`

`YoyoPodApp` is still the highest-level owner of runtime behavior. The extracted runtime owners reduce pressure on it, but it still carries cross-cutting responsibilities for network events, shutdown, recovery, and some voice-note updates.

### `RuntimeBootService`

Owns:
- boot-time wiring
- constructing `AppStateRuntime`
- constructing `CallRuntime` and `MusicRuntime`
- binding backend callbacks to runtime handlers and event publishers

This is where the app decides which backend signals become typed runtime events and which runtime helpers exist around the initialized managers and screens.

Canonical owner:
- `yoyopod/core/bootstrap/`

### `RuntimeLoopService`

Owns:
- loop cadence
- draining queued scheduler tasks and typed events
- calling recovery, power-runtime, shutdown, LVGL, and periodic screen refresh work in a stable order

This service is the bridge between queued background work and deterministic main-thread handling.
Current fairness protections are intentionally local to this service: each main-thread
iteration drains at most 4 queued scheduler tasks and 8 queued `Bus` items before it
continues into protected VoIP, LVGL, watchdog, and power spans, and pending generic
work keeps the loop on a 10 ms cadence instead of collapsing into a zero-sleep spin.

Canonical owner:
- `yoyopod/core/loop.py`

### `AppStateRuntime`

Owns:
- derived app-state calculation
- base UI state vs call/music overlay state
- shared derived state such as VoIP readiness and the latest power snapshot

It does not listen to events itself. It is the shared derived-state authority used by the runtime owners, not a bag of screen/backend/config references.

### `CallRuntime`

Owns:
- translating VoIP runtime events into call FSM transitions
- pausing and optionally resuming music around calls
- call-related screen pushes and cleanup
- VoIP readiness state in `AppStateRuntime`
- call-history persistence at call end

### `MusicRuntime`

Owns:
- translating music backend events into music FSM transitions
- refreshing now-playing UI
- recording recent tracks
- handling music backend availability loss

### `PowerRuntimeService`

Owns:
- applying new power snapshots to runtime and `AppContext`
- refreshing visible power-related UI
- running `PowerSafetyPolicy` and publishing resulting power events

### `ScreenManager`

Owns screen navigation plus the small screen-stack and render helpers used by the domain runtimes:
- push/pop call screens
- refresh visible screens when other runtime owners decide they should change

It is a UI helper and routing authority for screens, not a domain-behavior owner.

### `ScreenPowerService`

Owns:
- inactivity tracking
- screen wake/sleep
- screen-on runtime metrics
- temporary power overlays

It reacts to `ScreenChangedEvent`, `UserActivityEvent`, and low-battery events, but it does not own app navigation.

Canonical owner:
- `yoyopod/integrations/display/service.py`

### `RuntimeRecoveryService`

Owns:
- backend recovery attempts
- publishing recovery completion events

Canonical owner:
- `yoyopod/core/recovery.py`

### `integrations.power.PowerRuntimeService`

Owns:
- periodic power polling
- watchdog start/feed/disable cadence
- queueing PiSugar I/O off the main thread when needed

### `NetworkManager`

Owns:
- modem backend lifecycle
- publishing network events (`PPP`, signal, GPS, modem-ready)

Today it does **not** have a separate network runtime class. `YoyoPodApp` still handles those events directly through app-level subscriptions.

## Core event pipeline

## 1. Backend callback or worker action happens

Examples:
- `VoIPManager` reports incoming call or registration change
- `MpvBackend` reports track or playback-state change
- `PowerManager` returns a new snapshot during polling
- input hardware reports user activity
- `NetworkManager` publishes PPP, signal, or GPS events

## 2. The producer schedules onto main and publishes onto `Bus`

The common pattern is:
- boot wiring registers backend callbacks in `RuntimeBootService`
- those callbacks schedule handling through `app.scheduler.run_on_main(...)`
- the scheduled handler calls runtime or service methods on the main thread
- those handlers publish typed events onto `Bus` from the main thread

This means background threads can report state changes without touching UI objects directly.

## 3. `RuntimeLoopService` drains work on the main thread

`RuntimeLoopService.process_pending_main_thread_actions()` does two things in order:
- drains queued scheduler tasks from `MainThreadScheduler`
- drains queued typed events from `Bus`

Inside `run_iteration()`, that same drain step is fairness-bounded instead of trying to
empty every queue in one pass: the coordinator processes up to 4 queued callbacks and
8 queued typed events, records any deferred remainder in runtime diagnostics, and then
continues with the rest of the iteration. When backlog exists, the next loop wake uses
the dedicated pending-work cadence (`_PENDING_WORK_LOOP_INTERVAL_SECONDS`, currently
10 ms) so target hardware keeps yielding between iterations while still revisiting the
queued work quickly.

## 4. Event handlers mutate runtime state and UI

Handlers live in two places today:
- extracted runtime owners (`CallRuntime`, `MusicRuntime`, `PowerRuntimeService`)
- `YoyoPodApp`, `ScreenManager`, and runtime services for still-centralized concerns like network and screen-power bookkeeping

## Important flows

### Incoming call flow

1. `VoIPManager` invokes the callback registered by `RuntimeBootService.setup_voip_callbacks()`.
2. That callback schedules `CallRuntime.handle_incoming_call()` onto the main thread.
3. `CallRuntime` publishes `IncomingCallEvent` onto `Bus` as needed for other subscribers.
4. `RuntimeLoopService` drains the event on the main thread.
5. `CallRuntime.handle_incoming_call()`:
   - guards against duplicate handling
   - records an in-progress call session
   - pauses music if playback is active
   - transitions `CallFSM`
   - re-derives app state through `AppStateRuntime.sync_app_state()`
   - pushes `IncomingCallScreen`
   - starts the ring tone

Ownership: call behavior belongs to `CallRuntime`; derived app state belongs to `AppStateRuntime`; actual screen stack mutations happen through `ScreenManager`.

### Call state change flow

1. `VoIPManager` reports `CallState`.
2. `CallRuntime` publishes the call-domain events owned by `yoyopod/integrations/call/events.py`: `CallStateChangedEvent`, and `CallEndedEvent` for `RELEASED`.
3. The main-thread drain calls `CallRuntime.handle_call_state_change()` or `handle_call_ended()`.
4. Those methods update the call FSM, derived app state, call screens, call history, and optional music resume.

Notable ownership detail: `CallRuntime` directly decides music pause/resume around calls through `CallInterruptionPolicy`, so call orchestration currently owns one of the main cross-domain behaviors.

### Playback change flow

1. `MpvBackend` invokes callbacks registered in `RuntimeBootService.setup_music_callbacks()`.
2. `MusicRuntime.handle_track_change()` or `handle_playback_state_change()` publishes the music-domain events now owned by `yoyopod/integrations/music/events.py` when other subscribers need them.
3. Those callbacks arrive from the mpv IPC dispatch thread, so boot wiring schedules them onto the main thread before they publish onto `Bus`.
4. The main-thread drain calls `MusicRuntime.handle_track_change()` or `handle_playback_state_change()`.
5. `MusicRuntime` updates the music-domain `MusicFSM`, re-derives app state, records recents, and refreshes the now-playing screen.

Ownership: playback truth comes from the music backend; playback interpretation for app state belongs to `MusicRuntime` plus `AppStateRuntime`.

### Power snapshot flow

1. `PowerRuntimeService.poll_status()` fetches a snapshot from `PowerManager`.
2. It queues the completion back onto the main thread.
3. `PowerRuntimeService.handle_snapshot_updated()`:
   - stores the snapshot in `AppStateRuntime`
   - updates `AppContext`
   - refreshes visible UI when user-visible data changed
   - runs `PowerSafetyPolicy`
   - publishes policy outputs like low-battery warnings or graceful shutdown requests

Ownership: power telemetry, safety evaluation, and power availability handling are centralized in `PowerRuntimeService`, while overlay rendering and shutdown execution remain in `ScreenPowerService` and `core.shutdown.ShutdownLifecycleService`.

### Screen change and user activity flow

1. Input adapters fire semantic actions into `InputManager`.
2. `ScreenManager` dispatches the action to the active screen.
3. On LVGL paths, `ScreenManager` uses `action_scheduler` to queue the action onto the coordinator thread before it runs.
4. If navigation changes the visible route, `ScreenManager.on_screen_changed` schedules `ScreenChangedEvent` publication through the app scheduler.
5. `ScreenPowerService` and other app-level subscribers react to that event on the main thread.
6. `ScreenPowerService.handle_screen_changed_event()`:
   - syncs base UI state through `AppStateRuntime.sync_ui_state_for_screen()`
   - marks user activity so the display stays awake

Input activity separately publishes `UserActivityEvent`, which `ScreenPowerService` uses to track idle time and wake the display.

Ownership: route-change bookkeeping is split. `ScreenManager` knows when the route changed, the app scheduler republishes it, `ScreenPowerService` handles the event, and `AppStateRuntime` owns the resulting base UI state.

### Network status flow

1. `NetworkManager` uses the app-provided event publisher to schedule the typed network/location events from `yoyopod/integrations/network/events.py` and `yoyopod/integrations/location/events.py` onto the main thread and publish them to `Bus`.
2. `YoyoPodApp` subscribes to those events in its constructor.
3. App handlers call `_sync_network_context_from_manager()` or update `AppContext` directly.

Ownership: network state is still app-owned, not coordinator-owned. This is one of the clearest remaining gaps in the extraction.

### Recovery flow

1. `RuntimeLoopService` calls `RuntimeRecoveryService.attempt_manager_recovery()`.
2. VoIP recovery runs inline because it is a direct manager restart attempt.
3. Music recovery starts a background worker so mpv reconnect work does not block the coordinator loop.
4. Those workers schedule completion callbacks back onto the main thread.
5. The next coordinator drain runs the scheduled completion.
6. Recovery backoff state is finalized on the coordinator thread.

## Where state actually lives

### FSM state

Owned by:
- `yoyopod.integrations.music.fsm.MusicFSM`
- `yoyopod.integrations.call.session.CallFSM`
- `yoyopod.integrations.call.session.CallInterruptionPolicy`

### Derived app state

Owned by `AppStateRuntime.current_app_state`.

This state is derived from:
- call FSM state
- music FSM state
- `CallInterruptionPolicy.music_interrupted_by_call`
- base UI state
- `voip_ready`

### Shared user-facing runtime data

Mostly owned by `AppContext`.

`AppContext` is still the broad sink for:
- power telemetry
- network status
- VoIP summary data
- screen runtime metrics
- voice settings and talk summaries

This means runtime ownership is split between coordinator/FSM state and context snapshots for UI consumption.

## Known overloaded or confusing seams

### 1. `YoyoPodApp` is still both composition root and event handler hub

The app shell is thinner than before, but it still directly owns:
- network event handling
- screen-change event fan-out
- compatibility wrappers for older call sites
- voice-note update paths
- the root `Bus`

That makes it easy to reason about wiring, but it also means the app remains a hotspot.

### 2. Screen-state ownership is distributed

Route change handling crosses four layers:
- `ScreenManager`
- `YoyoPodApp._handle_screen_changed()`
- `ScreenPowerService.handle_screen_changed_event()`
- `AppStateRuntime.sync_ui_state_for_screen()`

This works, but it is not especially obvious. A future cleanup probably wants either a dedicated navigation/screen-state coordinator or a clearer single owner for route-to-state translation.

### 3. Network events are outside the coordinator split

`NetworkManager` already publishes typed events, but `YoyoPodApp` handles them directly instead of through an extracted coordinator. That leaves network as a parallel architecture beside call/playback/power.

### 4. `AppContext` is a broad shared sink

`AppContext` is practical, but ownership boundaries blur because many services write into it directly. It is easy to update, but harder to answer "who owns this field?" without tracing call sites.

### 5. Power behavior is split across multiple runtime services

`PowerRuntimeService` owns telemetry application and safety-policy evaluation, while `ScreenPowerService` owns overlays and `core.shutdown.ShutdownLifecycleService` owns actual shutdown execution. The division is workable, but a reader must cross service boundaries to understand the full low-battery path.

### 6. Event timing depends on scheduler backlog, not mixed bus semantics

All off-thread producers now go through the same `scheduler -> bus` handoff.

- background callbacks queue scheduler work
- scheduler work may publish typed events onto `Bus`
- bus events dispatch only after the scheduler slice for that iteration

If ordering looks inconsistent, check scheduler backlog first and bus backlog second.

## Source files to trust

- `yoyopod/app.py`
- `yoyopod/core/application.py`
- `yoyopod/core/bootstrap/`
- `yoyopod/core/loop.py`
- `yoyopod/core/recovery.py`
- `yoyopod/core/app_state.py`
- `yoyopod/integrations/call/runtime.py`
- `yoyopod/integrations/music/runtime.py`
- `yoyopod/integrations/power/service.py`
- `yoyopod/ui/screens/manager.py`
- `yoyopod/core/bus.py`
- `yoyopod/core/scheduler.py`
- `yoyopod/core/events.py`
- `yoyopod/integrations/network/manager.py`

## Bottom line

The current architecture is a partial extraction around a single coordinator-thread event loop.

- Call, playback, and power now have explicit runtime owners.
- Screen refresh and screen-power behavior are split helpers, not one unified screen owner.
- Network status still routes through `YoyoPodApp` directly.
- `AppStateRuntime` is the derived-state authority, but `AppContext` is still the broad user-facing state sink.

That is the truthful current model contributors should use when making the next small runtime-hardening changes.
