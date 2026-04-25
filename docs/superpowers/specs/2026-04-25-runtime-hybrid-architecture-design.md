# Runtime Hybrid Architecture Design

**Date:** 2026-04-25
**Owner:** Moustafa
**Status:** Draft for review
**Target hardware:** Raspberry Pi Zero 2W
**Related PR:** GitHub PR #376, `feat(core): add BackgroundExecutor for off-thread work`

---

## 1. Problem

YoYoPod currently behaves like a mostly single-threaded Python application with scattered background work. The main runtime loop owns LVGL, input handling, app state, scheduling, and event delivery. Some subsystems already use threads or native subprocesses, but the concurrency model is not yet an explicit runtime architecture.

The goal is to improve responsiveness on a Raspberry Pi Zero 2W and make better use of its four Cortex-A53 cores without turning the application into seven loosely coordinated services. The GIL prevents CPU-bound Python threads from running Python bytecode in parallel inside one process, but process boundaries and native workers can use additional cores. Threads are still useful for blocking I/O, native extensions that release the GIL, subprocess supervision, and sleep/poll loops.

The design must protect the small-screen UI experience first. A faster architecture that makes call handling, state ownership, or shutdown behavior harder to reason about would be a bad trade.

---

## 2. Goals

- Keep button-to-visible-response latency consistently low under background load.
- Use additional CPU cores where it matters, especially for voice and blocking hardware I/O.
- Reduce RAM pressure by avoiding local STT model loading by default.
- Keep UI, app state, call/music coordination, screen navigation, `Bus`, and `MainThreadScheduler` in one Python supervisor process.
- Move selected blocking or memory-heavy work behind process boundaries with explicit protocols.
- Make worker crashes degrade one domain instead of crashing the whole app.
- Keep the first implementation inspectable and debuggable on a Pi over SSH.
- Preserve the current codebase's main-thread scheduling pattern: background work returns facts/results to the main thread; the main thread applies state.

---

## 3. Non-goals

- Do not split YoYoPod into seven OS processes in the first architecture pass.
- Do not move LVGL, screen management, `Bus`, `MainThreadScheduler`, `AppStateRuntime`, `CallRuntime`, or `MusicRuntime` out of the supervisor.
- Do not make ZeroMQ/msgpack a phase-one dependency.
- Do not rewrite the network/modem stack in Go before measurements prove it is worth the risk.
- Do not move VoIP/liblinphone to a sidecar in the first worker wave.
- Do not guarantee offline voice commands when cloud voice is selected.
- Do not attempt a full asyncio migration as part of the first process split.

---

## 4. Success Criteria

Responsiveness targets on target hardware:

- Input event to handled action p95 under 50 ms during mixed background work.
- Handled action to visible LVGL refresh p95 under 100 ms.
- No main-loop gap over 250 ms during a one-hour mixed soak unless explicitly classified as an expected shutdown/reboot path.
- No synchronous supervisor wait on voice, network, cloud, or worker shutdown paths during normal UI operation.

Reliability targets:

- A voice worker crash disables voice and produces visible degraded state, but UI, music, network status, and VoIP continue.
- A network worker crash disables or degrades cellular/GPS/network facts, but UI, music, local navigation, and active app loop continue.
- Worker queues are bounded. Overflow is counted and reported rather than growing without limit.
- Shutdown has bounded waits. A stuck worker must not hang `app.stop()` indefinitely.

RAM targets:

- Cloud-first voice should reduce memory versus the current local Vosk default.
- The first two workers should fit comfortably on Pi Zero 2W after measuring proportional set size (PSS), not only RSS.
- Local STT models may remain available as an explicit opt-in, but they are not loaded by default.

---

## 5. Architecture Decision

Use a hybrid architecture:

```text
Python supervisor process
  owns UI, app state, bus, scheduler, navigation, music/call coordination

Go voice worker process
  owns cloud STT/TTS streaming, cancellation, and voice request lifecycle

Python network worker process
  owns serial/modem/GPS/PPP polling and emits network facts

Optional future workers
  only added after instrumentation shows a concrete stall, crash, or memory problem
```

The supervisor is the only process allowed to mutate application state. Workers are fact producers and command executors. They report observations and results; they do not own global truth.

