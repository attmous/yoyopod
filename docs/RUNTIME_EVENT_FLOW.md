# Runtime Event Flow and Coordinator Ownership

**Last updated:** 2026-04-16  
**Status:** Current implementation on `main`

This document maps how runtime events move through the current app and which layer owns each decision.

It is intentionally descriptive, not aspirational. If code and docs disagree, trust the code under `src/yoyopod/`.

## Big picture

The runtime has one coordinator thread, centered on `YoyoPodApp`.

Background or device-facing code does not usually mutate UI state directly. Instead, it either:

1. publishes a typed event onto `EventBus`, or
2. queues a main-thread callback through `RuntimeLoopService`

`RuntimeLoopService.run_iteration()` then drains that work on the coordinator thread and lets the extracted coordinators update FSM state, screens, and shared context.

## Dispatch rules

`EventBus.publish()` is synchronous when called on the coordinator thread and queued when called off-thread.

That means event timing depends on the publisher:

- power events published during coordinator-loop polling dispatch inline
- screen-change events published from `ScreenManager` dispatch inline
- VoIP call and registration events dispatch inline because Liblinphone iterate runs on the coordinator thread
- mpv events queue because mpv callbacks arrive on background IPC threads
- music recovery completion queues because it is published from a worker thread

This difference is real current behavior, not an implementation detail to ignore while debugging.

## Ownership map

### `YoyoPodApp`

Owns:
- process-wide composition root
- the single `EventBus`
- shared managers, screens, FSM instances, and runtime services
- app-level event handlers that still write directly into `AppContext`
- the coordinator-thread loop through `RuntimeLoopService`

`YoyoPodApp` is still the highest-level owner of runtime behavior. The extracted coordinators reduce pressure on it, but it still carries cross-cutting responsibilities for screen-change events, network events, shutdown, recovery, and some voice-note updates.

### `RuntimeBootService`

Owns:
- boot-time wiring
- constructing `CoordinatorRuntime`
- binding backend callbacks to event publishers
- binding extracted coordinators to the `EventBus`

This is where the app decides which backend signals become typed runtime events.

### `RuntimeLoopService`

Owns:
- loop cadence
- draining queued callbacks and typed events
- calling recovery, power, shutdown, LVGL, and periodic screen refresh work in a stable order

This service is the bridge between queued background work and deterministic main-thread handling.

### `CoordinatorRuntime`

Owns:
- shared references needed by extracted coordinators
- derived app-state calculation
- base UI state vs call/music overlay state

It does not listen to events itself. It is the shared state and derived-state authority used by the coordinators.

### `CallCoordinator`

Owns:
- translating VoIP runtime events into call FSM transitions
- pausing and optionally resuming music around calls
- call-related screen pushes and cleanup
- VoIP readiness state in `CoordinatorRuntime`
- call-history persistence at call end

### `PlaybackCoordinator`

Owns:
- translating music backend events into music FSM transitions
- refreshing now-playing UI
- recording recent tracks
- handling music backend availability loss

### `PowerCoordinator`

Owns:
- applying new power snapshots to runtime and `AppContext`
- refreshing visible power-related UI
- running `PowerSafetyPolicy` and publishing resulting power events

### `ScreenCoordinator`

Owns only small screen-stack and render helpers:
- push/pop call screens
- refresh visible screens when other coordinators decide they should change

It is a UI helper, not a routing authority.

### `ScreenPowerService`

Owns:
- inactivity tracking
- screen wake/sleep
- screen-on runtime metrics
- temporary power overlays

It reacts to `ScreenChangedEvent`, `UserActivityEvent`, and low-battery events, but it does not own app navigation.

### `RecoverySupervisor`

Owns:
- backend recovery attempts
- periodic power polling
- watchdog feeding
- publishing recovery completion events

### `NetworkManager`

Owns:
- modem backend lifecycle
- publishing network events (`PPP`, signal, GPS, modem-ready)

Today it does **not** have an extracted `NetworkCoordinator`. `YoyoPodApp` still handles those events directly.

## Core event pipeline

## 1. Backend callback or worker action happens

Examples:
- `VoIPManager` reports incoming call or registration change
- `MpvBackend` reports track or playback-state change
- `PowerManager` returns a new snapshot during polling
- input hardware reports user activity
- `NetworkManager` publishes PPP, signal, or GPS events

