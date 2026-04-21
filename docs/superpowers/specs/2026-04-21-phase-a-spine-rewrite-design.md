# Phase A — Spine Rewrite (State Store + Typed Bus + Service Registry) — Design

**Date:** 2026-04-21
**Owner:** Moustafa
**Status:** Awaiting review
**Review note (2026-04-21):** Current `main` already includes the CLI polish merge (`5e2640f`) and already exposes a compatibility `src/yoyopod/core/` package. Execute Phase A against that baseline: validate the CLI rename instead of replaying it, and repurpose the existing `core/` package rather than creating a parallel one.
**Precedes:** Phase B (HAL consolidation, formerly Phase C — renumbered when the original Phase B was absorbed into Phase A)
**Supersedes:** `docs/RUNTIME_EVENT_FLOW.md` (the old coordinator/FSM event flow becomes historical)

---

## 1. Goals

The current YoyoPod spine exhibits a pseudo-reactive anti-pattern: 9 of 14 event-bus events are published and subscribed by the **same coordinator class**, so the bus is functioning as a thread-marshaller pretending to be pub/sub. One incoming-call event traverses 7–8 hops (`LiblinphoneBackend → VoIPManager → event_scheduler → callback list → CallCoordinator.publish → EventBus → CallCoordinator.handle`) before any real work runs. Call state lives in 5 places simultaneously — Liblinphone native, `VoIPManager`, `CallFSM`, `CoordinatorRuntime`, and screens — with manual sync bookkeeping in between.

Against Moustafa's maintainability rule ((1) reduce the layers a reader traces, (2) reduce the state a reader holds in their head), both axes are over budget.

Phase A rewrites the spine to a single consistent model inspired by Home Assistant's architecture (typed event bus + entity state store + typed service registry), adapted in-process for a Pi Zero 2W.

**Success criteria:**

- One place to answer "where is X's state?" — the state store (`app.states`).
- One mechanism to trigger an action — the service registry (`app.services.call`).
- One mechanism to react to signals — the event bus (`app.bus.subscribe`).
- Every event on the bus has a real reason to be there (never pub-to-self).
- `CallState` change path: ≤5 hops, top-down readable.
- All state transitions recorded to `events.jsonl` as structured JSON for LLM-driven debugging.
- `app.py` shrinks from ~685 LOC to ~150 LOC.
- The entire "coordinator" concept (CallCoordinator, PlaybackCoordinator, ScreenCoordinator, PowerCoordinator, CoordinatorRuntime, AppRuntimeState) deleted.
- MusicFSM, CallFSM, CallInterruptionPolicy deleted.
- VoIPManager's 4 private callback lists deleted.
- Adding a new cross-cutting observer (LED status, cloud telemetry, metrics) = one new file, zero changes to existing integrations.

---

## 2. Scope

**In scope:**