This design rejects a first-pass seven-process split because YoYoPod's hardest problem is not raw CPU scheduling. The first bottleneck to prove and fix is responsiveness under blocking I/O and heavy voice paths. A broad service split would add RAM overhead, IPC complexity, ordering bugs, restart policy questions, and more deployment surface before the measurements justify it.

---

## 6. Supervisor Responsibilities

The Python supervisor remains the runtime authority for:

- LVGL pumping and screen rendering.
- Input event handling.
- Screen navigation.
- `Bus` delivery.
- `MainThreadScheduler` draining.
- App state transitions.
- Call and music coordination.
- User-visible degraded states.
- Worker lifecycle supervision.
- Applying worker facts to app-owned state.

The supervisor must not perform blocking worker calls on the UI path. It sends commands with deadlines and continues pumping the loop. Worker results are delivered back through the scheduler/bus seam already used by the current runtime.

---

## 7. Worker Protocol

Phase one uses stdio plus newline-delimited JSON (NDJSON).

```text
supervisor stdin -> worker commands
worker stdout    -> supervisor events/results
worker stderr    -> logs
```

This is intentionally boring:

- easy to inspect with shell tools
- language-neutral
- no broker process
- no new native dependency
- suitable for Go, Python, Rust, or C workers
- easy to fake in tests

Each message envelope includes:

```json
{
  "schema_version": 1,
  "kind": "command | event | result | error | heartbeat",
  "type": "voice.transcribe | network.status | ...",
  "request_id": "optional stable request id",
  "timestamp_ms": 1777100000000,
  "deadline_ms": 5000,
  "payload": {}
}
```

Protocol rules:

- Unknown `schema_version` is rejected with a structured protocol error.
- Unknown `type` is ignored or rejected based on message kind, then counted.
- Commands that expect replies carry `request_id`.
- Long-running work must support cancellation when practical.
- Worker stdout is protocol-only. Human logs go to stderr.
- Supervisor receive queues are bounded.
- Supervisor send queues are bounded.
- Queue overflow is a health signal and may drop low-priority events.
- `timestamp_ms` is Unix epoch milliseconds for diagnostics.
- `deadline_ms` is a relative budget from worker receipt time. A value of `0` means no explicit deadline, and should be rare.
- Large or binary payloads are not embedded in NDJSON. Use temp file paths, inherited file descriptors, or worker-owned streams.

ZeroMQ/msgpack remains a later option. It becomes attractive only if measured IPC overhead, fan-out shape, or multi-client patterns justify it. The first design wants a crisp process contract more than maximum theoretical IPC speed.

---

## 8. Go Voice Worker

Voice is the best first non-Python worker because it has the clearest payoff:

- cloud STT/TTS avoids local Vosk memory pressure
- Go avoids Python interpreter overhead in the worker
- Go has good standard-library support for HTTP, JSON, process signals, contexts, cancellation, and streaming I/O
- cross-compilation to Pi is straightforward
- implementation speed is better than Rust for this project phase

Responsibilities:

- Handle cloud STT requests.
- Handle cloud TTS requests.
- Stream or chunk audio to the chosen provider.
- Enforce request deadlines.
- Cancel active voice work when the supervisor sends cancellation.
- Report degraded state when cloud voice is unavailable.
- Emit structured timing and memory diagnostics.

Initial audio boundary:

- Keep raw audio out of JSON envelopes.
- Prefer the existing Python capture path writing a bounded temp audio file, then pass the file path and metadata to the Go worker for cloud STT.
- For cloud TTS, prefer the Go worker writing a bounded temp audio file and returning its path to the supervisor.
- Later, if latency measurements justify it, move capture or playback-adjacent streaming fully into the Go worker under the same command/result contract.

Out of scope for the first voice worker:

- owning UI state
- executing app commands directly
- owning wake word policy
- replacing call audio
- guaranteeing offline STT

Offline behavior:

- voice commands are unavailable when cloud voice is unavailable
- local tones/status prompts still work where already supported
- UI shows voice degraded/unavailable
- music, VoIP, navigation, and non-voice controls continue

---

## 9. Python Network Worker

Network should be split after the worker runtime exists, but it should remain Python initially.

Reasons:

- existing `pyserial`, SIM7600, PPP, and GPS code is already Python-oriented
- serial and modem behavior is hardware-sensitive
- rewriting it while changing process boundaries would multiply risk
- a Python sidecar still isolates serial stalls from the UI loop