## 2. The producer publishes onto `EventBus`

The common pattern is:
- boot wiring registers backend callbacks in `RuntimeBootService`
- those callbacks call `publish_*()` methods on a coordinator or service
- `EventBus.publish()` dispatches immediately on the main thread or queues when called from another thread

This means background threads can report state changes without touching UI objects directly.

## 3. `RuntimeLoopService` drains work on the coordinator thread

`RuntimeLoopService.process_pending_main_thread_actions()` does two things in order:
- drains explicit queued callbacks from `_pending_main_thread_callbacks`
- drains queued typed events from `EventBus`

That drain happens inside the main loop before recovery/power refresh side effects finish the iteration.

## 4. Event handlers mutate runtime state and UI

Handlers live in two places today:
- extracted coordinators (`CallCoordinator`, `PlaybackCoordinator`, `PowerCoordinator`)
- `YoyoPodApp` and runtime services for still-centralized concerns like network and screen-power bookkeeping

## Important flows

### Incoming call flow

1. `VoIPManager` invokes the callback registered by `RuntimeBootService.setup_voip_callbacks()`.
2. That callback calls `CallCoordinator.publish_incoming_call()`.
3. `CallCoordinator` publishes `IncomingCallEvent` onto `EventBus`.
4. `RuntimeLoopService` drains the event on the coordinator thread.
5. `CallCoordinator.handle_incoming_call()`:
   - guards against duplicate handling
   - records an in-progress call session
   - pauses music if playback is active
   - transitions `CallFSM`
   - re-derives app state through `CoordinatorRuntime.sync_app_state()`
   - pushes `IncomingCallScreen`
   - starts the ring tone

Ownership: call behavior belongs to `CallCoordinator`; derived app state belongs to `CoordinatorRuntime`; actual screen stack mutations happen through `ScreenCoordinator`.

### Call state change flow

1. `VoIPManager` reports `CallState`.
2. `CallCoordinator.publish_call_state_events()` publishes `CallStateChangedEvent`, and `CallEndedEvent` for `RELEASED`.
3. The coordinator-thread drain calls `CallCoordinator.handle_call_state_change()` or `handle_call_ended()`.
4. Those methods update the call FSM, derived app state, call screens, call history, and optional music resume.

Notable ownership detail: `CallCoordinator` directly decides music pause/resume around calls through `CallInterruptionPolicy`, so call orchestration currently owns one of the main cross-domain behaviors.

### Playback change flow

1. `MpvBackend` invokes callbacks registered in `RuntimeBootService.setup_music_callbacks()`.
2. `PlaybackCoordinator.publish_track_change()` or `publish_playback_state_change()` publishes typed events.
3. Those callbacks arrive from the mpv IPC dispatch thread, so the `EventBus` queues them for the coordinator thread.
4. The coordinator-thread drain calls `PlaybackCoordinator.handle_track_change()` or `handle_playback_state_change()`.
5. `PlaybackCoordinator` updates `MusicFSM`, re-derives app state, records recents, and refreshes the now-playing screen.

Ownership: playback truth comes from the music backend; playback interpretation for app state belongs to `PlaybackCoordinator` plus `CoordinatorRuntime`.

### Power snapshot flow

1. `RecoverySupervisor.poll_power_status()` fetches a snapshot from `PowerManager`.
2. It calls `PowerCoordinator.publish_snapshot()` and, on availability transitions, `publish_availability_change()`.
3. `PowerCoordinator.handle_snapshot_updated()`:
   - stores the snapshot in `CoordinatorRuntime`
   - updates `AppContext`
   - refreshes visible UI when user-visible data changed
   - runs `PowerSafetyPolicy`
   - republishes policy outputs like low-battery warnings or graceful shutdown requests

Ownership: power telemetry and safety evaluation are centralized in `PowerCoordinator`, but overlay rendering and shutdown execution remain in `ScreenPowerService` and `ShutdownLifecycleService`.

### Screen change and user activity flow

1. Input adapters fire semantic actions into `InputManager`.
2. `ScreenManager` dispatches the action to the active screen.
3. On LVGL paths, `ScreenManager` uses `action_scheduler` to queue the action onto the coordinator thread before it runs.
4. If navigation changes the visible route, `ScreenManager.on_screen_changed` calls `YoyoPodApp._handle_screen_changed()`.
5. That method publishes `ScreenChangedEvent`.
6. `ScreenPowerService.handle_screen_changed_event()`:
   - syncs base UI state through `YoyoPodApp._sync_screen_changed()` and `CoordinatorRuntime.sync_ui_state_for_screen()`
   - marks user activity so the display stays awake