- Build new `core/` primitives: `Bus`, `States`, `Services`, `Scheduler`, and `App` shell.
- Rewrite the spine under `integrations/` in HA-style: 11 integration folders, each with a `setup(app)` function that subscribes to events, registers commands, and mirrors backend state into the store.
- Delete all FSMs, coordinators, derived-state enums, runtime services (boot/loop/shutdown/eventwiring), AppContext.
- Split VoIPManager into `integrations/call/` (handlers, messaging, voice notes, history).
- Fold PowerManager, NetworkManager, CloudManager, PeopleDirectory, LocalMusicService, VoiceRuntimeCoordinator, ScreenPowerService into their respective integrations.
- Separate GPS from network into a new `location` integration.
- Add an `audio focus` integration (replaces CallInterruptionPolicy; arbiter pattern borrowed from Android's AudioFocus).
- Add a `diagnostics` integration that owns the structured event log, responsiveness watchdog, and snapshot command.
- Touch up `ScreenManager` + all 17 screens to read state via `app.states.get(...)` and trigger actions via `app.services.call(...)` instead of holding direct manager references.
- Validate the merged CLI polish baseline and clean only any remaining post-merge `yoyoctl` stragglers (for example live docs/skills or new regressions caught by `tests/test_no_yoyoctl_references.py`).
- Rewrite tests for new primitives and integrations; rewrite orchestration tests as state-store + event-trace assertions.

**Out of scope (deferred to later phases):**

- Display/input HAL consolidation and LVGL binding changes (Phase C).
- Runtime service rethink beyond what Phase A already collapses (Phase B finishes the job if anything remains).
- Screen rendering changes beyond the read-paths/action-paths touch-up.
- Config model changes (`src/yoyopod/config/models/` package untouched).
- Backend adapter reshaping beyond the new observer-via-scheduler contract (Liblinphone binding, mpv IPC, PiSugar socket, modem serial all keep their current internal structure).
- Moving to asyncio.
- Process-based architecture (Mycroft-style separate services).

---

## 3. Target architecture

### 3.1 Three primitives

```
app.bus                 ← observations: "X happened"
app.states              ← state of record: "X is currently Y"
app.services            ← commands: "please do X"
```

Plus `app.scheduler` as a main-thread task queue for background-to-main marshalling.

### 3.2 Directory layout

```
src/yoyopod/
├── app.py                         # ~150 LOC — constructs core, loads integrations, runs main loop
├── main.py                        # entry point
├── core/
│   ├── __init__.py
│   ├── app_shell.py               # YoyoPodApp class
│   ├── bus.py                     # Bus (main-thread-only, strict)
│   ├── states.py                  # States (entity store)
│   ├── services.py                # Services (command registry)
│   ├── scheduler.py               # MainThreadScheduler
│   ├── events.py                  # StateChangedEvent + cross-cut event types
│   └── testing.py                 # build_test_app, assert_events_contain, drain_all
├── integrations/
│   ├── call/
│   │   ├── __init__.py            # setup(app)
│   │   ├── events.py              # CallIncomingEvent, MessageReceivedEvent, ...
│   │   ├── commands.py            # DialCommand, AnswerCommand, HangupCommand, ...
│   │   ├── handlers.py            # _handle_backend_state, etc.
│   │   ├── messaging.py           # text message handling
│   │   ├── voice_notes.py         # voice-note record/play
│   │   └── history.py             # call history store
│   ├── music/
│   │   ├── __init__.py
│   │   ├── events.py
│   │   ├── commands.py            # PlayCommand, PauseCommand, SeekCommand, ...
│   │   ├── handlers.py
│   │   └── library.py             # playlists, recent tracks
│   ├── power/                     # battery, charging, RTC, watchdog, shutdown
│   ├── network/                   # cellular, PPP, signal
│   ├── location/                  # GPS (split out of network)
│   ├── focus/                     # AudioFocus arbiter
│   ├── cloud/                     # MQTT telemetry, HTTPS sync, remote commands
│   ├── contacts/                  # people directory, SIP→name lookup
│   ├── voice/                     # STT, TTS, voice commands, Ask screen backend
│   ├── screen/                    # display on/off, brightness, idle timeout
│   ├── diagnostics/               # event log, responsiveness watchdog, snapshots
│   └── recovery/                  # backend recovery supervision
├── backends/                      # adapters to external systems (adapter layer only)
│   ├── voip/                      # LiblinphoneBackend + binding
│   ├── music/                     # MpvBackend + process + ipc
│   ├── power/                     # PiSugarBackend + watchdog
│   ├── network/                   # modem AT, PPP, transport
│   ├── location/                  # GPS backend
│   └── voice/                     # STT engines, TTS engines
└── ui/                            # screens + display/input (unchanged structurally for Phase A)
```

### 3.3 Threading model

One main thread runs the app loop:

```python
while running:
    scheduler.drain()     # run queued main-thread tasks (backends → handlers)
    bus.drain()           # dispatch events published during scheduler tasks
    ui.tick()             # render / input poll
    time.sleep(SLEEP_SECONDS)
```

Rule: **the bus is main-thread-only.** `bus.publish()` from any other thread raises in strict mode. Backend callbacks schedule main-thread tasks via `scheduler.run_on_main(fn)`; those tasks then safely publish events and mutate state.

This eliminates the bus's current dual semantics (sync-from-main, queued-from-other) and the re-entrancy edge case where a handler publishing during dispatch recursively re-enters `_dispatch`.

### 3.4 Canonical flow (incoming call pauses music)

```
Liblinphone native callback (bg thread)
  → LiblinphoneBackend.on_native_event(ev)       [bg thread]
  → scheduler.run_on_main(lambda: app.bus.publish(CallBackendStateEvent("connected", caller)))
  → [main loop drains scheduler]
  → bus.publish(CallBackendStateEvent(...))      [main thread]
  → [bus drains]
  → handlers.handle_backend_state(app, ev)       [main thread]
       ├─ app.states.set("call.state", "active", attrs={"caller": ...})
       │    └─ auto-fires StateChangedEvent (bus drains before tick ends)
       ├─ app.services.call("focus", "request", RequestFocusCommand(owner="call"))
       │    └─ focus integration publishes AudioFocusLostEvent(owner="music", preempted_by="call")
       │    └─ music integration subscriber: backend.pause()
       │    └─ mpv fires "paused" → scheduler → bus → states.set("music.state", "paused")
       └─ (done)
UI screens subscribed to StateChangedEvent redraw as relevant state keys change.
```

Hops from native callback to final state: 5. Every hop a direct call or a single queue. No pub-to-self. No bidirectional callback web.

---

## 4. Core primitives

### 4.1 Bus (`core/bus.py`)

```python
class Bus:
    """Typed, main-thread-only, strict event bus."""

    def __init__(self, main_thread_id: int) -> None: ...

    def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> None: ...

    def publish(self, event: Any) -> None:
        """Publish an event. Raises if called from a non-main thread."""

    def drain(self, limit: int | None = None) -> int:
        """Dispatch queued events to subscribers. Returns count dispatched."""

    def pending_count(self) -> int: ...
```

- `publish()` queues the event on an internal deque; `drain()` dispatches.
- Dispatch iterates subscribers registered for the exact event type or any base class (isinstance-based).
- Exceptions in a handler are logged (loguru error) and recorded as an error event in the structured log; dispatch continues to remaining handlers. Strict mode can be enabled to re-raise (used in tests).

### 4.2 States (`core/states.py`)

```python
@dataclass(frozen=True, slots=True)
class StateValue:
    value: Any
    attrs: dict[str, Any]
    last_changed_at: float

class States:
    def __init__(self, bus: Bus) -> None: ...

    def set(self, entity: str, value: Any, attrs: dict[str, Any] | None = None) -> None:
        """Set an entity's value. No-op if unchanged. Fires StateChangedEvent on change."""

    def get(self, entity: str) -> StateValue | None: ...

    def get_value(self, entity: str, default: Any = None) -> Any:
        """Convenience: return .value or default."""

    def all(self) -> dict[str, StateValue]:
        """Snapshot of the full state store (used by diagnostics)."""

    def has(self, entity: str) -> bool: ...
```

Rules:
- Entity keys are `domain.entity_name` (snake_case). See §5 for the catalog.
- `set()` is a no-op when the new `(value, attrs)` equals the current `(value, attrs)` — prevents no-op `StateChangedEvent` spam.
- `set()` auto-publishes `StateChangedEvent(entity, old, new, attrs, last_changed_at)`.
- State is in-memory only. Persistence (call history, contacts, etc.) is the owning integration's job via its own store.
- High-frequency ephemeral values (e.g., music position, call duration-in-progress) do **not** live in the state store. They are direct reads on the owning integration's backend.

### 4.3 Services (`core/services.py`)

```python
Handler = Callable[[Any], Any]

class Services:
    def __init__(self, bus: Bus, diagnostics_log: DiagnosticsLog | None = None) -> None: ...

    def register(self, domain: str, service: str, handler: Handler) -> None: ...

    def call(self, domain: str, service: str, data: Any = None) -> Any:
        """Invoke a registered service synchronously on the main thread.
        Logs the invocation to the event log. Raises if unregistered."""

    def registered(self) -> list[tuple[str, str]]:
        """List (domain, service) pairs (for diagnostics)."""
```

Rules:
- `data` is a typed frozen dataclass per command, defined in the owning integration's `commands.py`.
- Handlers run synchronously on the main thread. Slow work (e.g., file I/O during voice-note save) is offloaded by the handler itself (a background thread or a scheduler task) — the service call returns quickly.
- Return is typically `None`. Query-style services (e.g., `contacts.get_by_address`) may return typed data.
- Errors raise to the caller; the event log records both the call and the exception.

### 4.4 Scheduler (`core/scheduler.py`)

```python
class MainThreadScheduler:
    def __init__(self, main_thread_id: int) -> None: ...

    def run_on_main(self, fn: Callable[[], None]) -> None:
        """Schedule fn to run on the main thread. Runs immediately if called on main."""

    def drain(self, limit: int | None = None) -> int:
        """Run queued tasks in FIFO order."""

    def pending_count(self) -> int: ...
```

Rules:
- Thread-safe queue (`queue.Queue`).
- Called from backend threads with a closure: `scheduler.run_on_main(lambda: handle(...))`.
- Drained once per main-loop tick.
- Exceptions in a scheduled task are logged; drain continues to remaining tasks.

### 4.5 App shell (`core/app_shell.py`)

```python
class YoyoPodApp:
    bus: Bus
    states: States
    services: Services
    scheduler: MainThreadScheduler
    config: YoyoPodConfig

    def __init__(self, config_dir: str = "config", simulate: bool = False) -> None: ...

    def setup(self) -> None:
        """Load config, init core primitives, call setup(self) on every integration."""

    def run(self) -> None:
        """Main loop: drain scheduler, drain bus, tick UI, sleep, repeat."""

    def stop(self) -> None:
        """Call teardown() on each integration in reverse registration order. Idempotent."""

    def drain(self) -> None:
        """Test-friendly composite: drain scheduler then bus until both quiescent.
        Called by unit/e2e tests between stimulus and assertion; not used in production run loop."""

    def recent_events(self, count: int = 500) -> list[LogEntry]:
        """Return the last N entries from the diagnostics ring buffer.
        Convenience accessor; delegates to the diagnostics integration."""
```

Integrations register their `setup(app)` in a known order (see §11.2). The app shell does nothing domain-specific; all behavior lives in integrations.

**Dependency injection pattern.** Every integration's `setup(app)` receives the `app` instance as its only argument. Integrations pull their dependencies (`bus`, `states`, `services`, `scheduler`, `config`, plus any other integration's state via `app.states.get(...)`) from `app`. No separate DI container, no constructor-graph wiring, no service locator. The `app` object is the single ambient dependency. This matches HA's `hass` pattern one-to-one.