Responsibilities:

- Poll modem/network status.
- Manage serial interaction that can block or stall.
- Emit GPS/location facts if still owned by the network stack at implementation time.
- Emit connection state, signal quality, and error facts.
- Accept explicit reconnect/reset-style commands from the supervisor when supported.

The network worker does not decide navigation, user messaging, or app state. It only reports facts and command results.

---

## 10. VoIP Decision

Do not create a VoIP sidecar in the first worker wave.

Liblinphone already lives behind a native backend and has tight coupling to call state, audio device behavior, ringing, active-call transitions, message events, and screen navigation. Moving it out of process might improve crash isolation, but it is unlikely to improve RAM and could create subtle ordering and audio bugs.

Phase zero and phase one must instrument VoIP carefully:

- duration of `iterate` or equivalent background calls
- callback-to-main-thread latency
- incoming-call event latency
- call state transition latency
- audio-device contention
- crashes or native wedges

VoIP becomes a candidate sidecar only if measurements show one of these:

- liblinphone blocks the supervisor enough to violate responsiveness targets
- liblinphone crashes or wedges the process
- call audio requires isolation from other audio paths
- shutdown/restart of VoIP is needed without restarting UI

Until then, keeping VoIP in-process is the simpler and safer design.

---

## 11. PR #376 Alignment

PR #376 is aligned as an enabling step, not the final architecture.

It improves the current runtime by grouping ad-hoc threads behind a shared `BackgroundExecutor`, registering long-running pollers, and returning background results to the main thread. That matches the direction of this design: explicit lanes, centralized shutdown, and main-thread state application.

Before using it as a foundation, the implementation plan must address two risks found during review:

1. Executor shutdown must be bounded. A stuck I/O task must not make `app.stop()` block forever.
2. Watchdog feeding must not share a saturated general I/O pool. It needs a dedicated safety lane or a design that cannot be starved by cloud/network work.

Useful follow-ups from PR #376:

- queue depth and pending-task diagnostics
- bounded submit wrappers or explicit backpressure
- named lanes for safety-critical work versus ordinary I/O
- consistent "background result posts to main thread" helpers

PR #376 should be treated as a cleanup bridge toward the process-worker runtime, not as a substitute for it.

---

## 12. RAM Budget Model

Use PSS as the main memory metric because RSS double-counts shared pages across processes.

Rough planning estimates before measurement:

```text
Python sidecar process: 30-70 MB PSS
Go sidecar process:     12-30 MB PSS
Rust/C sidecar process:  5-20 MB PSS
Cloud voice active:     40-70 MB PSS incremental, depending on buffers/provider client
Local Vosk active:     100-180+ MB incremental, depending on model and keep-loaded mode
```

Expected direction:

- Go cloud voice worker adds process overhead, but removes local Vosk as the default memory resident.
- Python network worker adds memory, but isolates serial/modem stalls.
- Net memory may still improve if Vosk was previously kept loaded.
- VoIP sidecar is likely RAM-neutral or worse, because it adds another interpreter/process boundary while still needing native liblinphone resources.

The spec does not claim exact savings. Phase zero must measure baseline PSS, and each worker phase must include before/after memory snapshots under equivalent scenarios.

---

## 13. Instrumentation First

Phase zero is required before worker extraction.

Add or extend diagnostics for:

- input event received timestamp
- action handler start and finish
- next visible LVGL refresh after action
- main-loop gaps
- scheduler drain duration
- bus drain duration
- blocking span attribution
- worker queue depth once workers exist
- worker restart count
- worker request latency
- PSS snapshots by process

The important product metric is not "uses all four cores." The important metric is "the device reacts immediately while background work is happening." CPU utilization is supporting evidence only.

---

## 14. Phase Plan

### Phase 0: Responsiveness and memory baseline

Measure the current runtime without changing architecture.

Deliverables:

- button-to-action latency metric
- action-to-visible-refresh latency metric
- main-loop gap metric
- blocking-span labels for known risky paths
- PSS/RSS snapshot helper for Pi runs
- one-hour mixed soak report format

Exit criteria:

- baseline numbers collected on target hardware
- top responsiveness offenders identified
- local Vosk memory impact measured with keep-loaded on and off

### Phase 1: Worker runtime

Build the supervisor-side process runtime without moving major subsystems yet.

