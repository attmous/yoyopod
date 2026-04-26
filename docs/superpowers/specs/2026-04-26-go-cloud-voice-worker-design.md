# Go Cloud Voice Worker Design

**Date:** 2026-04-26
**Owner:** Moustafa
**Status:** Draft for review
**Target hardware:** Raspberry Pi Zero 2W
**Depends on:** Runtime Hybrid Phase 0-1 worker foundation

---

## 1. Problem

YoYoPod's local voice path currently composes audio capture, local STT, command matching, and local TTS inside the Python supervisor runtime. The local Vosk STT path is the main RAM concern on Raspberry Pi Zero 2W, especially when the model is kept resident. Python threads can hide some blocking I/O but do not make CPU-bound Python work run in parallel because of the GIL.

The Phase 1 worker runtime now gives YoYoPod a bounded, supervised process boundary with request deadlines, cancellation, crash isolation, and status reporting. Phase 2 should use that foundation for the first production sidecar: a Go cloud voice worker.

The goal is not to make voice independent from the app. The Python supervisor remains the owner of UI state, audio policy, command execution, and user-visible degraded behavior. The Go worker handles cloud STT/TTS calls and request lifecycle mechanics.

---

## 2. Goals

- Reduce default RAM pressure by making cloud STT/TTS the normal voice path instead of loading Vosk by default.
- Keep the UI loop responsive while STT/TTS requests are in flight.
- Use the existing worker supervisor and NDJSON envelope protocol.
- Keep the supervisor-worker contract provider-neutral while implementing only one cloud provider in the first production worker.
- Preserve local non-speech feedback for button and voice interaction states.
- Enforce request deadlines and cancellation across the process boundary.
- Surface cloud voice degraded state without degrading music, VoIP, navigation, or local controls.
- Produce before/after Pi Zero 2W RAM measurements against the current Vosk path.

---

## 3. Non-goals

- Do not move LVGL, screen navigation, app state, command execution, or voice UI state into Go.
- Do not move microphone capture into Go in the first implementation slice.
- Do not move audio playback ownership into Go in the first implementation slice.
- Do not build multiple cloud provider adapters in the first production worker.
- Do not guarantee offline STT/TTS in Phase 2.
- Do not remove the existing local Vosk/espeak code in this phase. It may remain as an explicit opt-in or fallback for development, but it is not the default Pi Zero runtime path.
- Do not move VoIP or call audio into the voice worker.

---

## 4. Architecture

```text
Python supervisor process
  owns UI, app state, voice interaction state, command execution, capture, playback,
  local feedback, worker supervision, and degraded status

Go voice worker process
  owns cloud STT/TTS provider calls, request contexts, cancellation,
  deadlines, provider error mapping, and worker-local diagnostics
```

The first production path keeps capture and playback adjacent to the existing Python voice runtime:

```text
PTT/listen action
  -> Python captures bounded WAV/PCM temp file
  -> supervisor sends voice.transcribe request to Go worker
  -> Go worker uploads/processes audio with one cloud provider
  -> Go worker returns transcript result
  -> Python command executor maps transcript to an app action
  -> Python optionally requests voice.speak for spoken cloud TTS
  -> Go worker writes bounded TTS temp file
  -> Python plays returned file using the existing output path
```

This keeps raw audio out of JSON envelopes and avoids changing the most hardware-sensitive paths at the same time as introducing the Go worker.

---

## 5. Local Feedback

Local non-speech feedback remains in the supervisor and stays available even when cloud voice is degraded:

- attention tones
- button or capture start/stop sounds
- short error/status sounds that already exist locally
- visual state changes on the Ask screen

Phase 2 does not require local spoken fallback. A future phase may add a small canned-prompt TTS path if measurements show it is cheap enough, but Phase 2's local fallback is non-speech only.

---

## 6. Worker Protocol

The worker uses the Phase 1 NDJSON envelope protocol over stdio. Worker stdout is protocol-only. Worker stderr is logs.

Required commands:

```text
voice.health
voice.transcribe
voice.speak
voice.cancel
voice.shutdown
```

Required events/results:

```text
voice.ready
voice.degraded
voice.progress
voice.transcribe.result
voice.speak.result
voice.cancelled
voice.error
```

`voice.transcribe` payload:

```json
{
  "audio_path": "/tmp/yoyopod-voice-input.wav",
  "format": "wav",
  "sample_rate_hz": 16000,
  "channels": 1,
  "language": "en",
  "delete_input_on_success": false
}
```

`voice.transcribe.result` payload:

```json
{
  "text": "play music",
  "confidence": 0.92,
  "is_final": true,
  "provider_latency_ms": 481,
  "audio_duration_ms": 2100
}
```

`voice.speak` payload:

```json
{
  "text": "Playing music",
  "voice": "default",
  "format": "wav",
  "sample_rate_hz": 16000
}
```

`voice.speak.result` payload:

```json
{
  "audio_path": "/tmp/yoyopod-voice-output.wav",
  "format": "wav",
  "sample_rate_hz": 16000,
  "duration_ms": 830,
  "provider_latency_ms": 352
}
```

`voice.degraded` and `voice.error` payloads must include:

```json
{
  "code": "provider_unavailable",
  "message": "cloud voice provider unavailable",
  "retryable": true
}
```