---

## 5. Entity catalog

~22 entities total. Values are authoritative; screens and other observers read these.

| Entity | Value domain | Attrs | Owner |
|---|---|---|---|
| `call.state` | `idle | incoming | outgoing | active` | `caller`, `call_id` | call |
| `call.caller` | `CallerInfo | None` | (embedded in `call.state.attrs`; may split if redundant) | call |
| `call.muted` | `bool` | — | call |
| `call.registration` | `none | progress | ok | failed` | `reason` | call |
| `call.history_unread_count` | `int` | `recent_preview` | call |
| `music.state` | `idle | playing | paused` | `reason` | music |
| `music.track` | `Track | None` | `title`, `artist`, `duration_seconds`, `path` | music |
| `music.volume_percent` | `int 0..100` | — | music |
| `music.backend_available` | `bool` | `reason` | music |
| `power.battery_percent` | `int 0..100 | None` | `voltage_volts`, `temperature_celsius` | power |
| `power.charging` | `bool` | — | power |
| `power.external_power` | `bool` | — | power |
| `power.backend_available` | `bool` | `reason` | power |
| `network.cellular_registered` | `bool` | `carrier`, `network_type` | network |
| `network.signal_bars` | `int 0..5 | None` | `csq` | network |
| `network.ppp_up` | `bool` | `reason` | network |
| `location.fix` | `LocationFix | None` | `lat`, `lng`, `altitude`, `speed_mps`, `last_fix_at` | location |
| `location.backend_available` | `bool` | `reason` | location |
| `focus.owner` | `call | music | voice | None` | `preempted_by` | focus |
| `cloud.mqtt_connected` | `bool` | `reason`, `last_sync_at` | cloud |
| `screen.awake` | `bool` | — | screen |
| `screen.brightness_percent` | `int 0..100` | — | screen |
| `voice.state` | `idle | listening | thinking | responding` | `transcript`, `response` | voice |
| `contacts.people_count` | `int` | — | contacts |
| `contacts.unread_voice_notes` | `int` | `by_address` | contacts |

