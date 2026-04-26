# Python Network Worker Design

**Date:** 2026-04-26
**Owner:** Moustafa
**Status:** Draft for review
**Target hardware:** Raspberry Pi Zero 2W
**Depends on:** Runtime Hybrid Phase 0-1 worker foundation

---

## 1. Problem

YoYoPod's cellular and GPS path currently uses Python modem, serial, GPS, and PPP code through the app-facing `NetworkManager`. Some bring-up work has been moved off the immediate boot path, but the supervisor process still contains the network lifecycle and can still be exposed to serial, modem, and PPP stalls.

On a Pi Zero 2W, the main product risk is not that network work consumes too much CPU. The risk is that hardware I/O stalls the UI loop, complicates shutdown, or leaves the modem/PPP state hard to recover without restarting the app. Phase 3 should move the full cellular/GPS/PPP operational lifecycle behind a Python worker process while keeping policy and user-visible state in the supervisor.

---

## 2. Goals

- Remove direct serial/modem/PPP blocking from the supervisor and UI loop.
- Keep the existing Python modem implementation where practical.
- Ensure only one process owns the modem serial port and PPP lifecycle when the worker is enabled.
- Make reconnect, modem failure, GPS failure, and PPP failure observable through structured events.
- Allow the supervisor to restart a wedged network worker without restarting UI, music, or VoIP.
- Preserve the existing network integration event model where possible.
- Keep network policy in Python supervisor code, not inside the worker.
- Validate on Pi Zero 2W with real modem hardware.

---

## 3. Non-goals

- Do not rewrite the modem stack in Go for Phase 3.
- Do not move Wi-Fi management into the worker.
- Do not move cloud MQTT ownership into the worker.
- Do not let the worker directly update screens or global app state.
- Do not let both supervisor and worker open the same serial port.
- Do not make the worker a general network daemon for unrelated app domains.
- Do not move VoIP/liblinphone into this worker.

---

## 4. Architecture

```text
Python supervisor process
  owns policy, app state, UI, Bus, Scheduler, degraded display,
  high-level network decisions, and worker supervision

Python network worker process
  owns cellular modem serial access, GPS queries, PPP bring-up/teardown,
  modem polling, reconnect attempts, and worker-local recovery loops
```

The worker can reuse existing Python backend code where possible:

- `yoyopod.backends.network.modem.Sim7600Backend`
- `yoyopod.backends.network.ppp`
- `yoyopod.backends.network.at_commands`
- `yoyopod.backends.location.gps`
- `yoyopod.integrations.network.models`

The supervisor-facing `NetworkManager` should become a small adapter when worker mode is enabled. It sends commands to the worker and translates worker facts/results into existing network events. In local or simulation mode, the existing in-process manager can remain available as an explicit compatibility path.

---

## 5. Ownership Rules

The main safety rule is single ownership.

When the network worker is enabled:

- The worker is the only process that opens the modem serial port.
- The worker is the only process that starts, observes, or stops PPP for the cellular modem.
- The supervisor must not call `Sim7600Backend` methods directly.
- The supervisor may request lifecycle operations, but the worker decides how to execute them safely.
- The supervisor owns user-visible state and policy decisions based on worker events.

This avoids split-brain modem control and prevents duplicate PPP processes.

---

## 6. Worker Protocol

The worker uses the Phase 1 NDJSON envelope protocol over stdio.

Required commands:

```text
network.health
network.start
network.stop
network.status
network.reconnect
network.reset_modem
network.query_gps
network.shutdown
```

Required events/results:

```text
network.ready
network.degraded
network.modem_state
network.signal
network.registered
network.ppp_up
network.ppp_down
network.gps_fix
network.gps_no_fix
network.reconnect_started
network.reconnect_result
network.error
network.cancelled
```

`network.status` result payload:

```json
{
  "phase": "online",
  "carrier": "Telekom.de",
  "network_type": "4G",
  "signal": {
    "bars": 3,
    "csq": 17
  },
  "ppp": {
    "up": true,
    "interface": "ppp0",
    "pid": 1234
  },
  "gps": {
    "has_fix": false
  },
  "updated_at_ms": 1777100000000
}
```

`network.error` payload:

```json
{
  "code": "serial_timeout",
  "message": "modem did not respond before deadline",
  "retryable": true,
  "phase": "initializing"
}
```

The payload shapes should map directly to existing typed events and models. The implementation should avoid adding a second parallel network vocabulary unless the existing model cannot represent a worker fact.

---

## 7. Lifecycle and Reconnect Policy

The worker owns execution mechanics. The supervisor owns policy.

Worker responsibilities:

- open and close the serial port
- initialize the modem
- start PPP without blocking shutdown indefinitely
- monitor PPP state
- poll signal and registration status
- query GPS when requested or when configured polling is enabled
- run bounded reconnect attempts
- stop PPP and close the serial port on shutdown
- emit structured progress and failure events

Supervisor responsibilities:

- decide whether cellular is enabled
- decide when to request start, reconnect, reset, or stop
- decide how degraded network state appears in UI/status
- apply network facts to `AppContext` and app state
- suppress duplicate commands when a request is already in flight

Reconnect policy:

