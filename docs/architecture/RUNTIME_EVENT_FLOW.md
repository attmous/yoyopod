# Runtime Event Flow

**Last updated:** 2026-05-06
**Status:** Current implementation

This document maps the supported Rust runtime event flow. If code and docs
disagree, trust the Rust runtime and host code under `device/`.

## Big Picture

`yoyopod-runtime` is the process owner. It loads config, starts supervised host
processes, reads NDJSON worker envelopes from host stdout, routes events into
runtime state, and sends commands or UI snapshots back to hosts over stdin.

Hosts own domain integration:

- `device/cloud/`: MQTT telemetry and backend commands
- `device/media/`: local music and mpv control
- `device/network/`: modem, PPP, and GPS state
- `device/power/`: PiSugar battery, RTC, watchdog, and shutdown signals
- `device/speech/`: ASK and voice command speech work
- `device/ui/`: screen model rendering and UI intents
- `device/voip/`: Liblinphone/SIP calls, messages, and voice notes

The retired Python runtime event loop is preserved only under
`legacy/python-runtime/` for reference.

## Protocol Rule

Runtime and hosts communicate with newline-delimited JSON envelopes defined by
`device/protocol/`.

The common envelope classes are:

- `event`: asynchronous host state or intent
- `command`: runtime request to a host
- `result`: response to a command request id
- `error`: domain or protocol failure

Every host should emit a `*.ready` event once it has initialized far enough for
the runtime to mark the worker running or degraded.

## Runtime Loop

Each runtime iteration:

1. drains worker stdout and protocol errors
2. applies host events and command results to runtime state
3. routes UI intents, cloud commands, and domain side effects
4. evaluates safety policy such as low or critical battery state
5. sends queued host commands
6. sends a UI tick and, when state changed, a fresh UI runtime snapshot
7. updates worker health and shutdown state

The runtime owns orchestration and cross-domain policy. Host code owns the
domain-specific hardware/backend details.

## Important Flows

### Incoming Call

1. `voip-host` receives Liblinphone call state.
2. `voip-host` emits a `voip.snapshot` event.
3. `yoyopod-runtime` applies the snapshot to call state.
4. The runtime pauses media when needed and updates the UI snapshot.
5. `ui-host` renders the incoming or active call screen and emits user intents.
6. Runtime routes answer, reject, hangup, mute, and dial intents back to
   `voip-host`.

### Playback

1. `media-host` owns mpv transport and track metadata.
2. Track or playback changes emit `media.snapshot`.
3. Runtime updates media state and visible setup/listen/now-playing projections.
4. UI music intents route back to `media-host` commands.

### Power

1. `power-host` emits battery and power policy snapshots.
2. Runtime updates app power state.
3. Runtime publishes cloud battery telemetry through `cloud-host` when needed.
4. Critical battery state requests shutdown once until power is restored.

### Network

1. `network-host` emits modem, PPP, signal, and GPS snapshots.
2. Runtime updates network status and setup-page rows.
3. Connectivity changes route to `cloud-host` telemetry.

### Speech And ASK

1. UI voice intents start, stop, or cancel capture.
2. Runtime routes recording work to VoIP or speech hosts depending on intent.
3. `speech-host` returns transcripts or ASK replies.
4. Runtime applies local command routing first and uses ASK fallback when
   enabled.
5. Runtime sends speak/playback commands for the final response.

### Cloud Commands

1. `cloud-host` receives backend MQTT commands and emits `cloud.command`.
2. Runtime routes supported remote media/config commands to the owning domain.
3. Runtime sends an ACK/NACK command back to `cloud-host`.

## Ownership Boundaries

- Runtime state projection lives in `device/runtime/src/state.rs`.
- Worker supervision and command routing live in `device/runtime/src/worker.rs`
  and `device/runtime/src/runtime_loop.rs`.
- Shared envelope behavior lives in `device/protocol/`.
- Host-specific protocol payloads and snapshots stay in their domain crate.

Python under `yoyopod_cli/` is operations and validation tooling. It is not in
the runtime event path.