**Not in the state store** (direct reads on the owning integration):
- `music.position_seconds` — changes 1×/sec during playback; would flood the event log.
- `call.duration_seconds` — same reason.
- Signal polling deltas before they cross a "bars" threshold.

Naming conventions:
- `domain.entity_name` snake_case.
- Booleans: adjective / past-tense (`charging`, `muted`, `ppp_up`).
- Percentages: `_percent` suffix.
- Durations: `_seconds` suffix.
- Timestamps: `_at` suffix (unix-time float or ISO string as documented per-entity).
- Counts: `_count` suffix.

---

## 6. Event catalog rules

### 6.1 Universal: `StateChangedEvent`

```python
@dataclass(frozen=True, slots=True)
class StateChangedEvent:
    entity: str
    old: StateValue | None
    new: StateValue
```

Auto-published on every effective `states.set(...)`. Subscribers filter by entity prefix:

```python
def on_state_changed(ev):
    if ev.entity.startswith("call."):
        ...
```

This single event type covers ~80% of "refresh UI when X changes" subscriptions.

### 6.2 One-off domain events (per-type, frozen dataclasses)

Per-domain `events.py` files define events that are **not** state changes — they carry a distinct payload shape.

| Event | Origin | Purpose |
|---|---|---|
| `CallIncomingEvent(caller_address, caller_name)` | call | New incoming call arrived |
| `CallBackendStateEvent(state, caller_address, reason)` | call | Raw Liblinphone state (internal, used by handler) |
| `MessageReceivedEvent(sender, text, timestamp, message_id)` | call | Inbound text message |
| `MessageDeliveryChangedEvent(message_id, state)` | call | Delivery receipt |
| `VoiceNoteCompletedEvent(draft)` | call | Recorded voice note ready to send |
| `MusicTrackChangedEvent(track)` | music | (Alternative to state change; may be collapsed into state) |
| `UserActivityEvent(action_name)` | screen | User input detected (keep-awake trigger) |
| `BackendStoppedEvent(domain, reason)` | any | Backend crashed or shut down |
| `RecoveryAttemptedEvent(domain, success)` | recovery | Recovery attempt result |
| `AudioFocusGrantedEvent(owner, preempted)` | focus | Focus awarded |
| `AudioFocusLostEvent(owner, preempted_by)` | focus | Focus lost |
| `ShutdownRequestedEvent(reason, delay_seconds)` | power/cloud | Graceful shutdown requested |
| `ResponsivenessLagEvent(duration_ms, context)` | diagnostics | Main loop tick exceeded threshold |
| `LifecycleEvent(integration, phase)` | core | Integration setup/teardown boundaries |

Estimated total: ~15 event types plus the universal `StateChangedEvent`.

### 6.3 Rules

- **Prefer state.** If something can be modeled as a state change, don't create a per-type event.
- **Frozen dataclasses** with `slots=True` for every event — immutable, typed, cheap.
- **No commands via events.** If the intent is "please do X," register it as a service and call it. Events are observations, not requests.
- **No event-to-event forwarding.** A subscriber that only publishes another event should be collapsed.

---

## 7. Command API (services)

### 7.1 Command dataclasses

Each integration defines its commands in `commands.py`:

```python
@dataclass(frozen=True, slots=True)
class PlayCommand:
    track_uri: str
    start_position_seconds: float = 0.0
```

### 7.2 Registration and invocation

```python
# during integrations/music/__init__.py :: setup(app)
app.services.register("music", "play", lambda cmd: _handle_play(app, cmd))

# during another integration's handler
app.services.call("music", "play", PlayCommand(track_uri="local:file:song.mp3"))
```

### 7.3 Command catalog (approximate; final set emerges per integration)

**call:** `dial`, `answer`, `hangup`, `reject`, `mute`, `unmute`, `send_message`, `start_voice_note`, `stop_voice_note`, `send_voice_note`, `cancel_voice_note`, `play_voice_note`, `mark_voice_notes_seen`
**music:** `play`, `pause`, `resume`, `stop`, `next`, `prev`, `seek`, `set_volume`
**power:** `shutdown`, `reboot`, `set_watchdog`, `set_rtc_alarm`, `disable_rtc_alarm`, `sync_rtc_to_system`, `sync_rtc_from_system`
**network:** `enable_ppp`, `disable_ppp`, `refresh_signal`, `set_apn`
**location:** `request_fix`, `enable_gps`, `disable_gps`
**focus:** `request`, `release`
**screen:** `wake`, `sleep`, `set_brightness`, `set_idle_timeout`
**voice:** `start_listening`, `stop_listening`, `say`
**cloud:** `sync_now`, `publish_telemetry`
**contacts:** `lookup_by_address`, `reload`, `mark_voice_notes_seen`
**diagnostics:** `snapshot`, `mark_user_activity`

Total ≈ 40 commands. Exact set finalised per integration during implementation.

---

## 8. Observability

### 8.1 Structured event log

- File: `~/.yoyopod/logs/events.jsonl`.
- Rolling: 5 files × 5 MB = 25 MB total ceiling.
- One JSON object per line.
- Four `kind` values: `event`, `command`, `error`, `lifecycle`.