Deliverables:

- worker process launcher
- NDJSON envelope parser/writer
- bounded send and receive queues
- request/reply tracking
- deadline and cancellation support
- heartbeat support
- restart/backoff policy
- fake worker test harness
- degraded-state reporting path

Exit criteria:

- fake worker crash does not crash supervisor
- fake worker hang does not block UI loop or shutdown forever
- queue overflow is counted and visible
- tests cover malformed messages, unknown schema, restart, timeout, and cancellation

### Phase 2: Go cloud voice worker

Move cloud STT/TTS request execution to the Go worker.

Deliverables:

- Go worker skeleton and build path for Pi
- cloud STT command path
- cloud TTS command path
- cancellation/deadline handling
- voice degraded-state mapping
- local Vosk disabled by default
- fallback local tones/status prompts preserved where applicable

Exit criteria:

- UI remains responsive during voice requests
- cloud outage degrades voice only
- worker crash degrades voice only
- measured memory is lower than or acceptable versus current local voice baseline

### Phase 3: Python network worker

Move blocking serial/modem/GPS/PPP polling into a Python sidecar.

Deliverables:

- network worker entrypoint
- modem/GPS/network fact events
- supervisor network-state adapter
- reconnect/reset command path where supported
- degraded-state behavior for worker crash or serial failure

Exit criteria:

- serial stalls do not produce main-loop gaps over target
- network worker crash does not crash UI
- network facts update through the main-thread state path
- hardware smoke run confirms modem behavior

### Phase 4: VoIP decision gate

Do not implement by default. Decide from measurements.

Deliverables if needed:

- VoIP sidecar feasibility note
- measured reason for sidecar split
- audio-device ownership plan
- call-state protocol design

Exit criteria:

- either VoIP remains in-process with evidence, or a separate VoIP design is approved before implementation

---

## 15. Error Handling

Worker failures map to domain degradation, not global failure.

Supervisor behavior:

- mark domain degraded
- show or expose user-visible unavailable state where appropriate
- cancel outstanding requests for the failed worker
- restart with bounded exponential backoff
- stop restarting after a configured threshold and keep domain disabled
- continue pumping UI during restart/backoff

Worker behavior:

- never write non-protocol text to stdout
- write logs to stderr
- return structured errors for expected failures
- exit non-zero for unrecoverable startup/runtime failures
- honor cancellation and deadlines where practical

Shutdown behavior:

- send graceful stop command if the worker protocol is alive
- wait for a bounded grace period
- terminate if needed
- kill only after terminate fails or exceeds timeout
- never wait indefinitely on ordinary shutdown

---

## 16. Testing Strategy

Unit tests:

- message envelope validation
- schema/version rejection
- request/reply matching
- cancellation and timeout behavior
- bounded queue overflow
- restart/backoff state transitions
- degraded-state mapping

Integration tests:

- fake worker emits events and supervisor applies them on main-thread scheduler
- fake worker crashes and supervisor continues
- fake worker hangs and shutdown remains bounded
- malformed worker output is rejected and counted
- slow worker responses do not block UI-loop simulation

Hardware validation:

- Pi Zero 2W one-hour mixed soak
- voice request under cloud success/failure/timeout
- network serial stall simulation or real modem failure test
- memory snapshots before and after each phase
- active call smoke after worker runtime changes, even before any VoIP split

Regression checks:

- `uv run python scripts/quality.py gate`
- `uv run pytest -q`

---

## 17. Open Implementation Decisions

These are intentionally left for the implementation plan, not the architecture spec:

- exact cloud STT/TTS provider API shape
- exact Go module layout
- exact process binary packaging inside dev/prod lanes
- exact temp-file lifetime and cleanup ownership for voice audio payloads
- specific PSS snapshot command format for Pi diagnostics
- exact queue sizes and restart thresholds

The implementation plan must pick concrete defaults for these before code changes begin.

---

## 18. Final Recommendation

Proceed with the hybrid design:

1. Instrument first.
2. Add a small, language-neutral worker runtime.
3. Move cloud voice to a Go worker.
4. Move network/modem polling to a Python worker.
5. Keep VoIP in-process until measurements prove that a sidecar is necessary.

This gives YoYoPod the performance benefit of multiple cores where the current runtime most needs it, while keeping the small-screen product behavior understandable and safe.
