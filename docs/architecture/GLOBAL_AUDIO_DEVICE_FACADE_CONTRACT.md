# YoYoPod Global Audio Device Facade Contract

**Last Updated:** 2026-05-06
**Status:** Rust target contract

## Problem Statement

YoYoPod has one physical audio stack, but several Rust hosts need audio routes:

- `device/media/` launches `mpv` for local playback.
- `device/voip/` owns Liblinphone playback, ringer, capture, and media IDs.
- `device/speech/` owns command capture and prompt playback.
- CLI validation still invokes target diagnostics for audio smoke checks.

The runtime needs one resolved hardware profile so music, calls, speech capture,
and spoken prompts do not drift into separate ALSA policies.

## Goals

- Establish one runtime-owned source of truth for input and output audio routes.
- Centralize ALSA mixer command policy behind one Rust-facing facade.
- Keep media, VoIP, speech, and prompt playback aligned to the same resolved
  hardware profile unless config explicitly overrides a role.
- Preserve config and environment override flexibility.
- Make effective device selection visible in runtime logs, CLI status, and Pi
  validation output.

## Non-Goals

- Replace `mpv`, Liblinphone, `arecord`, or `aplay`.
- Redesign call interruption or media playback policy.
- Add a user-facing audio routing UI in this phase.
- Solve advanced hot-plug or multi-device profile management beyond the current
  Pi target.

## Contract

### 1. The runtime owns one resolved audio profile

At startup, `device/runtime/` resolves the effective audio profile for the app
run and passes role-specific selectors to workers.

The profile should include:

- media playback output
- call playback output
- call ringer output
- capture input
- speech prompt output
- output mixer controls
- capture mixer controls and startup tuning

Workers consume this resolved profile. They should not independently decide
system-wide ALSA defaults.

### 2. ALSA policy lives behind one facade

Raw `amixer`, `aplay -L`, `arecord -L`, ALSA-name normalization, and startup
mixer policy should live behind a shared Rust audio layer or runtime-owned
helper.

Workers may still execute domain-specific subprocesses, but system-wide audio
defaults should come from the shared resolver.

### 3. Shared defaults come first, explicit overrides remain allowed

The resolver applies shared defaults first and then layers role overrides:

- one default output route for media and prompts
- one default capture route for speech and calls
- optional explicit per-role overrides when the product needs them

Per-role divergence must be configuration, not accidental drift.

### 4. The profile must support each backend shape

The facade must produce backend-specific selectors for:

- `mpv`
- Liblinphone
- `arecord`
- `aplay`
- future ALSA-backed helpers

That includes mapping friendly config values such as `ALSA: wm8960-soundcard`
into the concrete form each backend expects.

### 5. Mixer state is app state

Output volume, mic capture tuning, mute, and boost settings are app-level state
with one owner. No worker should silently re-apply conflicting mixer gain after
startup.

## Suggested Rust Shape

The preferred home is a shared Rust module or crate consumed by runtime and
workers:

- `device/runtime/` owns startup resolution and log/status reporting.
- `device/protocol/` carries any profile fields that cross worker boundaries.
- `device/media/`, `device/voip/`, and `device/speech/` receive resolved role
  selectors in their config/start envelopes.

Suggested models:

- `ResolvedAudioProfile`
- `AudioRoleRoutes`
- `AudioMixerProfile`
- `AudioRouteOverrides`
- `AudioHardwareInventory`

These should be typed models, not loose maps.

## Configuration Contract

Audio routing should be shared configuration first and backend-specific
configuration second.

Suggested direction:

- keep SIP behavior in `config/communication/calling.yaml`
- keep media behavior in `config/audio/music.yaml`
- keep shared physical device truth in `config/device/hardware.yaml`
- route env overrides through the shared resolver

Illustrative shape:

```yaml
audio:
  output_device: default
  capture_device: "ALSA: wm8960-soundcard"
  ringer_device: inherit
  media_device: inherit
  prompt_output_device: inherit
  mixer:
    output_controls: ["Speaker", "Headphone", "Playback"]
    capture_control: "Capture"
    adc_pcm_value: 195
    enable_input_boost: true
    mic_gain: 80
```

The exact key names can change. The contract is that device and mixer policy
are globally owned by the Rust runtime stack.

## Verification Contract

Required coverage:

- Rust checks for route resolution and ALSA command generation.
- Pi validation showing the runtime wires one resolved profile into media,
  calls, speech, and prompts.
- Pi validation showing the same effective routes after restart.
- Runtime logs and status commands showing the resolved profile.

## Acceptance Criteria

- One runtime-owned facade resolves audio devices and mixer policy for the app
  run.
- No worker issues ad hoc startup ALSA policy commands outside the shared audio
  subsystem.
- Media playback, calls, speech commands, and spoken prompts use the intended
  WM8960 routes by default on the Pi.
- Output volume and mic capture tuning remain stable across restarts.
- Config and env overrides still work, but now flow through one resolver.

## Rollout Outline

1. Inventory ALSA and device-selection call sites in Rust workers and CLI
   validation.
2. Introduce typed resolved-audio models and the shared facade.
3. Move mixer command generation out of feature workers.
4. Wire `mpv`, Liblinphone, speech capture, and prompt playback through the
   resolved profile.
5. Add build checks and Pi status reporting for the resolved profile.