Sample:
```json
{"ts":"2026-04-21T10:15:32.123Z","kind":"event","type":"StateChangedEvent","payload":{"entity":"call.state","old":"idle","new":"incoming","attrs":{"caller":"sip:bob@..."}}}
{"ts":"2026-04-21T10:15:32.125Z","kind":"command","domain":"focus","service":"request","data":{"owner":"call"}}
{"ts":"2026-04-21T10:15:32.140Z","kind":"error","handler":"music.on_focus_lost","exc":"RuntimeError: mpv not connected"}
{"ts":"2026-04-21T10:15:32.160Z","kind":"lifecycle","integration":"call","phase":"setup_complete"}
```

### 8.2 Responsibility

The `diagnostics` integration:
- Subscribes to `StateChangedEvent` and every one-off event type.
- Is wired into `services.call()` to log every command invocation.
- Catches handler exceptions from `bus.drain()` and `scheduler.drain()` and records them.
- Owns event-log file rotation.
- Measures `scheduler.drain() + bus.drain()` duration per tick; emits `ResponsivenessLagEvent` when over threshold (default 100 ms, configurable).
- Exposes the `diagnostics.snapshot` service (see below).

### 8.3 Snapshot command

```python
@dataclass(frozen=True, slots=True)
class SnapshotCommand:
    reason: str
```

`app.services.call("diagnostics", "snapshot", SnapshotCommand(reason="bug_report"))` writes `~/.yoyopod/logs/snapshot-{ts}-{reason}.json`:

```json
{
  "ts": "2026-04-21T10:15:32Z",
  "reason": "bug_report",
  "states": { "call.state": {"value": "active", "attrs": {...}, "last_changed_at": 1234.56}, ... },
  "subscriptions": { "StateChangedEvent": 6, "CallIncomingEvent": 2, ... },
  "services": ["call.dial", "call.answer", "music.play", ...],
  "tick_stats_last_100": {
    "drain_ms_p50": 2.1,
    "drain_ms_p99": 18.4,
    "queue_depth_max": 12
  },
  "recent_events_tail_path": "events.jsonl",
  "recent_events_tail_lines": 500
}
```

### 8.4 Cloud observability

The `cloud` integration subscribes to `StateChangedEvent` (filtered by what the cloud cares about) and publishes to MQTT. This requires zero changes to other integrations — the whole point of A+3.

### 8.5 loguru

Retained for human-readable `info`/`warn`/`error` lines. Complementary to the structured event log, not replaced. Rule: loguru for human context ("registering with SIP server..."), event log for machine-consumable state transitions.

---

## 9. Fate of existing classes

### 9.1 Deleted outright

| Class / module | File(s) | Why |
|---|---|---|
| `MusicFSM` | `src/yoyopod/fsm.py` | 3 states, 3 triggers; replaced by `app.states.get("music.state")` |
| `CallFSM` | `src/yoyopod/fsm.py` | Replaced by `app.states.get("call.state")` |
| `CallInterruptionPolicy` | `src/yoyopod/fsm.py` | Replaced by `focus` integration's AudioFocus arbiter |
| `AppRuntimeState` enum | `src/yoyopod/coordinators/runtime.py` | 18 cross-product values become direct state reads per entity |
| `CoordinatorRuntime` | `src/yoyopod/coordinators/runtime.py` | Aggregate view replaced by `app.states.all()` + direct reads |
| `CallCoordinator` | `src/yoyopod/coordinators/call.py` | Logic into `integrations/call/handlers.py` |
| `PlaybackCoordinator` | `src/yoyopod/coordinators/playback.py` | Logic into `integrations/music/handlers.py` |
| `ScreenCoordinator` | `src/yoyopod/coordinators/screen.py` | Push/pop into `ScreenManager`; refresh-if-visible becomes subscription |
| `PowerCoordinator` | `src/yoyopod/coordinators/power.py` | Into `integrations/power/handlers.py` |
| `RuntimeBootService` | `src/yoyopod/runtime/` | Replaced by `YoyoPodApp.setup()` calling each integration's `setup(app)` |
| `RuntimeLoopService` | `src/yoyopod/runtime/` | Replaced by 4-line loop in `YoyoPodApp.run()` |
| `ShutdownLifecycleService` | `src/yoyopod/runtime/` | Replaced by `YoyoPodApp.stop()` calling integration `teardown(app)` |
| `RuntimeEventWiring` | `src/yoyopod/runtime/event_wiring.py` | Each integration wires itself in its own `setup()` |
| `AppContext` | `src/yoyopod/app_context.py` | Screens read via `app.states.get(...)`; config via `app.config` |

All of `src/yoyopod/coordinators/` and `src/yoyopod/runtime/` end up empty and are removed.

### 9.2 Split

**VoIPManager** (`src/yoyopod/communication/calling/manager.py`, 618 LOC) dissolves into `integrations/call/`:
- `__init__.py` — `setup(app)`: constructs `LiblinphoneBackend`, wires callbacks through scheduler, registers commands, subscribes to `AudioFocusLostEvent`.
- `handlers.py` — call-state handler, registration-state handler, availability handler, post-call history finalization.
- `messaging.py` — text message handling (from existing `MessagingService`).
- `voice_notes.py` — voice-note record/playback/send (from existing `VoiceNoteService`).
- `history.py` — persistent call history store (from existing `CallHistoryStore`).
- `commands.py` — `DialCommand`, `AnswerCommand`, `HangupCommand`, `RejectCommand`, `MuteCommand`, `UnmuteCommand`, `SendMessageCommand`, ...
- `events.py` — `CallIncomingEvent`, `CallBackendStateEvent`, `MessageReceivedEvent`, ...