The protocol names voice operations, not the provider. Provider-specific request options stay inside the Go worker config and are not exposed to the supervisor unless they become product features.

---

## 7. Deadlines and Cancellation

The supervisor already tracks request deadlines. The Go worker must also enforce deadlines locally.

Rules:

- Every STT/TTS request from the supervisor carries a `request_id` and `deadline_ms`.
- The worker creates a request-scoped context with the smaller of `deadline_ms` and any worker-side maximum.
- `voice.cancel` cancels the active context for the matching request id.
- Late provider responses after cancellation are discarded by the worker.
- Late worker responses are still protected by the supervisor's stale-attempt logic.
- The worker emits `voice.cancelled` only when it has accepted or observed cancellation for that request.
- A provider call that times out returns `kind="error"` with `code="deadline_exceeded"` and `retryable=true` when retry is safe.

The worker may process one active voice request at a time in the first implementation. If a second request arrives while one is active, the worker returns a retryable `voice.error` with `code="busy"` unless the request is an explicit cancel.

---

## 8. Degraded Behavior

Cloud voice can degrade for several reasons:

- no network path
- provider DNS/TLS/connectivity failure
- provider timeout
- provider rate limit
- provider authentication failure
- malformed local audio file
- Go worker crash or protocol failure

Supervisor behavior:

- Keep UI, music, VoIP, local navigation, and local feedback running.
- Mark voice STT/TTS availability as degraded in app status.
- Show a voice-unavailable Ask outcome rather than blocking the screen.
- Do not load Vosk automatically as a hidden fallback on Pi Zero.
- Allow an explicit local-voice development mode to use the current Vosk/espeak path if configured.

Worker behavior:

- Emit structured `voice.degraded` on startup when provider config is missing or invalid.
- Emit `voice.degraded` after repeated retryable provider failures.
- Recover automatically when a later `voice.health` or STT/TTS request succeeds.
- Exit cleanly on `voice.shutdown`; otherwise the supervisor stop path remains bounded.

---

## 9. Configuration and Secrets

The first implementation should add a cloud voice configuration section under the existing config topology rather than scattering provider settings across code.

Required configuration concepts:

- voice mode: `cloud`, `local`, or `disabled`
- worker enabled flag
- worker binary path
- STT language
- TTS voice name
- request timeout seconds
- maximum audio input duration
- maximum TTS output duration
- provider name for diagnostics

Secrets must not be stored in tracked YAML. Provider keys should come from environment variables or the existing device secrets mechanism. Logs and worker envelopes must not include raw provider credentials.

---

## 10. RAM and Performance Measurement

Phase 2 is not complete without target-hardware measurements.

Required Pi Zero 2W scenarios:

- supervisor idle with voice disabled
- supervisor idle with current local Vosk configured
- one local Vosk transcription path, if model is installed
- supervisor plus Go voice worker idle
- one cloud STT request
- one cloud TTS request
- degraded provider path

Record:

- supervisor PSS/RSS
- worker PSS/RSS
- total process tree PSS/RSS
- `responsiveness_input_to_action_p95_ms`
- `responsiveness_action_to_visible_p95_ms`
- `runtime_main_thread_drain_seconds`
- worker request latency
- worker restart count
- protocol errors and dropped messages

Acceptance target:

- Default cloud voice mode should use less total PSS than the current default local Vosk path when Vosk is kept available for voice commands.
- STT/TTS requests must not introduce UI-loop blocking spans over the existing runtime thresholds.
- Voice worker crash must degrade voice only and must not crash the supervisor.

---

## 11. Testing Strategy

Unit and integration tests should cover the Python supervisor boundary before depending on a real cloud provider.

Required tests:

- protocol payload validation for `voice.transcribe`, `voice.speak`, and `voice.cancel`
- fake Go-compatible worker that returns STT result envelopes
- fake worker that returns TTS audio file path envelopes
- timeout and cancellation handling through `WorkerSupervisor`
- provider unavailable mapped to degraded voice state
- worker crash mapped to voice degraded state
- local feedback still triggered when cloud voice is unavailable
- status snapshot includes voice worker state and memory data

The Go worker should have its own tests for request parsing, context cancellation, provider error mapping, and temp-file output cleanup. The first implementation may use a fake provider client for CI.

---

## 12. Rollout Plan

Recommended PR sequence:

1. Add Python-side cloud voice worker contract, fake worker tests, config shape, and status wiring.
2. Add Go worker skeleton with `voice.health`, `voice.transcribe` fake-provider mode, packaging, and Pi deploy support.
3. Route STT through the worker when cloud mode is enabled; keep local Vosk as explicit opt-in.
4. Add TTS worker path and playback of returned audio file.
5. Run Pi Zero RAM and responsiveness comparison and update profiling docs with measured results.

Each step should remain mergeable on its own. Production cloud provider credentials should be optional for CI and local simulation.

---

## 13. Open Decisions Resolved

- Runtime language: Go for the voice worker.
- Default Phase 2 voice mode: cloud first.
- Offline behavior: no full offline voice guarantee.
- Local fallback: non-speech feedback only.
- Provider strategy: one provider in the first production worker, with a provider-neutral supervisor protocol.
- Audio boundary: temp files across the process boundary for Phase 2.