Input activity separately publishes `UserActivityEvent`, which `ScreenPowerService` uses to track idle time and wake the display.

Ownership: route-change bookkeeping is split. `ScreenManager` knows when the route changed, `YoyoPodApp` republishes it, `ScreenPowerService` handles the event, and `CoordinatorRuntime` owns the resulting base UI state.

### Network status flow

1. `NetworkManager` publishes network events directly to `EventBus`.
2. `YoyoPodApp` subscribes to those events in its constructor.
3. App handlers call `_sync_network_context_from_manager()` or update `AppContext` directly.

Ownership: network state is still app-owned, not coordinator-owned. This is one of the clearest remaining gaps in the extraction.

### Recovery flow

1. `RuntimeLoopService` calls `RecoverySupervisor.attempt_manager_recovery()`.
2. VoIP recovery runs inline because it is a direct manager restart attempt.
3. Music recovery starts a background worker so mpv reconnect work does not block the coordinator loop.
4. That worker publishes `RecoveryAttemptCompletedEvent`.
5. The event queues onto `EventBus` because it was published off-thread.
6. The next coordinator drain calls `RecoverySupervisor.handle_recovery_attempt_completed_event()`.
7. Recovery backoff state is finalized on the coordinator thread.

## Where state actually lives

### FSM state

Owned by:
- `MusicFSM`
- `CallFSM`
- `CallInterruptionPolicy`

### Derived app state

Owned by `CoordinatorRuntime.current_app_state`.

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
- the root `EventBus`

That makes it easy to reason about wiring, but it also means the app remains a hotspot.

### 2. Screen-state ownership is distributed

Route change handling crosses four layers:
- `ScreenManager`
- `YoyoPodApp._handle_screen_changed()`
- `ScreenPowerService.handle_screen_changed_event()`
- `CoordinatorRuntime.sync_ui_state_for_screen()`

This works, but it is not especially obvious. A future cleanup probably wants either a dedicated navigation/screen-state coordinator or a clearer single owner for route-to-state translation.

### 3. Network events are outside the coordinator split

`NetworkManager` already publishes typed events, but `YoyoPodApp` handles them directly instead of through an extracted coordinator. That leaves network as a parallel architecture beside call/playback/power.

### 4. `AppContext` is a broad shared sink

`AppContext` is practical, but ownership boundaries blur because many services write into it directly. It is easy to update, but harder to answer "who owns this field?" without tracing call sites.

### 5. Power behavior is split across multiple runtime services

`PowerCoordinator` owns telemetry application and safety-policy evaluation, while `ScreenPowerService` owns overlays and `ShutdownLifecycleService` owns actual shutdown execution. The division is workable, but a reader must cross service boundaries to understand the full low-battery path.

### 6. Event timing depends on the source thread

The same `EventBus` is used for both inline and deferred dispatch.

- VoIP and power flows are mostly synchronous once they enter the coordinator loop
- mpv and recovery flows are deferred until the next event drain
- screen actions may run directly or through the LVGL action scheduler before the route-change event is published

If ordering looks inconsistent, this is usually the first place to check.

## Source files to trust

- `src/yoyopod/app.py`
- `src/yoyopod/runtime/boot.py`
- `src/yoyopod/runtime/loop.py`
- `src/yoyopod/coordinators/runtime.py`
- `src/yoyopod/coordinators/call.py`
- `src/yoyopod/coordinators/playback.py`
- `src/yoyopod/coordinators/power.py`
- `src/yoyopod/coordinators/screen.py`
- `src/yoyopod/event_bus.py`
- `src/yoyopod/events.py`
- `src/yoyopod/network/manager.py`

## Bottom line

The current architecture is a partial extraction around a single coordinator-thread event loop.

- Call, playback, and power now have explicit coordinators.
- Screen refresh and screen-power behavior are split helpers, not one unified screen owner.
- Network status still routes through `YoyoPodApp` directly.
- `CoordinatorRuntime` is the derived-state authority, but `AppContext` is still the broad user-facing state sink.

That is the truthful current model contributors should use when making the next small runtime-hardening changes.