Killed inside VoIPManager:
- All 4 private callback lists.
- `_dispatch_backend_event` / `_handle_backend_event` / `event_scheduler` chain.
- Private state mirrors (`call_state`, `registration_state`, `caller_address`, `caller_name`, `is_muted`, `registered`, `current_call_id`) — moved to `app.states`.
- Background iterate worker thread — kept but re-homed as an integration-owned helper, not a class method.

Analogous splits for:
- **PowerManager** + **PowerRuntimeService** → `integrations/power/`
- **NetworkManager** → `integrations/network/` and `integrations/location/` (GPS split out)
- **CloudManager** → `integrations/cloud/`
- **PeopleDirectory** → `integrations/contacts/`
- **LocalMusicService** → `integrations/music/library.py` (substantial logic kept as submodule)
- **VoiceRuntimeCoordinator** → `integrations/voice/`
- **ScreenPowerService** → `integrations/screen/`
- **RecoverySupervisor** → `integrations/recovery/`

### 9.3 Kept as adapters

Adapters retain their current file layout under `src/yoyopod/backends/`:
- `LiblinphoneBackend` (+ binding + shim)
- `MpvBackend` (+ process + ipc)
- `PiSugarBackend` (+ watchdog)
- Network modem/PPP/GPS backends
- Voice STT/TTS backends

Each gets a lightly trimmed interface: events are fired via `scheduler.run_on_main(lambda: app.bus.publish(...))` callbacks set by the owning integration's `setup()`. No more observer classes or callback lists on the adapter side.

### 9.4 Kept, slimmed

| Class | New LOC (approx) | Notes |
|---|---|---|
| `YoyoPodApp` | ~150 | Owns `bus`, `states`, `services`, `scheduler`, `config`. Calls `setup()` per integration. Runs main loop. Nothing else. |
| `Bus` (new) | ~50 | Main-thread-only, strict, no conditional branches in `publish()` |
| `ScreenManager` + screens | ≈ current | Constructors take `app` instead of specific managers; read via `states`, act via `services` |

