# YoYoPod System Architecture

**Last updated:** 2026-05-06
**Status:** Current implementation

YoYoPod is now Rust-first. The supported app runtime is the Rust
`yoyopod-runtime` binary in `device/runtime`; Python is operations tooling only.

## Runtime Owner

Supported runtime launch surfaces:

- `device/runtime/build/yoyopod-runtime --config-dir config`
- release-slot launch through `deploy/scripts/launch.sh`, which starts the
  packaged Rust runtime from the slot root

Unsupported runtime launch surfaces:

- the retired Python launcher
- imports from the retired Python app package
- any `yoyopod.*` Python app-runtime package

The installed `yoyopod` console entrypoint in `pyproject.toml` belongs to
`yoyopod_cli`. It is the operations CLI, not the app runtime.

## Rust Workspace

Current device code lives under `device/`:

- `device/runtime/`: process owner, config loading, worker supervision, state
  composition, event routing, and UI snapshot dispatch
- `device/protocol/`: shared NDJSON envelope/schema contract
- `device/worker/`: shared worker loop helpers
- `device/harness/`: protocol and host test harnesses
- `device/cloud/`: cloud MQTT/telemetry host
- `device/media/`: local music and mpv ownership
- `device/network/`: SIM7600, PPP, and GPS ownership
- `device/power/`: PiSugar power ownership
- `device/speech/`: speech host for ASK/voice command work
- `device/ui/`: Whisplay/LVGL rendering host
- `device/voip/`: Liblinphone/SIP ownership

## Runtime Topology

```text
yoyopod-runtime
  -> load composed config from config/
  -> initialize logging, PID, and startup status
  -> spawn supervised Rust hosts
       -> cloud-host
       -> media-host
       -> network-host
       -> power-host
       -> speech-host
       -> ui-host
       -> voip-host
  -> exchange NDJSON protocol envelopes over stdin/stdout
  -> route host events into app state
  -> apply power, voice, call, media, network, and cloud state
  -> send UI snapshots to the UI host
  -> stop workers and emit shutdown status on exit
```

Each host is a sidecar process with a narrow domain owner. The runtime owns
orchestration and policy; hosts own hardware/backend integration details.

## Python Surface

Python remains in the repo for:

- `yoyopod_cli/` operations commands
- deploy, release, slot, and Pi validation helpers
- compatibility support modules that the CLI still uses

The retired Python app runtime has been deleted. Active code must not import a
`yoyopod.*` Python app-runtime package.

## Packaging

The Python package wheel contains `yoyopod_cli` only. Release slots copy the
active application sources under `app/device` and `app/yoyopod_cli`; they do not
package a Python app-runtime package.

## Source Of Truth

When docs disagree, trust sources in this order:

1. Current Rust runtime and hosts under `device/`
2. Current deploy/runtime tooling in `deploy/` and `yoyopod_cli/`
3. Current operations and architecture docs
4. `rules/`, `AGENTS.md`, and `skills/`
5. Historical plans and archived material