- A reconnect request starts a worker-owned attempt with a request id and deadline.
- The worker emits `network.reconnect_started` once accepted.
- The worker emits `network.reconnect_result` with success/failure and final modem phase.
- The worker uses bounded backoff inside one reconnect attempt.
- If the worker process crashes, the supervisor restart/backoff policy applies.
- After worker restart, the supervisor requests `network.status` before deciding whether to reconnect again.

---

## 8. Failure Handling

Failure cases must be explicit because cellular hardware often fails partially.

Required failure mappings:

- serial port unavailable -> `network.degraded`, `code="serial_unavailable"`
- serial read timeout -> `network.error`, `code="serial_timeout"`
- SIM not ready -> `network.degraded`, `code="sim_not_ready"`
- registration failure -> `network.degraded`, `code="registration_failed"`
- PPP start failure -> `network.error`, `code="ppp_start_failed"`
- PPP exited unexpectedly -> `network.ppp_down`, then policy-driven reconnect
- GPS no fix -> `network.gps_no_fix`, not worker degraded
- modem reset failure -> `network.degraded`, `code="modem_reset_failed"`
- worker crash -> supervisor marks network worker degraded and may restart it

The supervisor must not treat GPS no-fix as network offline. GPS fix quality and cellular connectivity are separate facts.

---

## 9. Shutdown and Cleanup

Shutdown must remain bounded.

Rules:

- `network.shutdown` asks the worker to stop polling, stop PPP, close serial, and exit.
- The worker should stop PPP it started or clearly report why it cannot.
- The supervisor still enforces process terminate/kill through `WorkerProcessRuntime`.
- A stuck worker must not hang `YoyoPodApp.stop()`.
- Startup should detect stale PPP state before creating a new PPP instance.
- Worker status should report whether a PPP process was started by this worker instance.

The implementation should prefer explicit ownership markers for PPP state where practical, such as pid files, command metadata, or process command-line matching scoped to YoYoPod.

---

## 10. Configuration

Network worker configuration should live under the existing network/device config topology.

Required configuration concepts:

- worker enabled flag
- worker argv or module path
- serial port
- baud rate
- PPP timeout
- reconnect enabled flag
- reconnect attempt count
- reconnect backoff seconds
- GPS enabled flag
- GPS poll interval
- status poll interval
- modem reset command policy

When worker mode is enabled, the in-process `NetworkManager` must not instantiate a live `Sim7600Backend` for the same modem.

---

## 11. RAM and Performance Measurement

The network worker is expected to increase total PSS because it is another Python process. That is acceptable if it removes UI-loop stalls and isolates modem failures.

Required Pi Zero 2W scenarios:

- supervisor idle with network disabled
- current in-process network bring-up
- worker network bring-up
- PPP up and idle
- GPS query
- modem unavailable
- PPP failure and reconnect
- worker crash and supervisor restart

Record:

- supervisor PSS/RSS
- worker PSS/RSS
- total process tree PSS/RSS
- `runtime_loop_gap_seconds`
- `runtime_main_thread_drain_seconds`
- network command latency
- reconnect duration
- worker restart count
- protocol errors and dropped messages
- orphaned PPP process count after shutdown/restart

Acceptance target:

- No direct serial/PPP blocking path remains on the supervisor UI loop when worker mode is enabled.
- Network reconnect/failure handling does not create UI loop gaps over the runtime threshold.
- Worker crash degrades network only and does not crash UI, music, local navigation, or VoIP.
- Shutdown leaves no YoYoPod-owned PPP process behind in the normal path.

---

## 12. Testing Strategy

Required tests:

- Python fake network worker emits ready/status/signal/PPP/GPS events.
- `NetworkManager` worker adapter translates worker messages into existing network events.
- start/reconnect/status commands carry request ids and deadlines.
- serial timeout and SIM-not-ready errors map to degraded state.
- GPS no-fix maps to location event without marking network offline.
- worker crash maps to network degraded state and restart/backoff.
- shutdown sends worker stop and remains bounded.
- PPP ownership cleanup is tested with a fake process layer.
- status snapshot includes worker health and pending request counts.

Hardware validation is required before merging production worker mode:

- deploy validation
- smoke validation
- stability navigation soak
- cellular start/status/reconnect path on target modem
- shutdown/restart check for orphaned PPP/serial ownership

---

## 13. Rollout Plan

Recommended PR sequence:

1. Add network worker protocol contract, fake worker, and supervisor-side adapter tests.
2. Add Python worker entrypoint that can run status-only fake backend mode.
3. Move modem status polling and GPS query through worker mode behind a feature flag.
4. Move PPP start/stop/reconnect lifecycle into the worker.
5. Make worker mode the default on Pi hardware after target validation.
6. Remove or narrow in-process modem startup paths that would violate single ownership.

Each step should keep the old path available until the worker path passes hardware validation. The final default switch should happen only after serial ownership and PPP cleanup are proven on the Pi.

---

## 14. Open Decisions Resolved

- Worker language: Python for Phase 3.
- Worker scope: full serial/GPS/PPP operational lifecycle.
- Supervisor scope: policy, UI state, app state, and event application.
- Ownership rule: one process owns the modem serial port and PPP lifecycle when worker mode is enabled.
- Primary success metric: no UI-loop serial stalls and bounded recovery, not RAM reduction.