Current spine LOC (app.py + fsm.py + event_bus.py + events.py + coordinators/ + VoIPManager + runtime/) ≈ **2,800 LOC**.
Target spine LOC (app_shell + bus + states + services + scheduler + core events + integrations' handler/command files) ≈ **1,400 LOC**.

---

## 10. Screen touch-up

Screens (`src/yoyopod/ui/screens/`) currently hold references to specific managers (e.g., `voip_manager`, `local_music_service`, `power_manager`). These become a single `app` reference.

### 10.1 Target pattern

```python
class NowPlayingScreen:
    def __init__(self, app: YoyoPodApp) -> None:
        self.app = app
        app.bus.subscribe(StateChangedEvent, self._on_state_changed)

    def _on_state_changed(self, ev: StateChangedEvent) -> None:
        if ev.entity in ("music.state", "music.track", "music.volume_percent"):
            self.dirty = True

    def render(self, canvas) -> None:
        state = self.app.states.get_value("music.state")
        track = self.app.states.get_value("music.track")
        # ... draw

    def on_button_play(self) -> None:
        if self.app.states.get_value("music.state") == "paused":
            self.app.services.call("music", "resume", ResumeCommand())
        else:
            current = self.app.states.get_value("music.track")
            self.app.services.call("music", "play", PlayCommand(track_uri=current.uri))
```

### 10.2 Screens affected

All 17 screens in `src/yoyopod/ui/screens/`:
- `home`, `hub`, `menu`, `listen`, `ask`, `power`
- `now_playing`, `playlist`, `recent_tracks`
- `call`, `talk_contact`, `call_history`, `contact_list`, `voice_note`, `incoming_call`, `outgoing_call`, `in_call`

Per-screen work is mechanical: replace manager references with `app`; rewrite reads to `app.states.get_value(...)`; rewrite writes to `app.services.call(...)`; add `StateChangedEvent` subscription for redraw triggers.

### 10.3 ScreenManager changes

- Constructor takes `app` (to resolve screen instances).
- `show_incoming_call(address, name)` / `show_in_call()` / `show_outgoing_call(...)` absorb the push/pop logic previously in `ScreenCoordinator`.
- `refresh_current_screen()` called once per tick by `ui.tick()`; screens mark themselves dirty via `StateChangedEvent` subscriptions.

---

## 11. Migration strategy: M-BigBang on a long-lived branch

Chosen explicitly by Moustafa over M-Incremental. Main branch frozen for the duration of Phase A (emergency hotfixes cherry-picked if unavoidable). Single merge when CI + Pi validation both green.

### 11.1 Branch plan

- Branch: `arch/phase-a-spine-rewrite` off `main` at SHA-of-record.
- Target merge commit is a single squash or a clean rebased history — reviewer's choice.
- No intermediate merges to main. No alias/compat code kept alive after each step.

### 11.2 Internal implementation order (commits on the branch, small and reviewable)

1. **CLI baseline verification.** Confirm the merged CLI polish baseline is still clean (`yoyopod_cli.main:run`, `tests/test_no_yoyoctl_references.py`, live docs/skills/rules). Fix only actual post-merge stragglers; do not replay the pre-merge bulk rename.

2. **Build `core/` scaffold.** `Bus`, `States`, `Services`, `MainThreadScheduler`, `YoyoPodApp` shell, core `events.py`, `core/testing.py`. Unit tests for each primitive. No integrations yet. Old app still runs.

3. **Migrate `power`.** Pilot. Isolated, well-understood. Delete `PowerManager`, `PowerRuntimeService`, `PowerCoordinator`. Pattern validated end-to-end.

4. **Easy batch: `network`, `location`, `contacts`, `cloud`.** Mostly data-flow, minimal cross-cutting.

5. **`focus` + `diagnostics`.** The arbiter and the event-log writer. Required before music/call migrations touch focus.

6. **`screen`.** Fold `ScreenPowerService`. Establishes the "integration owns the UI-adjacent side" pattern.

7. **`voice`.** Medium complexity. Uses `screen` (wake/sleep).

8. **`music`.** Uses `focus`. First hard integration.

9. **`call`.** Most complex. Uses `focus`; interacts with `music` via focus; messaging and voice-notes submodules.

10. **`recovery`.** Pulls in the last runtime service.

11. **Screen touch-up.** All 17 screens migrated to new pattern.

12. **Dead-code removal.** Delete FSMs, CoordinatorRuntime, AppRuntimeState, all coordinators, RuntimeBootService, RuntimeLoopService, ShutdownLifecycleService, RuntimeEventWiring, AppContext. `app.py` shrinks.

13. **Final sweep.** Double-check no `yoyoctl` references, no lingering managers outside integrations/, tests clean, docs updated. `docs/RUNTIME_EVENT_FLOW.md` archived or rewritten.

### 11.3 Acceptance bar per commit

- All commits on the branch pass `uv run python scripts/quality.py ci`.
- After step 2, `core/` has ≥90% test coverage.
- After each integration migration, its tests pass.
- The branch may leave the app unrunnable for some commits mid-rewrite (acceptable under M-BigBang), but tests must pass.

---

## 12. Testing strategy

### 12.1 Existing test suite — case by case

| File | Fate | Reason |
|---|---|---|
| `tests/test_fsm_runtime.py` | Delete | FSMs gone |
| `tests/test_event_bus.py` | Rewrite | New bus primitive |
| `tests/test_app_orchestration.py` | Rewrite | Orchestration is now integrations; tests go against `states`/`services`/`bus` |
| `tests/test_screen_routing.py` | Adapt | Screens still exist; touchpoints changed |
| `tests/test_call_screen.py` | Adapt | Screen now reads `states`, calls `services` |
| `tests/test_music_backend.py` | Keep | Backend adapter interface stays |
| `tests/test_voip_backend.py` | Keep | Same |
| `tests/test_config_models.py` | Keep | Config untouched |
| `tests/test_pi_remote.py` | Keep | CLI layer untouched (beyond rename) |
| `tests/test_cli.py` | Keep | Same |
| `tests/test_setup_cli.py` | Keep | Same |

### 12.2 New test structure

```
tests/
├── core/
│   ├── test_bus.py
│   ├── test_states.py
│   ├── test_services.py
│   └── test_scheduler.py
├── integrations/
│   ├── test_power.py
│   ├── test_music.py
│   ├── test_call.py
│   ├── test_focus.py
│   ├── test_network.py
│   ├── test_location.py
│   ├── test_cloud.py
│   ├── test_contacts.py
│   ├── test_voice.py
│   ├── test_screen.py
│   ├── test_diagnostics.py
│   └── test_recovery.py
├── e2e/
│   ├── test_call_pauses_music.py
│   ├── test_missed_call_logged.py
│   ├── test_voice_note_round_trip.py
│   ├── test_shutdown_flow.py
│   └── test_recovery_after_backend_stop.py
├── fixtures/
│   └── mock_backends.py
└── (kept) test_music_backend.py, test_voip_backend.py, test_config_models.py, test_pi_remote.py, test_cli.py, test_setup_cli.py
```

### 12.3 Test style

State-store + event-trace assertions, no method-mocking:

```python
def test_incoming_call_pauses_music(app):
    app.services.call("music", "play", PlayCommand(track_uri="local:test.mp3"))
    app.drain()
    assert app.states.get_value("music.state") == "playing"

    app.voip_backend.simulate_call("connected", caller="sip:bob@example")
    app.drain()

    assert app.states.get_value("call.state") == "active"
    assert app.states.get_value("music.state") == "paused"
    assert app.states.get_value("focus.owner") == "call"

    assert_events_contain(app.recent_events(), [
        CallBackendStateEvent(state="connected", caller_address="sip:bob@example"),
        StateChangedEvent(entity="call.state", old=("idle", {}), new=("active", {...})),
        AudioFocusLostEvent(owner="music", preempted_by="call"),
        StateChangedEvent(entity="music.state", old=("playing", ...), new=("paused", ...)),
    ])
```

### 12.4 Backend mocking

Mock backends live in `tests/fixtures/mock_backends.py`. Same interface as real backends; expose a test API to inject events:

```python
class MockVoIPBackend(VoIPBackend):
    def simulate_call(self, state: str, caller: str = "test@sip.example") -> None:
        self._publish_event(CallBackendStateEvent(state=state, caller_address=caller))
```

`build_test_app()` in `core/testing.py` wires mocks in place of real backends.

### 12.5 Development cadence: TDD

For each new primitive and integration:
1. Write failing unit / integration / e2e test.
2. Implement until green.
3. Refactor.

LLM-driven work benefits materially from concrete failing tests as specs. No legacy-test backward-compat pressure because rewriting tests is scope.

### 12.6 Pre-merge gate

Before the big-bang merge to main, all of:
- `uv run python scripts/quality.py ci` — full CI suite green (this is also the pre-commit gate per Moustafa's memory).
- `yoyopod pi validate deploy` — Pi deploy smoke green on actual hardware.
- `yoyopod pi validate smoke` — basic app-starts-and-responds green.
- `yoyopod pi validate music` — music flows green on hardware.
- `yoyopod pi validate voip` — VoIP flows green on hardware.
- `yoyopod pi validate stability` — no regressions under soak.
- Manual on-Pi checklist: place outgoing call, receive incoming call during music playback (verify auto-pause + auto-resume), missed call recording, voice note round-trip, graceful shutdown, wake from sleep after RTC alarm, recovery after killing mpv backend, recovery after killing Liblinphone backend.
- Event log review: tail `events.jsonl` during the manual checklist; verify no unexpected errors, no unexpected state transitions, no responsiveness-lag events.

---

## 13. Risks and known unknowns

1. **LVGL backend pump cadence.** The LVGL display backend needs its pump driven at a fixed cadence from the main loop. Under the new loop, this sits alongside `scheduler.drain()` and `bus.drain()`. Verify `ui.tick()` pumps LVGL at the current rate (current `_pump_lvgl_backend` fires every 5–10 ms). Mitigation: keep tick interval tunable; add `lvgl_pump_interval_seconds` to config; assert in `test_screen_integration` that the pump rate is maintained under event-storm conditions.

2. **VoIP iterate worker thread.** Liblinphone's native iterate runs on a dedicated worker (`voip-iterate` thread). Under the new model, this stays a worker thread owned by the `call` integration; events flow back to main via `scheduler.run_on_main()`. Mitigation: keep the worker's lifecycle simple (start in setup, stop in teardown). Validate the `_current_iterate_interval_seconds()` timing snapshot feeds `diagnostics` without cross-integration coupling.

3. **Event-log I/O on Pi Zero 2W.** SD-card write latency could spike during bursts. Mitigation: diagnostics writes via a background thread fed from the main-thread's event subscription; back-pressure drops oldest buffered entries rather than blocking the main loop. Add a test that asserts the log writer never blocks the main loop >5 ms.

4. **State-store fan-out on busy entities.** If a subscriber mis-uses `StateChangedEvent` without filtering, every state change wakes it. Mitigation: provide `bus.subscribe_to_entity(prefix, handler)` as a filtered helper; document the filter-by-prefix pattern; add a warning log if any handler exceeds a tick budget.

5. **Screen touch-up scope creep.** Screens are thick; changing them touches render logic. Mitigation: touch-up is strictly about read/write seams (manager references → `app.*`), not rendering. Any rendering change is out of scope for Phase A.

6. **Discovery that the pattern needs adjustment mid-rewrite.** Under M-BigBang this is the main risk: if `core/` primitives need a tweak after 3 integrations migrated, we retrofit in-branch. Mitigation: `core/` is small (~500 LOC) and has unit tests; changes there are localized; integration migrations are templateable, so retrofits propagate quickly.

7. **CLI rename collateral damage.** If the Phase A branch diverges from main for weeks and another CLI change lands on main, merge conflicts multiply. Mitigation: rebase the branch onto main after any significant main update; keep the CLI cleanup as the first commit so later conflicts are purely spine-related.

8. **Screens referencing deleted `AppContext`.** Many screens likely destructure `AppContext` for `battery_percent`, `missed_calls`, `recent_calls`, etc. Mitigation: the screen touch-up (step 11 of 11.2) explicitly replaces these reads with `app.states.get_value(...)`; exhaustive grep `context\.` in `ui/screens/` before merge.

---

## 14. Definition of done

- `src/yoyopod/coordinators/` deleted.
- `src/yoyopod/runtime/` deleted.
- `src/yoyopod/fsm.py` deleted.
- `src/yoyopod/app_context.py` deleted.
- `src/yoyopod/communication/calling/manager.py` deleted (logic split into `integrations/call/`).
- `src/yoyopod/app.py` ≤ 200 LOC.
- All 11 integrations present under `src/yoyopod/integrations/`.
- `core/` present with tested `Bus`, `States`, `Services`, `MainThreadScheduler`, `YoyoPodApp`.
- All 17 screens updated to take `app` and use `states`/`services`.
- Event log writing to `~/.yoyopod/logs/events.jsonl` with rotation.
- `diagnostics.snapshot` command produces a complete state + subscription + tick-stat dump.
- No `yoyoctl` references outside historical docs / planning files and `tests/test_no_yoyoctl_references.py`.
- Pre-merge gate (§12.6) all green.
- Design doc marked `Status: Implemented`.

---

## 15. Open questions for review

1. **`call.caller` entity shape.** Currently proposed as a separate entity alongside `call.state` with redundant data in attrs. Alternative: collapse caller into `call.state.attrs` only. Consequence: subscribers interested in just-caller-change need to filter on `call.state`'s attrs changing. Recommend: collapse (simpler catalog).

2. **Recovery integration location.** Originally a `RecoverySupervisor` runtime service. Now proposed as its own integration. Alternative: fold into `diagnostics` (recovery is arguably diagnostic). Recommend: keep separate — recovery is active behavior, diagnostics is passive observation.

3. **Voice integration scope.** Should STT engine lifecycle (model load/unload) be in `voice`, or split into a `voice_stt` integration? Recommend: keep together for Phase A; re-evaluate if `voice/` grows too large.

4. **`focus` integration state.** Proposed entity `focus.owner`. Alternative: expose `focus.active_mode` with value `none|call|music|voice`. Functionally equivalent. Recommend: keep `focus.owner`.

5. **Backwards-compat for Pi production deployment.** Production Pi runs `yoyopod@raouf.service`. During the frozen-main window, production Pi stays on pre-rewrite main. After merge, one coordinated deploy flips to new spine. Acceptable.

---

*End of design spec.*
